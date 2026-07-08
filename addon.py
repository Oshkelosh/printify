"""
Printify print-on-demand supplier integration.

Provides product sync, order creation, and fulfillment through the Printify API.
"""

from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter
from pydantic import BaseModel, Field, SecretStr

from app.addons.suppliers.base import SupplierAddon
from app.addons.suppliers.printify.catalog import normalize_printify_catalog_products
from app.addons.suppliers.printify.client import (
    PrintifyAPIError,
    PrintifyClient,
    build_line_items,
    map_address_to,
)
from schemas.supplier import SupplierCatalogProduct
from app.addons.log import info, warning
from app.addons.config_serialization import dump_addon_config


class PrintifyConfig(BaseModel):
    """Configuration for the Printify supplier addon."""

    api_key: SecretStr = Field(default=..., description="Printify Personal Access Token")
    shop_id: str = Field(default=..., min_length=1, description="Printify shop ID")
    is_active: bool = Field(default=False, description="Whether the addon is active")
    auto_confirm: bool = Field(
        default=True,
        description="Send orders to production after creation (manual approval shops)",
    )

    @classmethod
    def config_model(cls):
        return cls


class PrintifyAddon(SupplierAddon):
    """Printify print-on-demand supplier."""

    requires_variant_id = True

    addon_id: str = "printify"
    addon_name: str = "Printify"
    addon_description: str = "Print-on-demand supplier via Printify."
    addon_category: str = "supplier"
    version: str = "1.0.0"

    _config: Dict[str, Any] | None = None
    _client: PrintifyClient | None = None

    @classmethod
    def config_schema(cls):
        return PrintifyConfig

    async def initialize(self, config: dict) -> None:
        schema = self.config_schema()
        validated = schema(**config)
        self._config = dump_addon_config(validated)
        self._client = PrintifyClient(
            validated.api_key.get_secret_value(),
            validated.shop_id,
        )
        self.is_enabled = validated.is_active
        info("Printify", "Initialized shop_id={} auto_confirm={}",
            validated.shop_id,
            validated.auto_confirm,
        )

    async def validate_config(self, config: dict) -> None:
        from app.core.exceptions import ValidationError

        validated = self.config_schema()(**config)
        api_key = validated.api_key.get_secret_value()
        if not api_key:
            return
        client = PrintifyClient(api_key, validated.shop_id)
        try:
            await client.list_products(limit=1)
        except PrintifyAPIError as exc:
            if exc.status_code == 401:
                raise ValidationError(message="Invalid API key — check your credentials") from exc
            if exc.status_code == 403:
                raise ValidationError(
                    message="API key is valid but missing required permissions: catalog:read"
                ) from exc
            raise ValidationError(message=f"Printify API error: {exc}") from exc

    async def shutdown(self) -> None:
        self._client = None
        self._config = None
        self.is_enabled = False

    def admin_form_hints(self) -> dict[str, str | bool]:
        return {
            "requires_variant_id": True,
            "product_id_help": "Required. Printify shop product ID.",
            "variant_id_help": "Required. Printify variant ID.",
        }

    def _require_client(self) -> PrintifyClient:
        if self._client is None:
            raise PrintifyAPIError("Printify addon is not initialized")
        return self._client

    def _flatten_shop_product(self, product: dict[str, Any]) -> List[Dict[str, Any]]:
        product_id = product.get("id", "")
        title = product.get("title", "Unknown")
        description = product.get("description")
        visible = product.get("visible", True)
        images = product.get("images") or []
        rows: List[Dict[str, Any]] = []
        for variant in product.get("variants") or []:
            if not isinstance(variant, dict):
                continue
            variant_id = variant.get("id")
            variant_id_str = str(variant_id) if variant_id is not None else ""
            rows.append(
                {
                    "id": variant_id_str,
                    "product_id": str(product_id),
                    "variant_id": variant_id_str,
                    "title": variant.get("title") or title,
                    "description": description,
                    "visible": visible,
                    "images": images,
                    "sku": variant.get("sku"),
                    "price": variant.get("price"),
                    "is_enabled": variant.get("is_enabled", True),
                }
            )
        return rows

    async def _resolve_shop_product(
        self,
        client: PrintifyClient,
        product: dict[str, Any],
    ) -> dict[str, Any]:
        variants = product.get("variants")
        if isinstance(variants, list) and variants:
            return product
        product_id = str(product.get("id") or "").strip()
        if not product_id:
            return product
        try:
            detail = await client.get_product(product_id)
            if isinstance(detail, dict):
                return detail
        except PrintifyAPIError as exc:
            warning("Printify", "catalog sync: get_product({}) failed: {}", product_id, exc)
        return product

    async def list_products(self, **kwargs: Any) -> List[Dict[str, Any]]:
        client = self._require_client()
        products: List[Dict[str, Any]] = []
        page = 1
        limit = 50
        while True:
            data = await client.list_products(page=page, limit=limit)
            batch = data.get("data") or data.get("products") or []
            if not isinstance(batch, list):
                break
            for product in batch:
                if not isinstance(product, dict):
                    continue
                resolved = await self._resolve_shop_product(client, product)
                products.extend(self._flatten_shop_product(resolved))
            if len(batch) < limit:
                break
            page += 1
        return products

    async def fetch_catalog_for_import(self, **kwargs: Any) -> List[SupplierCatalogProduct]:
        raw = await self.list_products(**kwargs)
        return normalize_printify_catalog_products(raw)

    async def get_product(self, product_id: str) -> Dict[str, Any]:
        client = self._require_client()
        return await client.get_product(product_id)

    async def create_order(
        self,
        items: List[Dict[str, Any]],
        shipping_address: Dict[str, Any],
        *,
        external_id: str | None = None,
        supplier_ref: str | None = None,
    ) -> Dict[str, Any]:
        del supplier_ref
        client = self._require_client()
        try:
            line_items = build_line_items(items)
            if not line_items:
                return {"success": False, "error": "No valid Printify line items"}

            payload: Dict[str, Any] = {
                "line_items": line_items,
                "shipping_method": 1,
                "send_shipping_notification": False,
                "address_to": map_address_to(shipping_address),
            }
            if external_id:
                payload["external_id"] = external_id

            data = await client.create_order(payload)
            order_id = str(data.get("id", ""))
            if not order_id:
                return {"success": False, "error": "Printify did not return an order id"}

            confirm = bool(self._config.get("auto_confirm", True)) if self._config else True
            status = "created"
            if confirm:
                prod_data = await client.send_to_production(order_id)
                order_id = str(prod_data.get("id", order_id))
                status = "sent_to_production"

            return {
                "success": True,
                "order_id": order_id,
                "status": status,
                "printify_order_id": order_id,
            }
        except PrintifyAPIError as exc:
            warning("Printify", "create_order error: {}", exc)
            return {"success": False, "error": str(exc)}

    async def get_order_status(self, order_id: str) -> Dict[str, Any]:
        client = self._require_client()
        try:
            data = await client.get_order(order_id)
            return {
                "order_id": order_id,
                "status": data.get("status", "unknown"),
            }
        except PrintifyAPIError as exc:
            warning("Printify", "get_order_status({}) error: {}", order_id, exc)
            return {"order_id": order_id, "status": "error", "detail": str(exc)}

    async def sync_inventory(self) -> None:
        products = await self.list_products()
        info("Printify", "Synced {} product variants", len(products))

    def get_routers(self) -> List[APIRouter]:
        from app.addons.suppliers.printify.routes import api_router

        return [api_router]

    def get_admin_routes(self) -> List[APIRouter]:
        from app.addons.suppliers.printify.routes import admin_router

        return [admin_router]

    def get_admin_templates(self) -> str:
        from pathlib import Path

        return str(Path(__file__).resolve().parent / "templates")

    def get_admin_static(self) -> str:
        from pathlib import Path

        return str(Path(__file__).resolve().parent / "static")

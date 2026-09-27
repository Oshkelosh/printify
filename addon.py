"""
Printify print-on-demand supplier integration.

Provides product sync, order creation, and fulfillment through the Printify API.
"""

from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter
from pydantic import BaseModel, Field, SecretStr

from app.addons.suppliers.base import SupplierAddon
from app.addons.suppliers.printify.catalog import (
    build_printify_option_value_index,
    normalize_printify_catalog_products,
    resolve_printify_blueprint_product_type,
    resolve_printify_variant_options,
)
from app.addons.suppliers.printify.client import (
    PrintifyAPIError,
    PrintifyClient,
    build_line_items,
    map_address_to,
    parse_shipping_rate_options,
    resolve_shipping_method_id,
)
from schemas.supplier import SupplierCatalogProduct
from app.addons.log import exception, info, warning
from app.addons.config_serialization import dump_addon_config


class PrintifyConfig(BaseModel):
    """Configuration for the Printify supplier addon."""

    api_key: SecretStr = Field(default=..., description="Printify Personal Access Token")
    shop_id: str = Field(
        default="",
        description="Printify shop ID (auto-discovered when empty and the token has one shop)",
    )
    is_active: bool = Field(default=False, description="Whether the addon is active")
    auto_confirm: bool = Field(
        default=True,
        description="Send orders to production after creation (manual approval shops)",
    )
    webhook_secret: SecretStr = Field(
        default="",
        description="HMAC secret for Printify webhook signature verification",
    )

    @classmethod
    def config_model(cls):
        return cls


async def resolve_printify_shop_id(api_key: str, shop_id: str = "") -> str:
    """Resolve shop_id from config or GET /shops.json (Printify never shows it in the UI)."""
    from app.core.exceptions import ValidationError

    existing = str(shop_id or "").strip()
    if existing:
        return existing

    client = PrintifyClient(api_key)
    try:
        shops = await client.list_shops()
    except PrintifyAPIError as exc:
        if exc.status_code == 401:
            raise ValidationError(message="Invalid API key — check your credentials") from exc
        if exc.status_code == 403:
            raise ValidationError(
                message="API key is valid but missing required permissions: shops.read"
            ) from exc
        raise ValidationError(message=f"Printify API error: {exc}") from exc

    if len(shops) == 1:
        shop = shops[0]
        resolved = str(shop.get("id") or "").strip()
        if not resolved:
            raise ValidationError(message="Printify returned a shop without an id")
        return resolved

    if not shops:
        raise ValidationError(
            message=(
                "No Printify shops for this token. "
                "In Printify go to My Stores → Add store → API, then save again."
            )
        )

    listing = ", ".join(
        f"{row.get('id')} ({row.get('title') or 'untitled'})" for row in shops
    )
    raise ValidationError(
        message=(
            f"This token has multiple Printify shops: {listing}. "
            "Set Shop ID (multi-shop override) to the shop you want."
        )
    )


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
    _blueprint_title_cache: Dict[int, str] | None = None

    @classmethod
    def config_schema(cls):
        return PrintifyConfig

    async def initialize(self, config: dict) -> None:
        schema = self.config_schema()
        validated = schema(**config)
        api_key = validated.api_key.get_secret_value()
        shop_id = await resolve_printify_shop_id(api_key, validated.shop_id)
        config["shop_id"] = shop_id
        self._config = {**dump_addon_config(validated), "shop_id": shop_id}
        self._client = PrintifyClient(api_key, shop_id)
        self.is_enabled = validated.is_active
        info(
            "Printify",
            "Initialized shop_id={} auto_confirm={}",
            shop_id,
            validated.auto_confirm,
        )

    async def validate_config(self, config: dict) -> None:
        from app.core.exceptions import ValidationError

        validated = self.config_schema()(**config)
        api_key = validated.api_key.get_secret_value()
        if not api_key:
            return
        try:
            shop_id = await resolve_printify_shop_id(api_key, validated.shop_id)
            config["shop_id"] = shop_id
            client = PrintifyClient(api_key, shop_id)
            await client.list_products(limit=1)
        except ValidationError:
            raise
        except PrintifyAPIError as exc:
            if exc.status_code == 401:
                raise ValidationError(message="Invalid API key — check your credentials") from exc
            if exc.status_code == 403:
                raise ValidationError(
                    message="API key is valid but missing required permissions: products.read"
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
        product_title = str(product.get("title") or "Unknown").strip() or "Unknown"
        description = product.get("description")
        visible = product.get("visible", True)
        images = product.get("images") or []
        blueprint_id = product.get("blueprint_id")
        option_index = build_printify_option_value_index(product.get("options"))
        rows: List[Dict[str, Any]] = []
        for variant in product.get("variants") or []:
            if not isinstance(variant, dict):
                continue
            variant_id = variant.get("id")
            variant_id_str = str(variant_id) if variant_id is not None else ""
            row: Dict[str, Any] = {
                "id": variant_id_str,
                "product_id": str(product_id),
                "variant_id": variant_id_str,
                "product_title": product_title,
                "title": variant.get("title") or product_title,
                "description": description,
                "visible": visible,
                "images": images,
                "blueprint_id": blueprint_id,
                "sku": variant.get("sku"),
                "price": variant.get("price"),
                "is_enabled": variant.get("is_enabled", True),
            }
            options = variant.get("options")
            if isinstance(options, dict):
                row["options"] = options
            elif isinstance(options, list):
                resolved = resolve_printify_variant_options(options, option_index)
                if resolved:
                    row["options"] = resolved
            rows.append(row)
        return rows

    async def _enrich_rows_with_product_type(
        self,
        client: PrintifyClient,
        rows: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        cache = self._blueprint_title_cache
        if cache is None:
            return rows
        for row in rows:
            if row.get("product_type"):
                continue
            product_type = await resolve_printify_blueprint_product_type(
                client,
                row.get("blueprint_id"),
                catalog_cache=cache,
            )
            if product_type:
                row["product_type"] = product_type
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
        client = self._require_client()
        self._blueprint_title_cache = {}
        try:
            raw = await self.list_products(**kwargs)
            raw = await self._enrich_rows_with_product_type(client, raw)
            return normalize_printify_catalog_products(raw)
        finally:
            self._blueprint_title_cache = None

    async def after_catalog_sync(self, session: Any, result: Any) -> None:
        from app.addons.suppliers.printify.publish import acknowledge_touched_products

        keys = list(getattr(result, "touched_product_keys", []) or [])
        if not keys:
            return
        client = self._require_client()
        errors = await acknowledge_touched_products(client, session, keys)
        for message in errors:
            result.errors.append(message)

    async def get_product(self, product_id: str) -> Dict[str, Any]:
        client = self._require_client()
        return await client.get_product(product_id)

    def supports_shipping_quotes(self) -> bool:
        return True

    async def quote_shipping(
        self,
        items: List[Dict[str, Any]],
        shipping_address: Dict[str, Any],
        *,
        currency: str | None = None,
    ) -> int | None:
        """Live Printify rates; prefer standard, else cheapest. None → Site Settings."""
        details = await self.quote_shipping_details(items, shipping_address, currency=currency)
        if details is None:
            return None
        return int(details["cents"])

    async def quote_shipping_details(
        self,
        items: List[Dict[str, Any]],
        shipping_address: Dict[str, Any],
        *,
        selected_id: str | None = None,
        currency: str | None = None,
    ) -> Dict[str, Any] | None:
        """Live Printify methods with prices; selected_id overrides the default."""
        if currency and str(currency).upper() != "USD":
            # Printify quotes shipping in USD only; returning those cents under a
            # different shop currency would mix units. Fall back to Site Settings.
            return None
        from app.addons.suppliers.shipping_quote import pick_shipping_option

        client = self._require_client()
        try:
            line_items = build_line_items(items)
            if not line_items:
                return None
            rates = await client.calculate_shipping(
                line_items,
                map_address_to(shipping_address or {}),
            )
            options = parse_shipping_rate_options(rates)
            chosen = pick_shipping_option(
                options,
                selected_id=selected_id,
                preferred_ids=("standard",),
            )
            if chosen is None:
                return None
            return {
                "cents": int(chosen["cents"]),
                "selected_id": str(chosen["id"]),
                "options": options,
            }
        except PrintifyAPIError as exc:
            warning("Printify", "quote_shipping error: {}", exc)
            return None
        except Exception:
            exception("Printify", "quote_shipping unexpected error")
            return None

    async def create_order(
        self,
        items: List[Dict[str, Any]],
        shipping_address: Dict[str, Any],
        *,
        external_id: str | None = None,
        supplier_ref: str | None = None,
        shipping_method: str | None = None,
        currency: str | None = None,
        gift_message: str | None = None,
        packing_slip: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        del supplier_ref, currency, gift_message, packing_slip
        client = self._require_client()
        try:
            line_items = build_line_items(items)
            if not line_items:
                return {"success": False, "error": "No valid Printify line items"}

            payload: Dict[str, Any] = {
                "line_items": line_items,
                "shipping_method": resolve_shipping_method_id(shipping_method),
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

"""Printify API client."""

from __future__ import annotations

from typing import Any

import httpx

PRINTIFY_BASE = "https://api.printify.com/v1"


class PrintifyAPIError(Exception):
    """Raised when the Printify API returns an error response."""

    def __init__(self, message: str, status_code: int | None = None, body: Any = None):
        super().__init__(message)
        self.status_code = status_code
        self.body = body


class PrintifyClient:
    """Thin async wrapper around Printify REST endpoints."""

    def __init__(self, api_key: str, shop_id: str, *, timeout: float = 30.0):
        self._api_key = api_key
        self._shop_id = str(shop_id)
        self._timeout = timeout

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        url = f"{PRINTIFY_BASE}{path}"
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.request(
                method,
                url,
                headers=self._headers(),
                params=params,
                json=json,
            )
        try:
            data = resp.json()
        except Exception:
            data = {"raw": resp.text}
        if resp.status_code >= 400:
            message = resp.text
            if isinstance(data, dict):
                message = data.get("message") or data.get("error") or message
            raise PrintifyAPIError(str(message), status_code=resp.status_code, body=data)
        return data if isinstance(data, dict) else {"data": data}

    async def list_products(self, *, page: int = 1, limit: int = 50) -> dict[str, Any]:
        return await self._request(
            "GET",
            f"/shops/{self._shop_id}/products.json",
            params={"page": page, "limit": limit},
        )

    async def get_product(self, product_id: str) -> dict[str, Any]:
        return await self._request(
            "GET",
            f"/shops/{self._shop_id}/products/{product_id}.json",
        )

    async def create_order(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._request(
            "POST",
            f"/shops/{self._shop_id}/orders.json",
            json=payload,
        )

    async def send_to_production(self, order_id: str) -> dict[str, Any]:
        return await self._request(
            "POST",
            f"/shops/{self._shop_id}/orders/{order_id}/send_to_production.json",
        )

    async def get_order(self, order_id: str) -> dict[str, Any]:
        return await self._request(
            "GET",
            f"/shops/{self._shop_id}/orders/{order_id}.json",
        )


def map_address_to(shipping_address: dict[str, Any]) -> dict[str, str]:
    """Map Oshkelosh shipping_address keys to Printify address_to fields."""
    first = shipping_address.get("first_name", "")
    last = shipping_address.get("last_name", "")
    address: dict[str, str] = {
        "first_name": first or "Customer",
        "last_name": last or "",
        "country": shipping_address.get("country")
        or shipping_address.get("country_code")
        or "US",
        "address1": shipping_address.get("line1") or shipping_address.get("address1") or "",
        "city": shipping_address.get("city", ""),
        "zip": shipping_address.get("zip") or shipping_address.get("postal_code") or "",
        "region": shipping_address.get("state") or shipping_address.get("state_code") or "",
    }
    line2 = shipping_address.get("line2") or shipping_address.get("address2")
    if line2:
        address["address2"] = str(line2)
    email = shipping_address.get("email")
    if email:
        address["email"] = str(email)
    phone = shipping_address.get("phone")
    if phone:
        address["phone"] = str(phone)
    return address


def build_line_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert fulfillment items to Printify order line items."""
    line_items: list[dict[str, Any]] = []
    for item in items:
        product_id = item.get("supplier_product_id")
        variant_raw = item.get("supplier_variant_id")
        if not product_id or not variant_raw:
            continue
        try:
            variant_id = int(variant_raw)
        except (TypeError, ValueError) as exc:
            raise PrintifyAPIError(f"Invalid variant_id: {variant_raw}") from exc
        quantity = item.get("quantity", 1)
        try:
            qty = int(quantity)
        except (TypeError, ValueError):
            qty = 1
        line_items.append(
            {
                "product_id": str(product_id),
                "variant_id": variant_id,
                "quantity": max(qty, 1),
            }
        )
    return line_items

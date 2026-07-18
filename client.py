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

    async def calculate_shipping(
        self,
        line_items: list[dict[str, Any]],
        address_to: dict[str, Any],
    ) -> dict[str, Any]:
        """POST orders/shipping.json — shipping costs (in cents) for a cart."""
        return await self._request(
            "POST",
            f"/shops/{self._shop_id}/orders/shipping.json",
            json={"line_items": line_items, "address_to": address_to},
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
    from app.addons.suppliers.address import canonical_address

    addr = canonical_address(shipping_address)
    address: dict[str, str] = {
        "first_name": addr["first_name"],
        "last_name": addr["last_name"],
        "country": addr["country_code"] or "US",
        "address1": addr["line1"],
        "city": addr["city"],
        "zip": addr["zip"],
        "region": addr["state"],
    }
    for src, dst in (("line2", "address2"), ("email", "email"), ("phone", "phone")):
        if addr[src]:
            address[dst] = addr[src]
    return address


# Printify order ``shipping_method`` integers (docs /orders).
PRINTIFY_SHIPPING_METHOD_IDS: dict[str, int] = {
    "standard": 1,
    "priority": 2,
    "express": 3,
    "printify_express": 3,
    "economy": 4,
}


def parse_shipping_rate_options(rates: Any) -> list[dict[str, Any]]:
    """Normalize Printify shipping.json into checkout options."""
    if not isinstance(rates, dict):
        return []
    options: list[dict[str, Any]] = []
    for method, value in rates.items():
        try:
            cents = int(value)
        except (TypeError, ValueError):
            continue
        if cents <= 0:
            continue
        option_id = str(method).strip().lower()
        if not option_id:
            continue
        options.append(
            {
                "id": option_id,
                "name": option_id.replace("_", " ").title(),
                "cents": cents,
            }
        )
    return options


def pick_shipping_cents(rates: dict[str, Any]) -> int | None:
    """Printify returns integer cents per method; prefer standard, else cheapest.

    Response shape: ``{"standard": 450, "express": 900, "economy": 350, ...}``.
    Non-positive or non-integer values are ignored.
    """
    from app.addons.suppliers.shipping_quote import pick_shipping_option

    chosen = pick_shipping_option(
        parse_shipping_rate_options(rates),
        preferred_ids=("standard",),
    )
    return int(chosen["cents"]) if chosen else None


def resolve_shipping_method_id(shipping_method: str | None) -> int:
    """Map a checkout selection (name or int string) to Printify's method int."""
    if shipping_method is None or not str(shipping_method).strip():
        return 1
    raw = str(shipping_method).strip()
    try:
        return int(raw)
    except ValueError:
        pass
    return PRINTIFY_SHIPPING_METHOD_IDS.get(raw.lower(), 1)


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

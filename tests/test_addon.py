"""Unit tests for the Printify supplier addon."""

from unittest.mock import AsyncMock

import pytest

from app.addons.suppliers.printify.addon import PrintifyAddon, PrintifyConfig


class TestPrintifyAddon:
    def test_printify_addon_has_required_attrs(self):
        assert PrintifyAddon.addon_id == "printify"
        assert PrintifyAddon.addon_category == "supplier"

    def test_printify_config_schema(self):
        config = PrintifyConfig(
            api_key="test-token",
            shop_id="12345",
            is_active=True,
            auto_confirm=False,
        )
        assert config.api_key.get_secret_value() == "test-token"
        assert config.shop_id == "12345"
        assert config.auto_confirm is False

    def test_printify_config_requires_api_key_and_shop_id(self):
        with pytest.raises(Exception):
            PrintifyConfig()

    def test_supports_shipping_quotes(self):
        assert PrintifyAddon().supports_shipping_quotes() is True

    @pytest.mark.asyncio
    async def test_quote_shipping_returns_cents(self):
        addon = PrintifyAddon()
        addon._client = AsyncMock()
        addon._client.calculate_shipping = AsyncMock(
            return_value={"standard": 599, "express": 1200}
        )
        cents = await addon.quote_shipping(
            [
                {
                    "supplier_product_id": "prod-1",
                    "supplier_variant_id": "17887",
                    "quantity": 1,
                }
            ],
            {"country": "US", "zip": "97201"},
        )
        assert cents == 599

    @pytest.mark.asyncio
    async def test_quote_shipping_returns_none_on_api_error(self):
        from app.addons.suppliers.printify.client import PrintifyAPIError

        addon = PrintifyAddon()
        addon._client = AsyncMock()
        addon._client.calculate_shipping = AsyncMock(
            side_effect=PrintifyAPIError("bad request", status_code=400)
        )
        cents = await addon.quote_shipping(
            [
                {
                    "supplier_product_id": "prod-1",
                    "supplier_variant_id": "17887",
                    "quantity": 1,
                }
            ],
            {"country": "US"},
        )
        assert cents is None

    @pytest.mark.asyncio
    async def test_quote_shipping_details_honors_selected_method(self):
        addon = PrintifyAddon()
        addon._client = AsyncMock()
        addon._client.calculate_shipping = AsyncMock(
            return_value={"standard": 599, "express": 1200}
        )
        details = await addon.quote_shipping_details(
            [
                {
                    "supplier_product_id": "prod-1",
                    "supplier_variant_id": "17887",
                    "quantity": 1,
                }
            ],
            {"country": "US"},
            selected_id="express",
        )
        assert details is not None
        assert details["cents"] == 1200
        assert details["selected_id"] == "express"
        assert [row["id"] for row in details["options"]] == ["standard", "express"]

    @pytest.mark.asyncio
    async def test_create_order_sends_shipping_method(self):
        addon = PrintifyAddon()
        addon._config = {"auto_confirm": False}
        addon._client = AsyncMock()
        addon._client.create_order = AsyncMock(return_value={"id": "ord-1"})
        result = await addon.create_order(
            [
                {
                    "supplier_product_id": "prod-1",
                    "supplier_variant_id": "17887",
                    "quantity": 1,
                }
            ],
            {"line1": "1 Main", "city": "Austin", "zip": "78701", "country": "US"},
            shipping_method="express",
        )
        assert result["success"] is True
        payload = addon._client.create_order.await_args.args[0]
        assert payload["shipping_method"] == 3


@pytest.mark.asyncio
async def test_list_products_fetches_detail_when_variants_missing():
    addon = PrintifyAddon()
    addon._client = AsyncMock()
    addon._config = {"api_key": "tok", "shop_id": "shop1", "is_active": True}
    addon._client.list_products.return_value = {
        "data": [{"id": "prod-1", "title": "Tee", "visible": True}],
    }
    addon._client.get_product.return_value = {
        "id": "prod-1",
        "title": "Tee",
        "visible": True,
        "variants": [
            {"id": 101, "title": "M", "price": 2000, "is_enabled": True},
            {"id": 102, "title": "L", "price": 2100, "is_enabled": True},
        ],
        "images": [],
    }

    rows = await addon.list_products()

    addon._client.get_product.assert_awaited_once_with("prod-1")
    assert len(rows) == 2
    assert {row["variant_id"] for row in rows} == {"101", "102"}

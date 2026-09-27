"""Unit tests for the Printify supplier addon."""

from unittest.mock import AsyncMock, patch

import pytest

from app.addons.suppliers.printify.addon import (
    PrintifyAddon,
    PrintifyConfig,
    resolve_printify_shop_id,
)
from app.core.exceptions import ValidationError


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
            webhook_secret="whsec",
        )
        assert config.api_key.get_secret_value() == "test-token"
        assert config.shop_id == "12345"
        assert config.auto_confirm is False
        assert config.webhook_secret.get_secret_value() == "whsec"

    def test_printify_config_shop_id_optional(self):
        config = PrintifyConfig(api_key="test-token")
        assert config.shop_id == ""

    def test_printify_config_requires_api_key(self):
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
    async def test_validate_config_auto_fills_single_shop(self):
        addon = PrintifyAddon()
        config = {"api_key": "tok", "shop_id": "", "is_active": True, "auto_confirm": True}
        with (
            patch(
                "app.addons.suppliers.printify.addon.resolve_printify_shop_id",
                new_callable=AsyncMock,
                return_value="5432",
            ),
            patch("app.addons.suppliers.printify.addon.PrintifyClient") as client_cls,
        ):
            client = AsyncMock()
            client.list_products = AsyncMock(return_value={"data": []})
            client_cls.return_value = client
            await addon.validate_config(config)
        assert config["shop_id"] == "5432"
        client_cls.assert_called_with("tok", "5432")

    @pytest.mark.asyncio
    async def test_initialize_resolves_empty_shop_id(self):
        addon = PrintifyAddon()
        config = {"api_key": "tok", "shop_id": "", "is_active": True, "auto_confirm": False}
        with patch(
            "app.addons.suppliers.printify.addon.resolve_printify_shop_id",
            new_callable=AsyncMock,
            return_value="9876",
        ):
            await addon.initialize(config)
        assert config["shop_id"] == "9876"
        assert addon._client is not None
        assert addon._client._shop_id == "9876"

    def test_flatten_keeps_product_title_and_blueprint(self):
        addon = PrintifyAddon()
        rows = addon._flatten_shop_product(
            {
                "id": "prod-1",
                "title": "Cool Tee",
                "description": "Soft",
                "blueprint_id": 12,
                "visible": True,
                "images": [],
                "variants": [
                    {
                        "id": 101,
                        "title": "Black / L",
                        "price": 2000,
                        "is_enabled": True,
                        "options": {"color": "Black", "size": "L"},
                    },
                ],
            }
        )
        assert len(rows) == 1
        assert rows[0]["product_title"] == "Cool Tee"
        assert rows[0]["title"] == "Black / L"
        assert rows[0]["blueprint_id"] == 12
        assert rows[0]["options"] == {"color": "Black", "size": "L"}

    def test_flatten_resolves_shop_option_ids(self):
        addon = PrintifyAddon()
        rows = addon._flatten_shop_product(
            {
                "id": "prod-1",
                "title": "Cool Tee",
                "description": "Soft",
                "blueprint_id": 12,
                "visible": True,
                "images": [],
                "options": [
                    {
                        "name": "Colors",
                        "type": "color",
                        "values": [
                            {"id": 123, "title": "Black"},
                            {"id": 124, "title": "White"},
                        ],
                    },
                    {
                        "name": "Sizes",
                        "type": "size",
                        "values": [
                            {"id": 456, "title": "L"},
                            {"id": 457, "title": "M"},
                        ],
                    },
                ],
                "variants": [
                    {
                        "id": 101,
                        "title": "Black / L",
                        "price": 2000,
                        "is_enabled": True,
                        "options": [123, 456],
                    },
                    {
                        "id": 102,
                        "title": "White / M",
                        "price": 2100,
                        "is_enabled": True,
                        "options": [124, 457],
                    },
                ],
            }
        )
        assert len(rows) == 2
        assert rows[0]["options"] == {"color": "Black", "size": "L"}
        assert rows[1]["options"] == {"color": "White", "size": "M"}

        from app.addons.suppliers.printify.catalog import normalize_printify_catalog_products

        products = normalize_printify_catalog_products(rows)
        assert [v.attributes for v in products[0].variants] == [
            {"Size": "L", "Color": "Black"},
            {"Size": "M", "Color": "White"},
        ]

    @pytest.mark.asyncio
    async def test_fetch_catalog_resolves_blueprint_type(self):
        addon = PrintifyAddon()
        addon._client = AsyncMock()
        addon._client.list_products = AsyncMock(
            return_value={
                "data": [
                    {
                        "id": "prod-1",
                        "title": "Cool Tee",
                        "description": "Soft",
                        "blueprint_id": 12,
                        "visible": True,
                        "images": [],
                        "variants": [
                            {
                                "id": 101,
                                "title": "Black / L",
                                "price": 2000,
                                "is_enabled": True,
                            }
                        ],
                    }
                ]
            }
        )
        with patch(
            "app.addons.suppliers.printify.addon.resolve_printify_blueprint_product_type",
            new_callable=AsyncMock,
            return_value="Unisex Jersey Short Sleeve Tee",
        ) as resolve:
            products = await addon.fetch_catalog_for_import()
        resolve.assert_awaited()
        assert len(products) == 1
        assert products[0].name == "Cool Tee"
        assert products[0].product_type == "Unisex Jersey Short Sleeve Tee"
        assert products[0].options["Product type"] == "Unisex Jersey Short Sleeve Tee"
        assert products[0].variants[0].title == "Cool Tee / Black / L"
        assert addon._blueprint_title_cache is None


class TestResolvePrintifyShopId:
    @pytest.mark.asyncio
    async def test_keeps_explicit_shop_id(self):
        assert await resolve_printify_shop_id("tok", "111") == "111"

    @pytest.mark.asyncio
    async def test_single_shop_auto_detect(self):
        with patch("app.addons.suppliers.printify.addon.PrintifyClient") as client_cls:
            client = AsyncMock()
            client.list_shops = AsyncMock(
                return_value=[{"id": 5432, "title": "API Store"}]
            )
            client_cls.return_value = client
            assert await resolve_printify_shop_id("tok", "") == "5432"

    @pytest.mark.asyncio
    async def test_zero_shops_error(self):
        with patch("app.addons.suppliers.printify.addon.PrintifyClient") as client_cls:
            client = AsyncMock()
            client.list_shops = AsyncMock(return_value=[])
            client_cls.return_value = client
            with pytest.raises(ValidationError, match="No Printify shops"):
                await resolve_printify_shop_id("tok", "")

    @pytest.mark.asyncio
    async def test_multi_shop_error(self):
        with patch("app.addons.suppliers.printify.addon.PrintifyClient") as client_cls:
            client = AsyncMock()
            client.list_shops = AsyncMock(
                return_value=[
                    {"id": 1, "title": "A"},
                    {"id": 2, "title": "B"},
                ]
            )
            client_cls.return_value = client
            with pytest.raises(ValidationError, match="multiple Printify shops"):
                await resolve_printify_shop_id("tok", "")


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

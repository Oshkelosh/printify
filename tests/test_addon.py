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

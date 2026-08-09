"""Unit tests for Printify catalog normalization."""

from unittest.mock import AsyncMock

import pytest

from app.addons.suppliers.printify.catalog import (
    build_printify_option_value_index,
    normalize_printify_catalog,
    normalize_printify_catalog_products,
    printify_plain_description,
    printify_variant_attributes_from_row,
    resolve_printify_blueprint_product_type,
    resolve_printify_variant_options,
    _printify_variant_image,
)


def test_printify_plain_description_strips_html():
    assert printify_plain_description(None) is None
    assert printify_plain_description("Already plain") == "Already plain"
    assert printify_plain_description("A &amp; B") == "A & B"
    assert printify_plain_description("<p>Soft <b>cotton</b> tee</p>") == "Soft cotton tee"
    assert printify_plain_description("<p>Line one</p><p>Line two</p>") == "Line one\n\nLine two"


def test_printify_variant_attributes_from_options():
    assert printify_variant_attributes_from_row({}) == {}
    assert printify_variant_attributes_from_row({"options": "nope"}) == {}
    assert printify_variant_attributes_from_row(
        {"options": {"color": "Black", "size": "L", "paper": "Matte"}}
    ) == {"Size": "L", "Color": "Black", "Paper": "Matte"}


def test_resolve_shop_option_ids():
    index = build_printify_option_value_index(
        [
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
        ]
    )
    assert index["123"] == ("color", "Black")
    assert index["456"] == ("size", "L")
    assert resolve_printify_variant_options([123, 456], index) == {
        "color": "Black",
        "size": "L",
    }
    assert resolve_printify_variant_options(["124", "457"], index) == {
        "color": "White",
        "size": "M",
    }
    assert printify_variant_attributes_from_row(
        {"options": resolve_printify_variant_options([123, 456], index)}
    ) == {"Size": "L", "Color": "Black"}


def test_normalize_products_maps_size_color_attributes():
    products = normalize_printify_catalog_products(
        [
            {
                "product_id": "p1",
                "variant_id": "101",
                "product_title": "Cool Tee",
                "title": "Black / L",
                "options": {"color": "Black", "size": "L"},
                "price": 2000,
                "is_enabled": True,
                "visible": True,
            },
            {
                "product_id": "p1",
                "variant_id": "102",
                "product_title": "Cool Tee",
                "title": "White / M",
                "options": {"color": "White", "size": "M"},
                "price": 2100,
                "is_enabled": True,
                "visible": True,
            },
        ]
    )
    assert len(products) == 1
    assert [v.attributes for v in products[0].variants] == [
        {"Size": "L", "Color": "Black"},
        {"Size": "M", "Color": "White"},
    ]


def test_normalize_products_strips_html_description():
    products = normalize_printify_catalog_products(
        [
            {
                "product_id": "p1",
                "variant_id": "101",
                "product_title": "Cool Tee",
                "title": "Black / L",
                "description": "<p>Soft <strong>cotton</strong></p>",
                "price": 2000,
                "is_enabled": True,
                "visible": True,
            }
        ]
    )
    assert products[0].description == "Soft cotton"


def test_printify_price_cents_passthrough():
    items = normalize_printify_catalog(
        [
            {
                "product_id": "abc",
                "variant_id": "17887",
                "title": "T-Shirt / M",
                "price": 2499,
                "is_enabled": True,
                "visible": True,
            }
        ]
    )
    assert len(items) == 1
    assert items[0].price_cents == 2499
    assert items[0].external_key == "printify:abc:17887"


def test_printify_skips_disabled_variant():
    items = normalize_printify_catalog(
        [
            {
                "product_id": "abc",
                "variant_id": "99",
                "title": "Disabled",
                "is_enabled": False,
                "visible": True,
            }
        ]
    )
    assert len(items) == 1
    assert items[0].skip_reason == "Printify variant is disabled"


def test_normalize_products_uses_shop_product_title():
    products = normalize_printify_catalog_products(
        [
            {
                "product_id": "p1",
                "variant_id": "101",
                "product_title": "Cool Tee",
                "title": "Black / L",
                "description": "Soft cotton",
                "price": 2000,
                "is_enabled": True,
                "visible": True,
                "product_type": "Unisex Heavy Cotton Tee",
                "images": [
                    {
                        "src": "https://cdn.example/default.jpg",
                        "variant_ids": [101],
                        "is_default": True,
                    },
                    {
                        "src": "https://cdn.example/black.jpg",
                        "variant_ids": ["101"],
                        "is_default": False,
                    },
                ],
            },
            {
                "product_id": "p1",
                "variant_id": "102",
                "product_title": "Cool Tee",
                "title": "White / M",
                "description": "Soft cotton",
                "price": 2100,
                "is_enabled": True,
                "visible": True,
                "product_type": "Unisex Heavy Cotton Tee",
                "images": [
                    {
                        "src": "https://cdn.example/default.jpg",
                        "variant_ids": [101],
                        "is_default": True,
                    },
                ],
            },
        ]
    )
    assert len(products) == 1
    product = products[0]
    assert product.name == "Cool Tee"
    assert product.description == "Soft cotton"
    assert product.product_type == "Unisex Heavy Cotton Tee"
    assert product.options == {"Product type": "Unisex Heavy Cotton Tee"}
    assert product.image_urls == []
    assert [v.title for v in product.variants] == [
        "Cool Tee / Black / L",
        "Cool Tee / White / M",
    ]
    assert product.variants[0].image_urls == ["https://cdn.example/default.jpg"]
    assert product.variants[0].image_alt_texts == ["Cool Tee / Black / L"]
    assert product.variants[1].image_urls == ["https://cdn.example/default.jpg"]
    assert product.variants[1].image_alt_texts == ["Cool Tee / White / M"]


def test_variant_image_matches_string_variant_ids():
    images = [
        {"src": "https://cdn.example/v.jpg", "variant_ids": ["17887"], "is_default": False},
        {"src": "https://cdn.example/default.jpg", "variant_ids": [], "is_default": True},
    ]
    assert _printify_variant_image(images, "17887") == "https://cdn.example/v.jpg"


@pytest.mark.asyncio
async def test_resolve_blueprint_product_type_caches():
    client = AsyncMock()
    client.get_blueprint = AsyncMock(return_value={"id": 5, "title": "Kids Regular Fit Tee"})
    cache: dict[int, str] = {}
    first = await resolve_printify_blueprint_product_type(client, 5, catalog_cache=cache)
    second = await resolve_printify_blueprint_product_type(client, "5", catalog_cache=cache)
    assert first == "Kids Regular Fit Tee"
    assert second == "Kids Regular Fit Tee"
    client.get_blueprint.assert_awaited_once_with(5)


@pytest.mark.asyncio
async def test_resolve_blueprint_product_type_failure_is_empty():
    from app.addons.suppliers.printify.client import PrintifyAPIError

    client = AsyncMock()
    client.get_blueprint = AsyncMock(side_effect=PrintifyAPIError("nope", status_code=403))
    cache: dict[int, str] = {}
    assert await resolve_printify_blueprint_product_type(client, 9, catalog_cache=cache) is None
    assert cache[9] == ""

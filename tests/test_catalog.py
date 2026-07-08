"""Unit tests for Printify catalog normalization."""

from app.addons.suppliers.printify.catalog import normalize_printify_catalog


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

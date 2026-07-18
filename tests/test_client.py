"""Unit tests for Printify API client helpers."""

from app.addons.suppliers.printify.client import (
    build_line_items,
    map_address_to,
    parse_shipping_rate_options,
    pick_shipping_cents,
    resolve_shipping_method_id,
)


def test_printify_client_helpers():
    address = map_address_to(
        {
            "first_name": "Jane",
            "last_name": "Doe",
            "line1": "1 Main",
            "city": "Portland",
            "state": "OR",
            "zip": "97201",
            "country": "US",
            "email": "jane@example.com",
        }
    )
    assert address["first_name"] == "Jane"
    assert address["region"] == "OR"
    assert address["country"] == "US"

    items = build_line_items(
        [
            {
                "supplier_product_id": "5bfd0b66a342bcc9b5563216",
                "supplier_variant_id": "17887",
                "quantity": 2,
            }
        ]
    )
    assert items == [
        {
            "product_id": "5bfd0b66a342bcc9b5563216",
            "variant_id": 17887,
            "quantity": 2,
        }
    ]


def test_pick_shipping_cents_prefers_standard():
    rates = {"standard": 450, "express": 900, "economy": 350}
    assert pick_shipping_cents(rates) == 450


def test_pick_shipping_cents_cheapest_when_no_standard():
    rates = {"express": 900, "economy": 350, "priority": 700}
    assert pick_shipping_cents(rates) == 350


def test_pick_shipping_cents_ignores_non_positive_and_invalid():
    assert pick_shipping_cents({"standard": 0, "express": "x", "economy": 500}) == 500
    assert pick_shipping_cents({}) is None
    assert pick_shipping_cents([]) is None


def test_parse_shipping_rate_options():
    options = parse_shipping_rate_options(
        {"standard": 450, "express": 900, "economy": 0}
    )
    assert [row["id"] for row in options] == ["standard", "express"]
    assert options[0]["cents"] == 450


def test_resolve_shipping_method_id():
    assert resolve_shipping_method_id(None) == 1
    assert resolve_shipping_method_id("express") == 3
    assert resolve_shipping_method_id("2") == 2
    assert resolve_shipping_method_id("unknown") == 1

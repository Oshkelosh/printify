"""Unit tests for Printify API client helpers."""

from app.addons.suppliers.printify.client import build_line_items, map_address_to


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

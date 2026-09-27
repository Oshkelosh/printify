"""Unit tests for Printify API client helpers."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.addons.suppliers.printify.client import (
    PrintifyAPIError,
    PrintifyClient,
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


def test_headers_include_user_agent():
    client = PrintifyClient("tok")
    headers = client._headers()
    assert headers["Authorization"] == "Bearer tok"
    assert headers["User-Agent"] == "Oshkelosh/printify"


def test_shop_scoped_methods_require_shop_id():
    client = PrintifyClient("tok")
    with pytest.raises(PrintifyAPIError, match="shop_id is not set"):
        client._require_shop_id()


@pytest.mark.asyncio
async def test_list_shops_parses_array_response():
    client = PrintifyClient("tok")
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = [{"id": 5432, "title": "API Store"}]
    resp.text = "[]"

    mock_http = AsyncMock()
    mock_http.__aenter__ = AsyncMock(return_value=mock_http)
    mock_http.__aexit__ = AsyncMock(return_value=None)
    mock_http.request = AsyncMock(return_value=resp)

    with patch("httpx.AsyncClient", return_value=mock_http):
        shops = await client.list_shops()

    assert shops == [{"id": 5432, "title": "API Store"}]
    call_kwargs = mock_http.request.await_args.kwargs
    assert call_kwargs["headers"]["User-Agent"] == "Oshkelosh/printify"


@pytest.mark.asyncio
async def test_publish_posts_all_true_body():
    client = PrintifyClient("tok", shop_id="99")
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {}
    resp.text = "{}"

    mock_http = AsyncMock()
    mock_http.__aenter__ = AsyncMock(return_value=mock_http)
    mock_http.__aexit__ = AsyncMock(return_value=None)
    mock_http.request = AsyncMock(return_value=resp)

    with patch("httpx.AsyncClient", return_value=mock_http):
        await client.publish("prod1")

    method, path = mock_http.request.await_args.args[:2]
    assert method == "POST"
    assert path.endswith("/shops/99/products/prod1/publish.json")
    assert mock_http.request.await_args.kwargs["json"] == {
        "title": True,
        "description": True,
        "images": True,
        "variants": True,
        "tags": True,
        "keyFeatures": True,
        "shipping_template": True,
    }


@pytest.mark.asyncio
async def test_publishing_succeeded_posts_external():
    client = PrintifyClient("tok", shop_id="99")
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {}
    resp.text = "{}"

    mock_http = AsyncMock()
    mock_http.__aenter__ = AsyncMock(return_value=mock_http)
    mock_http.__aexit__ = AsyncMock(return_value=None)
    mock_http.request = AsyncMock(return_value=resp)

    with patch("httpx.AsyncClient", return_value=mock_http):
        await client.publishing_succeeded(
            "prod1",
            external_id="42",
            handle="https://shop.example/products/tee",
        )

    method, path = mock_http.request.await_args.args[:2]
    assert method == "POST"
    assert path.endswith("/shops/99/products/prod1/publishing_succeeded.json")
    assert mock_http.request.await_args.kwargs["json"] == {
        "external": {"id": "42", "handle": "https://shop.example/products/tee"}
    }


@pytest.mark.asyncio
async def test_publishing_failed_and_unpublish():
    client = PrintifyClient("tok", shop_id="99")
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {}
    resp.text = "{}"

    mock_http = AsyncMock()
    mock_http.__aenter__ = AsyncMock(return_value=mock_http)
    mock_http.__aexit__ = AsyncMock(return_value=None)
    mock_http.request = AsyncMock(return_value=resp)

    with patch("httpx.AsyncClient", return_value=mock_http):
        await client.publishing_failed("prod1", reason="missing")
        await client.unpublish("prod1")

    paths = [call.args[1] for call in mock_http.request.await_args_list]
    assert paths[0].endswith("/publishing_failed.json")
    assert paths[1].endswith("/unpublish.json")

"""Unit tests for Printify publish helpers (no DB)."""

from __future__ import annotations

import hmac
from hashlib import sha256
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.addons.suppliers.printify.client import PrintifyAPIError
from app.addons.suppliers.printify.publish import (
    PUBLISH_STARTED_TOPIC,
    acknowledge_product_published,
    acknowledge_touched_products,
    ensure_publish_started_webhook,
    printify_product_id_from_key,
    storefront_product_handle,
    verify_printify_signature,
)


def test_printify_product_id_from_key():
    assert printify_product_id_from_key("printify:abc123") == "abc123"
    assert printify_product_id_from_key("printful:x") is None


def test_storefront_product_handle():
    assert (
        storefront_product_handle(site_url="https://shop.example/", slug="/cool-tee")
        == "https://shop.example/products/cool-tee"
    )


def test_verify_printify_signature():
    secret = "7afa37fd47d7a52ea644382e04962a83c16aef62"
    body = b'{"id":"evt"}'
    digest = hmac.new(secret.encode(), body, sha256).hexdigest()
    assert verify_printify_signature(
        secret=secret,
        body=body,
        header=f"sha256={digest}",
    )
    assert not verify_printify_signature(secret=secret, body=body, header="sha256=bad")
    assert not verify_printify_signature(secret="", body=body, header=f"sha256={digest}")


@pytest.mark.asyncio
async def test_acknowledge_product_published_calls_client():
    client = MagicMock()
    client.publishing_succeeded = AsyncMock(return_value={})
    product = SimpleNamespace(id=7, slug="cool-tee")
    await acknowledge_product_published(
        client,
        printify_product_id="prod1",
        local_product=product,
        site_url="https://shop.example",
    )
    client.publishing_succeeded.assert_awaited_once_with(
        "prod1",
        external_id="7",
        handle="https://shop.example/products/cool-tee",
    )
    client.publish.assert_not_called()


@pytest.mark.asyncio
async def test_acknowledge_touched_products_publishes_then_acks(monkeypatch):
    order: list[str] = []
    client = MagicMock()
    client.publish = AsyncMock(side_effect=lambda *_a, **_k: order.append("publish") or {})
    client.publishing_succeeded = AsyncMock(
        side_effect=lambda *_a, **_k: order.append("ack") or {}
    )
    product = SimpleNamespace(id=7, slug="cool-tee")

    async def _find(_session, _printify_id):
        return product

    monkeypatch.setattr(
        "app.addons.suppliers.printify.publish.find_local_product_by_printify_id",
        _find,
    )

    errors = await acknowledge_touched_products(
        client,
        session=MagicMock(),
        touched_product_keys=["printify:prod1", "printify:prod1"],
        site_url="https://shop.example",
    )

    assert errors == []
    assert order == ["publish", "ack"]
    client.publish.assert_awaited_once_with("prod1")
    client.publishing_succeeded.assert_awaited_once_with(
        "prod1",
        external_id="7",
        handle="https://shop.example/products/cool-tee",
    )


@pytest.mark.asyncio
async def test_acknowledge_touched_products_stops_on_publish_429(monkeypatch):
    client = MagicMock()
    client.publish = AsyncMock(side_effect=PrintifyAPIError("rate", status_code=429))
    client.publishing_succeeded = AsyncMock(return_value={})
    product = SimpleNamespace(id=7, slug="cool-tee")

    async def _find(_session, _printify_id):
        return product

    monkeypatch.setattr(
        "app.addons.suppliers.printify.publish.find_local_product_by_printify_id",
        _find,
    )

    errors = await acknowledge_touched_products(
        client,
        session=MagicMock(),
        touched_product_keys=["printify:prod1", "printify:prod2"],
        site_url="https://shop.example",
    )

    assert errors == ["publish handshake rate-limited for prod1"]
    client.publish.assert_awaited_once_with("prod1")
    client.publishing_succeeded.assert_not_awaited()


@pytest.mark.asyncio
async def test_ensure_publish_started_webhook_creates_when_missing():
    client = MagicMock()
    client.list_webhooks = AsyncMock(return_value=[])
    client.create_webhook = AsyncMock(return_value={"id": "wh1"})
    client.update_webhook = AsyncMock()

    await ensure_publish_started_webhook(
        client,
        webhook_url="https://shop.example/api/v1/suppliers/printify/webhook",
        secret="sec",
    )

    client.create_webhook.assert_awaited_once()
    kwargs = client.create_webhook.await_args.kwargs
    assert kwargs["topic"] == PUBLISH_STARTED_TOPIC
    assert kwargs["secret"] == "sec"
    client.update_webhook.assert_not_awaited()


@pytest.mark.asyncio
async def test_ensure_publish_started_webhook_updates_url():
    client = MagicMock()
    client.list_webhooks = AsyncMock(
        return_value=[
            {
                "id": "wh1",
                "topic": PUBLISH_STARTED_TOPIC,
                "url": "https://old.example/hook",
            }
        ]
    )
    client.create_webhook = AsyncMock()
    client.update_webhook = AsyncMock(return_value={})

    await ensure_publish_started_webhook(
        client,
        webhook_url="https://shop.example/api/v1/suppliers/printify/webhook",
        secret="sec",
    )

    client.update_webhook.assert_awaited_once()
    client.create_webhook.assert_not_awaited()

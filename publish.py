"""Printify sales-channel publish handshake helpers."""

from __future__ import annotations

import hmac
from hashlib import sha256
from typing import Any

from sqlalchemy import select
from sqlmodel import col

from app.addons.log import info, warning
from app.addons.suppliers.printify.client import PrintifyAPIError, PrintifyClient
from app.services.site_settings import resolve_public_site_url
from models.product import Product

PUBLISH_STARTED_TOPIC = "product:publish:started"


def printify_product_id_from_key(external_product_key: str) -> str | None:
    """Extract Printify product id from ``printify:{id}`` catalog keys."""
    key = str(external_product_key or "").strip()
    prefix = "printify:"
    if not key.startswith(prefix):
        return None
    product_id = key[len(prefix) :].strip()
    return product_id or None


def storefront_product_handle(*, site_url: str, slug: str) -> str:
    """Build the public product URL Printify stores as ``external.handle``."""
    base = site_url.rstrip("/")
    clean_slug = str(slug or "").strip().lstrip("/")
    return f"{base}/products/{clean_slug}"


def verify_printify_signature(*, secret: str, body: bytes, header: str) -> bool:
    """Validate ``X-Pfy-Signature: sha256=...`` against the raw request body."""
    if not secret or not header:
        return False
    expected = "sha256=" + hmac.new(secret.encode("utf-8"), body, sha256).hexdigest()
    return hmac.compare_digest(expected, header.strip())


async def find_local_product_by_printify_id(session: Any, printify_product_id: str) -> Product | None:
    key = f"printify:{printify_product_id}"
    result = await session.execute(
        select(Product).where(col(Product.supplier_external_product_key) == key)
    )
    return result.scalar_one_or_none()


async def acknowledge_product_published(
    client: PrintifyClient,
    *,
    printify_product_id: str,
    local_product: Product,
    site_url: str | None = None,
) -> None:
    """Call publishing_succeeded with local product id + storefront handle."""
    base = site_url or resolve_public_site_url()
    slug = str(local_product.slug or "").strip()
    if not slug:
        raise PrintifyAPIError(
            f"Local product {local_product.id} has no slug for Printify publish ACK"
        )
    await client.publishing_succeeded(
        printify_product_id,
        external_id=str(local_product.id),
        handle=storefront_product_handle(site_url=base, slug=slug),
    )


async def acknowledge_touched_products(
    client: PrintifyClient,
    session: Any,
    touched_product_keys: list[str],
    *,
    site_url: str | None = None,
) -> list[str]:
    """Publish then ACK each touched catalog key. Soft-errors; stops remaining keys on 429."""
    errors: list[str] = []
    base = site_url or resolve_public_site_url()
    seen: set[str] = set()
    for key in touched_product_keys:
        printify_id = printify_product_id_from_key(key)
        if not printify_id or printify_id in seen:
            continue
        seen.add(printify_id)
        product = await find_local_product_by_printify_id(session, printify_id)
        if product is None:
            errors.append(f"publish ACK skipped: no local product for {key}")
            continue
        try:
            # ponytail: sequential publish+ACK; publish.json ceiling is 200/30min — stop on 429
            await client.publish(printify_id)
            await acknowledge_product_published(
                client,
                printify_product_id=printify_id,
                local_product=product,
                site_url=base,
            )
        except PrintifyAPIError as exc:
            if exc.status_code == 429:
                warning("Printify", "publish handshake rate-limited for {}", printify_id)
                errors.append(f"publish handshake rate-limited for {printify_id}")
                break
            warning("Printify", "publish handshake failed for {}: {}", printify_id, exc)
            errors.append(f"publish handshake failed for {printify_id}: {exc}")
    return errors


async def ensure_publish_started_webhook(
    client: PrintifyClient,
    *,
    webhook_url: str,
    secret: str,
) -> None:
    """Create or update the shop webhook for ``product:publish:started``."""
    url = webhook_url.strip()
    if not url or not secret:
        return
    existing = await client.list_webhooks()
    for row in existing:
        if str(row.get("topic") or "") != PUBLISH_STARTED_TOPIC:
            continue
        webhook_id = str(row.get("id") or "").strip()
        current_url = str(row.get("url") or "").strip()
        if not webhook_id:
            continue
        if current_url == url:
            info("Printify", "publish webhook already registered id={}", webhook_id)
            return
        await client.update_webhook(webhook_id, url=url, secret=secret)
        info("Printify", "updated publish webhook id={} url={}", webhook_id, url)
        return
    created = await client.create_webhook(
        topic=PUBLISH_STARTED_TOPIC,
        url=url,
        secret=secret,
    )
    info(
        "Printify",
        "created publish webhook id={} url={}",
        created.get("id"),
        url,
    )


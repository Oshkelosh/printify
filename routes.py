"""
Printify addon routes.

API Router (mounted at /api/v1/suppliers/printify/*):
    GET  /api/v1/suppliers/printify/products            - List Printify shop variants
    GET  /api/v1/suppliers/printify/products/{id}     - Single variant detail
    POST /api/v1/suppliers/printify/webhook            - Printify product publish events

Admin Router (mounted at /admin/suppliers/printify/*):
    GET  /admin/suppliers/printify              - Config/status page
    POST /admin/suppliers/printify/save         - Save configuration
    POST /admin/suppliers/printify/sync         - Catalog sync
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import Depends, Request, status
from fastapi.responses import JSONResponse

from app.addons.log import exception, warning
from app.addons.suppliers.printify.client import PrintifyAPIError
from app.addons.suppliers.printify.publish import (
    PUBLISH_STARTED_TOPIC,
    acknowledge_product_published,
    ensure_publish_started_webhook,
    find_local_product_by_printify_id,
    verify_printify_signature,
)
from app.addons.suppliers.shared_routes import build_supplier_routers
from app.config import settings
from app.db.connection import get_session
from app.services.site_settings import resolve_public_site_url
from app.services.webhook_idempotency import claim_webhook_event


def _parse_printify_form(form: Any) -> tuple[dict[str, Any], bool]:
    return {
        "api_key": form.get("api_key", ""),
        "shop_id": form.get("shop_id", ""),
        "is_active": form.get("is_active") == "on",
        "auto_confirm": form.get("auto_confirm") == "on",
        "webhook_secret": form.get("webhook_secret", ""),
    }, form.get("is_active") == "on"


def _webhook_page_context(request: Request) -> dict[str, Any]:
    public_app_url = resolve_public_site_url(request=request)
    return {
        "public_app_url": public_app_url,
        "webhook_url": (
            f"{public_app_url}{settings.api_v1_prefix}/suppliers/printify/webhook"
        ),
    }


async def _ensure_webhook_on_save(
    session: Any,
    request: Request,
    config: dict[str, Any],
    enabled: bool,
) -> None:
    del session
    if not enabled:
        return
    from app.addons.registry import addon_registry

    addon = addon_registry.get("printify")
    if addon is None or not addon.is_enabled:
        return
    secret = str(config.get("webhook_secret") or "").strip()
    if not secret:
        return
    ctx = _webhook_page_context(request)
    webhook_url = str(ctx.get("webhook_url") or "").strip()
    if not webhook_url.startswith("http"):
        return
    client = addon._require_client()
    await ensure_publish_started_webhook(
        client,
        webhook_url=webhook_url,
        secret=secret,
    )


admin_router, api_router, jinja_env = build_supplier_routers(
    "printify",
    template_name="printify_config.html",
    page_title="Printify Settings",
    secret_keys=("api_key", "webhook_secret"),
    parse_config_form=_parse_printify_form,
    extra_page_context=_webhook_page_context,
    on_config_saved=_ensure_webhook_on_save,
)


@api_router.get("/products/{product_id}")
async def get_printify_product(product_id: str):
    from app.addons.registry import addon_registry

    addon = addon_registry.get("printify")
    if addon is None or not addon.is_enabled:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"error": "Printify addon is not enabled"},
        )

    try:
        product = await addon.get_product(product_id)
        return JSONResponse(content={"product": product})
    except Exception as exc:
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"error": str(exc)},
        )


@api_router.post("/webhook")
async def printify_webhook(request: Request, session=Depends(get_session)):
    from app.addons.registry import addon_registry

    body = await request.body()
    signature = request.headers.get("x-pfy-signature", "")

    addon = addon_registry.get("printify")
    if addon is None or not addon.is_enabled:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"error": "Printify addon is not enabled"},
        )

    config = getattr(addon, "_config", None) or {}
    secret = str(config.get("webhook_secret") or "").strip()
    if not verify_printify_signature(secret=secret, body=body, header=signature):
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"error": "Invalid webhook signature"},
        )

    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"error": "Invalid JSON payload"},
        )

    event_type = str(payload.get("type") or "").strip()
    event_id = str(payload.get("id") or "").strip()
    if not event_id:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"error": "Missing webhook event id"},
        )

    if event_type != PUBLISH_STARTED_TOPIC:
        return JSONResponse(content={"handled": False, "ignored": True, "type": event_type})

    claimed = await claim_webhook_event(
        session,
        event_id=event_id,
        provider="printify",
        event_type=event_type,
    )
    if not claimed:
        await session.commit()
        return JSONResponse(content={"handled": True, "duplicate": True})

    resource = payload.get("resource") if isinstance(payload.get("resource"), dict) else {}
    printify_product_id = str(resource.get("id") or "").strip()
    data = resource.get("data") if isinstance(resource.get("data"), dict) else {}
    action = str(data.get("action") or "create").strip().lower() or "create"

    try:
        client = addon._require_client()
        if not printify_product_id:
            await session.commit()
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={"error": "Missing product id"},
            )

        if action == "delete":
            await client.unpublish(printify_product_id)
            await session.commit()
            return JSONResponse(content={"handled": True, "action": "unpublish"})

        local = await find_local_product_by_printify_id(session, printify_product_id)
        if local is None:
            await client.publishing_failed(
                printify_product_id,
                reason="Product not found in Oshkelosh catalog",
            )
            await session.commit()
            return JSONResponse(content={"handled": True, "action": "publishing_failed"})

        await acknowledge_product_published(
            client,
            printify_product_id=printify_product_id,
            local_product=local,
        )
        await session.commit()
        return JSONResponse(content={"handled": True, "action": "publishing_succeeded"})
    except PrintifyAPIError as exc:
        warning("Printify", "webhook publish handshake failed: {}", exc)
        await session.rollback()
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"error": str(exc)},
        )
    except Exception:
        exception("Printify", "webhook processing failed")
        await session.rollback()
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"error": "Webhook processing failed"},
        )

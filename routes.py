"""
Printify addon routes.

API Router (mounted at /api/v1/suppliers/printify/*):
    GET  /api/v1/suppliers/printify/products            - List Printify shop variants
    GET  /api/v1/suppliers/printify/products/{id}     - Single variant detail

Admin Router (mounted at /admin/suppliers/printify/*):
    GET  /admin/suppliers/printify              - Config/status page
    POST /admin/suppliers/printify/save         - Save configuration
    POST /admin/suppliers/printify/sync         - Catalog sync
"""

from __future__ import annotations

from typing import Any

from fastapi import status
from fastapi.responses import JSONResponse

from app.addons.suppliers.shared_routes import build_supplier_routers


def _parse_printify_form(form: Any) -> tuple[dict[str, Any], bool]:
    return {
        "api_key": form.get("api_key", ""),
        "shop_id": form.get("shop_id", ""),
        "is_active": form.get("is_active") == "on",
        "auto_confirm": form.get("auto_confirm") == "on",
    }, form.get("is_active") == "on"


admin_router, api_router, jinja_env = build_supplier_routers(
    "printify",
    template_name="printify_config.html",
    page_title="Printify Settings",
    parse_config_form=_parse_printify_form,
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

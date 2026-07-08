"""Printify catalog normalization for local product import."""

from __future__ import annotations

from typing import Any

from schemas.supplier import (
    POD_INVENTORY_PLACEHOLDER,
    SupplierCatalogItem,
    SupplierCatalogProduct,
    SupplierCatalogVariant,
)


def _printify_product_name(title: str) -> str:
    """Derive product-level title from a variant row title."""
    if " / " in title:
        return title.split(" / ", 1)[0].strip()
    return title.strip() or "Printify product"


def _printify_variant_image(images: list[Any], variant_id: str) -> str | None:
    if not images:
        return None
    try:
        vid = int(variant_id)
    except (TypeError, ValueError):
        vid = None
    for image in images:
        if not isinstance(image, dict):
            continue
        variant_ids = image.get("variant_ids") or []
        if vid is not None and vid in variant_ids:
            src = image.get("src")
            if src:
                return str(src)
    for image in images:
        if isinstance(image, dict) and image.get("is_default") and image.get("src"):
            return str(image["src"])
    first = images[0]
    if isinstance(first, dict) and first.get("src"):
        return str(first["src"])
    return None


def normalize_printify_catalog(raw_items: list[dict[str, Any]]) -> list[SupplierCatalogItem]:
    """Map Printify list_products() rows to catalog import items."""
    items: list[SupplierCatalogItem] = []
    for row in raw_items:
        product_id = str(row.get("product_id") or "").strip()
        variant_id = str(row.get("variant_id") or row.get("id") or "").strip()
        if not product_id or not variant_id:
            continue
        external_key = f"printify:{product_id}:{variant_id}"
        if row.get("visible") is False:
            items.append(
                SupplierCatalogItem(
                    external_key=external_key,
                    name=row.get("title") or "Printify product",
                    description=row.get("description"),
                    price_cents=0,
                    sku=None,
                    image_url=None,
                    supplier_value="printify",
                    supplier_product_id=product_id,
                    supplier_variant_id=variant_id,
                    inventory_quantity=0,
                    skip_reason="Printify product is not visible",
                )
            )
            continue
        if row.get("is_enabled") is False:
            items.append(
                SupplierCatalogItem(
                    external_key=external_key,
                    name=row.get("title") or "Printify product",
                    description=row.get("description"),
                    price_cents=0,
                    sku=None,
                    image_url=None,
                    supplier_value="printify",
                    supplier_product_id=product_id,
                    supplier_variant_id=variant_id,
                    inventory_quantity=0,
                    skip_reason="Printify variant is disabled",
                )
            )
            continue
        price_raw = row.get("price")
        try:
            price_cents = int(price_raw) if price_raw is not None else 0
        except (TypeError, ValueError):
            price_cents = 0
        sku = row.get("sku")
        sku = str(sku).strip() if sku else f"printify-{product_id}-{variant_id}"
        images = row.get("images") if isinstance(row.get("images"), list) else []
        image_url = _printify_variant_image(images, variant_id)
        image_urls = [image_url] if image_url else []
        items.append(
            SupplierCatalogItem(
                external_key=external_key,
                name=str(row.get("title") or "Printify product"),
                description=row.get("description"),
                price_cents=max(price_cents, 0),
                sku=sku,
                image_url=image_url,
                image_urls=image_urls,
                supplier_value="printify",
                supplier_product_id=product_id,
                supplier_variant_id=variant_id,
                inventory_quantity=POD_INVENTORY_PLACEHOLDER,
            )
        )
    return items


def normalize_printify_catalog_products(raw_items: list[dict[str, Any]]) -> list[SupplierCatalogProduct]:
    """Map Printify list_products() rows to grouped catalog products."""
    groups: dict[str, dict[str, Any]] = {}
    for row in raw_items:
        product_id = str(row.get("product_id") or "").strip()
        variant_id = str(row.get("variant_id") or row.get("id") or "").strip()
        if not product_id or not variant_id:
            continue

        title = str(row.get("title") or "Printify product")
        description = row.get("description")
        images = row.get("images") if isinstance(row.get("images"), list) else []
        image_url = _printify_variant_image(images, variant_id)
        image_urls = [image_url] if image_url else []
        external_key = f"printify:{product_id}:{variant_id}"

        if row.get("visible") is False:
            variant = SupplierCatalogVariant(
                external_key=external_key,
                title=title,
                attributes={},
                price_cents=0,
                sku=None,
                inventory_quantity=0,
                supplier_product_id=product_id,
                supplier_variant_id=variant_id,
                image_urls=image_urls,
                skip_reason="Printify product is not visible",
            )
        elif row.get("is_enabled") is False:
            variant = SupplierCatalogVariant(
                external_key=external_key,
                title=title,
                attributes={},
                price_cents=0,
                sku=None,
                inventory_quantity=0,
                supplier_product_id=product_id,
                supplier_variant_id=variant_id,
                image_urls=image_urls,
                skip_reason="Printify variant is disabled",
            )
        else:
            price_raw = row.get("price")
            try:
                price_cents = int(price_raw) if price_raw is not None else 0
            except (TypeError, ValueError):
                price_cents = 0
            sku = row.get("sku")
            sku = str(sku).strip() if sku else f"printify-{product_id}-{variant_id}"
            variant = SupplierCatalogVariant(
                external_key=external_key,
                title=title,
                attributes={},
                price_cents=max(price_cents, 0),
                sku=sku,
                inventory_quantity=POD_INVENTORY_PLACEHOLDER,
                supplier_product_id=product_id,
                supplier_variant_id=variant_id,
                image_urls=image_urls,
            )

        if product_id not in groups:
            groups[product_id] = {
                "name": _printify_product_name(title),
                "description": description,
                "variants": [],
            }
        groups[product_id]["variants"].append(variant)

    products: list[SupplierCatalogProduct] = []
    for product_id, group in groups.items():
        products.append(
            SupplierCatalogProduct(
                external_product_key=f"printify:{product_id}",
                name=group["name"],
                description=group.get("description"),
                product_type=None,
                image_urls=[],
                image_alt_texts=[],
                variants=group["variants"],
                supplier_value="printify",
            )
        )
    return products

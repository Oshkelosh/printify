"""Printify catalog normalization for local product import."""

from __future__ import annotations

import re
from html import unescape
from html.parser import HTMLParser
from typing import Any

from schemas.supplier import (
    POD_INVENTORY_PLACEHOLDER,
    SupplierCatalogItem,
    SupplierCatalogProduct,
    SupplierCatalogVariant,
)

_BLOCK_TAGS = frozenset(
    {
        "br",
        "p",
        "div",
        "li",
        "tr",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "blockquote",
        "section",
        "article",
        "ul",
        "ol",
        "table",
        "hr",
    }
)


class _PlainTextExtractor(HTMLParser):
    """Collect visible text; treat block tags as newlines."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self._parts.append(data)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in _BLOCK_TAGS:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        t = tag.lower()
        if t != "br" and t in _BLOCK_TAGS:
            self._parts.append("\n")

    def plain(self) -> str:
        text = "".join(self._parts)
        text = re.sub(r"[ \t\r\f\v]+", " ", text)
        text = re.sub(r" *\n *", "\n", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()


def printify_plain_description(value: Any) -> str | None:
    """Printify shop descriptions are often HTML; store plain text locally."""
    if value is None:
        return None
    raw = str(value)
    if not raw.strip():
        return None
    if "<" not in raw:
        cleaned = unescape(raw).strip()
        return cleaned or None
    parser = _PlainTextExtractor()
    try:
        parser.feed(raw)
        parser.close()
        cleaned = parser.plain()
    except Exception:
        # ponytail: malformed HTML → naive strip; revisit if Printify markup breaks often
        cleaned = unescape(re.sub(r"<[^>]+>", " ", raw))
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned or None


def _printify_product_name(title: str) -> str:
    """Derive product-level title from a variant row title (fallback only)."""
    if " / " in title:
        return title.split(" / ", 1)[0].strip()
    return title.strip() or "Printify product"


def printify_variant_display_name(*, product_title: str, variant_title: str) -> str:
    """Build Printful-style variant title: ``{product} / {variant options}``."""
    product = (product_title or "").strip()
    variant = (variant_title or "").strip() or "Printify product"
    if not product:
        return variant
    if product.lower() in variant.lower():
        return variant
    if variant.lower() in product.lower():
        return product
    return f"{product} / {variant}"


_KNOWN_OPTION_LABELS = {"color": "Color", "size": "Size"}
# Printful attribute insertion order: Size then Color
_KNOWN_OPTION_ORDER = ("size", "color")


def build_printify_option_value_index(
    product_options: Any,
) -> dict[str, tuple[str, str]]:
    """Map shop option value id → (axis_key, value_title).

    Shop products define axes on the product (``options`` array) and reference
    them from each variant as an ID list. Axis key prefers ``type`` (size/color)
    and falls back to ``name``.
    """
    index: dict[str, tuple[str, str]] = {}
    if not isinstance(product_options, list):
        return index
    for axis in product_options:
        if not isinstance(axis, dict):
            continue
        axis_type = str(axis.get("type") or "").strip()
        axis_name = str(axis.get("name") or "").strip()
        axis_key = (axis_type or axis_name).lower()
        if not axis_key:
            continue
        values = axis.get("values")
        if not isinstance(values, list):
            continue
        for value in values:
            if not isinstance(value, dict):
                continue
            value_id = value.get("id")
            if value_id is None:
                continue
            title = value.get("title")
            if not isinstance(title, str) or not title.strip():
                continue
            index[str(value_id)] = (axis_key, title.strip())
    return index


def resolve_printify_variant_options(
    variant_option_ids: Any,
    index: dict[str, tuple[str, str]],
) -> dict[str, str]:
    """Resolve shop variant option ID list to ``{axis_key: value_title}``."""
    if not isinstance(variant_option_ids, list) or not index:
        return {}
    resolved: dict[str, str] = {}
    for entry in variant_option_ids:
        if entry is None:
            continue
        hit = index.get(str(entry))
        if hit is None:
            continue
        axis_key, title = hit
        resolved[axis_key] = title
    return resolved


def printify_variant_attributes_from_row(row: dict[str, Any]) -> dict[str, str]:
    """Picker attributes from resolved Printify options (Size/Color parity with Printful)."""
    options = row.get("options")
    if not isinstance(options, dict):
        return {}
    normalized: dict[str, str] = {}
    for raw_key, raw_value in options.items():
        if not isinstance(raw_value, str) or not raw_value.strip():
            continue
        key = str(raw_key).strip()
        if not key:
            continue
        normalized[key.lower()] = raw_value.strip()
    attrs: dict[str, str] = {}
    for known in _KNOWN_OPTION_ORDER:
        value = normalized.pop(known, None)
        if value is not None:
            attrs[_KNOWN_OPTION_LABELS[known]] = value
    for key, value in normalized.items():
        attrs[key.replace("_", " ").title()] = value
    return attrs


def _variant_id_matches(variant_ids: list[Any], variant_id: str) -> bool:
    """True when variant_id is in Printify image.variant_ids (int or str)."""
    if not variant_id:
        return False
    try:
        vid_int = int(variant_id)
    except (TypeError, ValueError):
        vid_int = None
    for entry in variant_ids:
        if entry is None:
            continue
        if str(entry) == variant_id:
            return True
        if vid_int is not None:
            try:
                if int(entry) == vid_int:
                    return True
            except (TypeError, ValueError):
                continue
    return False


def _printify_variant_image(images: list[Any], variant_id: str) -> str | None:
    if not images:
        return None
    for image in images:
        if not isinstance(image, dict):
            continue
        variant_ids = image.get("variant_ids") or []
        if isinstance(variant_ids, list) and _variant_id_matches(variant_ids, variant_id):
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


async def resolve_printify_blueprint_product_type(
    client: Any,
    blueprint_id: Any,
    *,
    catalog_cache: dict[int, str],
) -> str | None:
    """Resolve catalog blueprint title for category / Product type (Printful parity)."""
    if blueprint_id is None or blueprint_id == "":
        return None
    try:
        bp_id = int(blueprint_id)
    except (TypeError, ValueError):
        return None
    if bp_id in catalog_cache:
        cached = catalog_cache[bp_id]
        return cached or None
    try:
        data = await client.get_blueprint(bp_id)
    except Exception:
        catalog_cache[bp_id] = ""
        return None
    if not isinstance(data, dict):
        catalog_cache[bp_id] = ""
        return None
    title = data.get("title")
    if isinstance(title, str) and title.strip():
        resolved = title.strip()
        catalog_cache[bp_id] = resolved
        return resolved
    catalog_cache[bp_id] = ""
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
                    description=printify_plain_description(row.get("description")),
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
                    description=printify_plain_description(row.get("description")),
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
        product_type = row.get("product_type")
        product_type = str(product_type).strip() if product_type else None
        product_title = str(row.get("product_title") or "").strip()
        display_name = printify_variant_display_name(
            product_title=product_title,
            variant_title=str(row.get("title") or "Printify product"),
        )
        items.append(
            SupplierCatalogItem(
                external_key=external_key,
                name=display_name,
                description=printify_plain_description(row.get("description")),
                price_cents=max(price_cents, 0),
                sku=sku,
                image_url=image_url,
                image_urls=image_urls,
                supplier_value="printify",
                supplier_product_id=product_id,
                supplier_variant_id=variant_id,
                inventory_quantity=POD_INVENTORY_PLACEHOLDER,
                product_type=product_type,
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

        product_title = str(row.get("product_title") or "").strip()
        variant_part = str(row.get("title") or "Printify product")
        title = printify_variant_display_name(
            product_title=product_title,
            variant_title=variant_part,
        )
        description = printify_plain_description(row.get("description"))
        images = row.get("images") if isinstance(row.get("images"), list) else []
        image_url = _printify_variant_image(images, variant_id)
        image_urls = [image_url] if image_url else []
        external_key = f"printify:{product_id}:{variant_id}"
        attributes = printify_variant_attributes_from_row(row)

        if row.get("visible") is False:
            variant = SupplierCatalogVariant(
                external_key=external_key,
                title=title,
                attributes=attributes,
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
                attributes=attributes,
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
                attributes=attributes,
                price_cents=max(price_cents, 0),
                sku=sku,
                inventory_quantity=POD_INVENTORY_PLACEHOLDER,
                supplier_product_id=product_id,
                supplier_variant_id=variant_id,
                image_urls=image_urls,
            )

        if product_id not in groups:
            product_type = row.get("product_type")
            product_type = str(product_type).strip() if product_type else None
            groups[product_id] = {
                "name": product_title or _printify_product_name(variant_part),
                "description": description,
                "product_type": product_type,
                "variants": [],
            }
        groups[product_id]["variants"].append(variant)

    products: list[SupplierCatalogProduct] = []
    for product_id, group in groups.items():
        product_type = group.get("product_type")
        options: dict[str, str] = {}
        if product_type:
            options["Product type"] = product_type
        products.append(
            SupplierCatalogProduct(
                external_product_key=f"printify:{product_id}",
                name=group["name"],
                description=group.get("description"),
                product_type=product_type,
                image_urls=[],
                image_alt_texts=[],
                variants=group["variants"],
                supplier_value="printify",
                options=options,
            )
        )
    return products

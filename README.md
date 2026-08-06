# Printify (`printify`)

Print-on-demand supplier via Printify.

## Overview

| | |
|---|---|
| Addon ID | `printify` |
| Category | supplier |
| Version | 1.0.0 |
| Category guide | [../README.md](../README.md) |
| Fulfillment key | `printify` |

Multiple suppliers can be enabled at the same time. Fulfillment runs when an order becomes **paid**.

## Enable and configure

1. Install this package under `app/addons/suppliers/printify/`
2. In Printify: create a Personal Access Token (My Profile → Connections) and connect an **API** store (My Stores → Add store → API)
3. Open **Admin → Suppliers → Printify** at `/admin/suppliers/printify`
4. Paste the token, enable the addon, and save — shop ID is auto-discovered from `GET /v1/shops.json`

Tokens are long JWT-style strings; that is normal. Required scopes: `shops.read`, `products.read`, `orders.read`, `orders.write`, and `catalog.read` (blueprint title → category on sync).

## Configuration schema

| Field | Type | Description |
|-------|------|-------------|
| `api_key` | secret | Printify Personal Access Token |
| `shop_id` | string | Auto-filled on save when the token has exactly one shop; optional override for multi-shop tokens |
| `is_active` | bool | Whether the addon is active |
| `auto_confirm` | bool | Send order to production after create |

## Routes

### Public API

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/suppliers/printify/products` | List catalog products |
| GET | `/api/v1/suppliers/printify/products/{id}` | Single product detail |

### Admin

| Method | Path | Description |
|--------|------|-------------|
| GET | `/admin/suppliers/printify` | Config form |
| POST | `/admin/suppliers/printify/save` | Save config |
| POST | `/admin/suppliers/printify/sync` | Trigger catalog sync |

## Core integration

- **Variant supplier fields:** paid-order fulfillment reads Printify IDs from each **ProductVariant** row
- **Fulfillment:** creates Printify order; optional send-to-production when `auto_confirm` is true
- **Checkout shipping:** core calls `quote_shipping()` → `POST orders/shipping.json` for Printify line items (prefers standard, else cheapest). Unquoted or failed quotes fall back to Site Settings like any other supplier.
- **Grouping:** line items grouped by fulfillment key `printify`

## Variant supplier fields

| Field | Description |
|-------|-------------|
| `supplier_addon_id` | `printify` |
| `supplier_product_id` | Printify shop product id |
| `supplier_variant_id` | Printify variant id |

Both IDs come from your Printify shop catalog. Catalog sync sets them on each imported variant.

## Catalog sync

Supported. Admin sync at `/admin/suppliers/printify` or `POST /admin/suppliers/printify/sync`.

**Import model:** one Oshkelosh **Product** per Printify shop product; one **ProductVariant** per enabled variant.

| Key | Format |
|-----|--------|
| Product parent key | `printify:{productId}` |
| Variant dedup key | `printify:{productId}:{variantId}` |

**Parent vs variant fields:**

- Product **name** / **description** come from the shop product (`title` / `description`), not from a variant title. Printify descriptions are often HTML — import strips tags to plain text.
- Variant **title** is Printful-style: `{shop product title} / {Printify variant.title}` (e.g. `Cool Tee / Black / L`).
- Variant **attributes** (storefront Size/Color pickers) come from shop product option definitions: product `options` axes + each variant’s `options` **ID list** are resolved to `color`/`size` (etc.), then mapped to `Color`/`Size`. Catalog-style `{color, size}` dicts are also accepted. Empty attributes force a flat title list in VariantPicker — re-sync refreshes attributes on existing variants.
- **Product type** is the catalog blueprint title (`GET /catalog/blueprints/{blueprint_id}.json`), stored as `products.options["Product type"]` and used by core `assign_product_category_from_type` on first import (creates/links a Category). Category assignment runs on create only — re-sync updates names/descriptions/attributes but not category on existing rows.

**Images:** Sync downloads Printify mockups onto **variants** only (`SupplierCatalogProduct.image_urls` stays empty, same as Printful). Core stores local media as root-relative `/media/files/...` URLs so admin works on any browse host; set `PUBLIC_APP_URL` for absolute SEO/email links. Re-sync does not re-download images for existing variants.

**Prerequisites:**

- Products must exist in the auto-discovered (or override) shop.
- Hidden products and disabled variants are skipped.
- PAT needs `catalog.read` for blueprint → category mapping.
- Nested-git **Admin → Update** overwrites this package — commit fixes into the Printify addon repo before updating.

## Provider setup

1. Generate a Personal Access Token with the scopes above (token is shown once).
2. My Stores → Add store → **API** → Connect (required; otherwise shop list is empty).
3. Paste the token in Admin → Suppliers → Printify and save. Shop ID is resolved automatically when the token has one shop. If you have multiple shops, set the multi-shop override field to the integer shop `id` from the error message.

## Package layout

```
printify/
├── README.md
├── AGENTS.md
├── addon.py
├── catalog.py
├── client.py
├── routes.py
└── templates/
```

## See also

- [AGENTS.md](AGENTS.md) — package invariants
- [Supplier addon development](../README.md)
- [Oshkelosh addon guide](../../README.md)

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
2. Open **Admin → Suppliers → Printify** at `/admin/suppliers/printify`
3. Enter API credentials and enable the addon

## Configuration schema

| Field | Type | Description |
|-------|------|-------------|
| `api_key` | secret | Printify Personal Access Token |
| `shop_id` | string | Printify shop ID |
| `is_active` | bool | Whether the addon is active |
| `auto_confirm` | bool | Send order to production after create |

## Routes

### Public API

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/suppliers/printify/products` | List catalog products |

### Admin

| Method | Path | Description |
|--------|------|-------------|
| GET | `/admin/suppliers/printify` | Config form |
| POST | `/admin/suppliers/printify/save` | Save config |
| POST | `/admin/suppliers/printify/sync` | Trigger catalog sync |

## Core integration

- **Variant supplier fields:** paid-order fulfillment reads Printify IDs from each **ProductVariant** row
- **Fulfillment:** creates Printify order; optional send-to-production when `auto_confirm` is true
- **Grouping:** line items grouped by fulfillment key `printify`

## Variant supplier fields

| Field | Description |
|-------|-------------|
| `supplier_addon_id` | `printify` |
| `supplier_product_id` | Printify shop product id |
| `supplier_variant_id` | Printify variant id |

Both IDs come from your Printify shop catalog. Catalog sync sets them on each imported variant.

## Catalog sync

Supported. Admin sync at `/admin/suppliers/printify` or `POST /api/v1/admin/suppliers/printify/sync`.

**Import model:** one Oshkelosh **Product** per Printify product; one **ProductVariant** per enabled variant.

| Key | Format |
|-----|--------|
| Product parent key | `printify:{productId}` |
| Variant dedup key | `printify:{productId}:{variantId}` |

**Prerequisites:**

- Products must exist in the configured **shop ID**.
- Hidden products and disabled variants are skipped.

## Provider setup

- Generate a Personal Access Token and note your shop ID from Printify.

## Package layout

```
printify/
├── README.md
├── addon.py
├── catalog.py
├── client.py
├── routes.py
└── templates/
```

## See also

- [Supplier addon development](../README.md)
- [Oshkelosh addon guide](../../README.md)

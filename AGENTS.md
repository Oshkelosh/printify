# Printify (`printify`) — AGENTS

## Role

Print-on-demand supplier via Printify. Addon ID: `printify`. Fulfillment key: `printify`.

## File map

- `README.md`
- `AGENTS.md`
- `__init__.py`
- `addon.py`
- `catalog.py`
- `client.py`
- `oshkelosh-addon.json`
- `routes.py`
- `templates/`
- `tests/`

## Package specifics

**Category ceiling:** Many suppliers may be active; fulfillment runs on order `paid`; supplier IDs on variants; sync keys in package README.
**Config fields:** `api_key` (secret), `shop_id` (optional multi-shop override), `is_active` (bool), `auto_confirm` (bool)

## Invariants

- Implement the matching category ABC; do not patch host `app/services/*.py` with provider branches
- Credentials and enable flags live in `addon_configs` (admin UI), not host `.env`
- Discover shop ID via `GET /shops.json` when not overridden; do not require humans to invent dashboard IDs
- Catalog: parent name/description from shop product; strip HTML from descriptions
- Catalog: resolve shop `variant.options` ID arrays against product `options` axes → `SupplierCatalogVariant.attributes` (`color`/`size` → `Color`/`Size`); titles alone are not picker axes
- Catalog: images on variants only; `product_type` from blueprint title → `options["Product type"]` (category on create only)
- Use `app/addons/log.py` for structured logging
- Admin mutating forms need CSRF; use `render_addon_admin_page` correctly
- Nested `.git`: Admin **Update** overwrites this tree — ship fixes in the Printify addon repo

## Prefer / Avoid

- Prefer: extend this package and the category ABC; keep provider API clients here
- Avoid: editing host `app/services/` for this provider; putting secrets in host `.env`; leaving variant attributes empty when Printify exposes options

## See also

- [README.md](README.md) — package how-to
- [../README.md](../README.md) — category guide
- [../AGENTS.md](../AGENTS.md) — category invariants
- [../../AGENTS.md](../../AGENTS.md) — host addon boundary
- [../../README.md](../../README.md) — plugin development
- [../../../../AGENTS.md](../../../../AGENTS.md), [../../../../DESIGN.md](../../../../DESIGN.md)

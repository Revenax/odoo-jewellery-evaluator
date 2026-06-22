# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

This repo holds two Odoo 19 Community modules:

- **`jewellery_evaluator`** (the main one): adds gold/silver/diamond pricing to `product.template`, auto-updates prices from live sources via cron, and enforces minimum sale prices in the POS. It is packaged using a trick — **the repo root itself is this module** (see Packaging below).
- **`jewellery_inventory_management`** ([jewellery_inventory_management/](jewellery_inventory_management/)): a thin module that `depends` on `jewellery_evaluator` and reuses its security groups. Minimal so far — one model, `jewellery.inventory.count` (a stock-count entry linked to a `product.template`), plus a list/form view and menu. Unlike `jewellery_evaluator` it uses a **standard Odoo layout** (its own `__manifest__.py` + `__init__.py` at the module dir).

The git repo is named with hyphens (`odoo-gold-pricing-engine` / `odoo-jewellery-evaluator`), but **Odoo rejects hyphenated addon names** — see Packaging below.

## Commands

```bash
make install-dev        # pip install -r requirements-dev.txt (ruff, pytest, mypy, selenium)
make check              # lint + test + type-check (same as ./scripts/ci.sh, run in CI)
make lint               # ruff check jewellery_evaluator/ jewellery_inventory_management/ tests/
make test               # pytest tests/ -v
make type-check         # mypy on jewellery_evaluator/utils.py ONLY
pytest tests/test_price_computation.py::test_compute_21k_price   # single test
```

Notes:
- `make check` / `./scripts/ci.sh` is the gate. The pre-push git hook (`./scripts/install-git-hooks.sh`) runs it; CI re-runs it on every push/PR to `main`.
- mypy intentionally type-checks **only `utils.py`**, not the ORM models. Keep type-checkable logic there.
- ruff config (`pyproject.toml`) ignores `N999` (hyphenated dir), `F401` (Odoo `__init__` imports), and `UP009` (keeps the required UTF-8 header) — all deliberate for Odoo. Every file carries a `# -*- coding: utf-8 -*-` + copyright header (see CONTRIBUTING.md).

## Architecture

### Two layers: pure functions vs ORM models

All pricing **math** lives in [jewellery_evaluator/utils.py](jewellery_evaluator/utils.py) as pure functions (no Odoo imports beyond `env` for config reads). This is the only file that is unit-tested (`tests/`) and mypy-checked. The Odoo models in `jewellery_evaluator/models/` are thin: they read fields, call utils functions, and `write()` results. **When adding pricing logic, put the calculation in `utils.py` with a test, and call it from the model** — don't bury arithmetic in model methods.

`tests/` (pytest, runs in CI, no Odoo) load `utils.py` directly via `conftest.py` — they never import Odoo. A separate suite under `jewellery_evaluator/tests/` (`test_cron.py`, `test_require_customer.py`) uses Odoo's own test framework and only runs inside a running Odoo instance (`odoo -u jewellery_evaluator --test-enable`), **not** under pytest.

### `product.template` is the hub

[models/product_template.py](jewellery_evaluator/models/product_template.py) (the largest file) extends `product.template` with all jewellery fields. The `jewellery_type` selection drives everything — five categories:

| `jewellery_type` | priced by | base price source |
|---|---|---|
| `gold_local`, `gold_foreign`, `gold_bars` | `compute_gold_product_price` | 21K gold from API |
| `diamond_jewellery` | `compute_diamond_jewellery_price` | 21K gold (EGP) + stone tiers, USD→EGP |
| `silver` | `compute_silver_product_price` | silver 999 from Selenium scrape |

Legacy internal field `gold_type` (`jewellery_local`/`jewellery_foreign`/`bars`) is mapped from `jewellery_type` via `JEWELLERY_TYPE_TO_GOLD_TYPE` for the markup-config lookup. The `_register_hook` migrates deprecated `ingots`/`coins` gold_type values to `bars`.

### Pricing flows two ways

1. **Live recompute** on form edits: `@api.depends`-driven `_compute_*_prices` methods recompute when weight/purity/type change.
2. **Cron batch update** every 10 min: [data/jewellery_evaluator_cron.xml](jewellery_evaluator/data/jewellery_evaluator_cron.xml) defines two crons calling price-service models, which fetch the base price once and call `product.template.update_gold_prices` / `update_silver_prices` / `update_diamond_jewellery_prices` in batches of 100. **The gold cron also refreshes diamond products** (they share the 21K base); silver has its own cron.

### Price services (one model each, in `models/`)

- **`gold.price.service`** ([gold_price_service.py](jewellery_evaluator/models/gold_price_service.py)): GET the configured `gold_api_endpoint`, treat the 200 response as HTML/text, extract the 21K/gram price with the configured `gold_21k_regex_formula` (`parse_gold_price_with_regex`). On success it writes the price back to `fallback_price`; on failure it reads `fallback_price`.
- **`silver.price.service`** ([silver_price_service.py](jewellery_evaluator/models/silver_price_service.py)): headless-Chrome Selenium scrape of dahabmasr.com by XPath (no regex/API). Contains substantial chromedriver-version-matching logic to avoid SIGTRAP from mismatched drivers. `set_silver_price_999` lets an external script push a price in. Debug standalone with `scripts/test-silver-scrape.sh`.
- Diamond pricing has no fetch service — it reuses the gold 21K base, applies per-carat **stone tiers** (`get_stone_tier_price`, 5 tiers) and a USD→EGP rate.

### Pricing conventions (in `utils.py`)

- **`Decimal` arithmetic throughout** with `ROUND_HALF_UP`; final sale/min-sale prices are **rounded to the nearest 50** (EGP).
- **Purity factors are relative to 21K** (what the gold API returns): 24K = 8/7, 21K = 1, 18K = 7/8. (`product_template.py` exposes a 24K/21K/18K selection; older docs mentioning 14K/10K are stale.)
- **Bar markup is weight-tiered**: 11 tiers (1g…1000g+) resolved by closest neighbor (`get_markup_per_gram` → `_get_markup_bars_by_weight`); ≥1000g uses the 1000g tier; jewellery types use a single flat per-gram markup. Defaults live in `BAR_TIER_DEFAULT_MARKUP`.
- `min_sale_price = cost + markup_total × 0.7` for gold/silver; the POS uses this as the floor.

### Configuration = `ir.config_parameter`

All tunables (API endpoint, regex, fallback price, per-gram and per-tier markups, diamond stone-tier USD prices, exchange rate, silver markup) are stored as `jewellery_evaluator.*` system parameters, edited via the Settings view ([jewellery_evaluator_config.py](jewellery_evaluator/models/jewellery_evaluator_config.py)) or `ir.config_parameter`. There is no hardcoded API config in code.

### POS enforcement (two layers)

- Backend ([models/pos_order.py](jewellery_evaluator/models/pos_order.py)): validates order lines on create — blocks prices below `gold_min_sale_price` and discounts above the allowed share of markup. Cannot be bypassed.
- Frontend ([static/src/js/pos_discount_override.js](jewellery_evaluator/static/src/js/pos_discount_override.js)): patches the POS UI to clamp price/discount and show errors. Loaded via the `point_of_sale._assets_pos` bundle in `__manifest__.py`.

## Packaging & deployment

**Packaging trick (important):** the **repo root is the Odoo module** — root `__init__.py` + `__manifest__.py`, with the actual Python package and all `data`/`views`/`security`/`report` files under the `jewellery_evaluator/` subdirectory (hence manifest paths like `jewellery_evaluator/security/...`). Root `__init__.py` only imports the subpackage when loaded by Odoo (`if __package__`), so pytest/mypy can import `utils.py` even though the repo dir name has hyphens. The addons path must point at the **parent** of a directory named exactly `jewellery_evaluator` (no hyphens).

**Second module is a normal subdir — but the repo root is itself an addon, so the subdir is *nested*, not a sibling Odoo can see.** `jewellery_inventory_management/` lives inside `jewellery_evaluator` (the repo root), so it is NOT a top-level addon on the runtime addons path and won't appear in "Update Apps List" on its own. [scripts/remote-deploy.sh](scripts/remote-deploy.sh) fixes this for each name in its `SUBMODULES` list (default: `jewellery_inventory_management`) by creating a **persistent sibling symlink** in the repo's parent dir (the runtime addons path, e.g. `/opt/odoo/custom-addons/jewellery_inventory_management → …/jewellery_evaluator/jewellery_inventory_management`), plus an ephemeral staging symlink for the upgrade run. **Add any future repo-subdir module to that `SUBMODULES` list.** First install is still manual (Apps → Install); if a module ever fails to show up, check that sibling symlink exists on the addons path.

**Deploy** is push-to-`main` → GitHub Actions ([.github/workflows/deploy.yml](.github/workflows/deploy.yml)) runs `ci.sh`, then SSHes to EC2 and runs [scripts/remote-deploy.sh](scripts/remote-deploy.sh): it `git pull --ff-only`, stops Odoo, **symlinks the repo root to a temp `jewellery_evaluator` addon dir** (plus each `SUBMODULES` entry), runs `odoo -u jewellery_evaluator,jewellery_inventory_management --stop-after-init`, and restarts Odoo. First-time module install is manual (Apps → Install); deploy only upgrades (and `-u` on an installed-elsewhere/not-yet-installed module is a harmless no-op).

**Report XML is DB-cached:** editing `report/report_invoice_gold.xml` (custom gold invoice layout) requires a **module upgrade** (`-u jewellery_evaluator`) to take effect — a plain server restart will not reload it.

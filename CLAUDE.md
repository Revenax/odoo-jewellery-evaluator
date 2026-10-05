# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

This repo holds three Odoo 19 modules (prod runs Enterprise):

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

- **`gold.price.service`** ([gold_price_service.py](jewellery_evaluator/models/gold_price_service.py)): GET the configured `gold_api_endpoint`, treat the 200 response as HTML/text, extract the 21K/gram price with the configured `gold_21k_regex_formula` (`parse_gold_price_with_regex`). On success it writes the price back to `fallback_price`; on failure it reads `fallback_price`. A **plausibility guard** rejects a fetched price that jumps > `jewellery_evaluator.gold_price_max_jump_pct` (default 0.35) off the last known-good value — keeps the old price and fails the cron loudly — so a source-site/regex drift can't silently mass-misprice the catalog + the POS floor. The missing/invalid-cache fallback returns **0** (NOT the old plausible-but-wrong 75 EGP/g); `compute_gold_product_price` rejects base ≤ 0 (→ ValueError, caught → 0 prices), so a never-configured branch shows obviously-broken 0 prices instead of pricing gold at ~1.5% of value.
- **`silver.price.service`** ([silver_price_service.py](jewellery_evaluator/models/silver_price_service.py)): headless-Chrome Selenium scrape of dahabmasr.com by XPath (no regex/API). Contains substantial chromedriver-version-matching logic to avoid SIGTRAP from mismatched drivers. `set_silver_price_999` lets an external script push a price in. Debug standalone with `scripts/test-silver-scrape.sh`. **Chrome temp-dir cleanup (do NOT regress):** `_create_driver` returns `(driver, profile_dir)`; the caller **deletes the temp `chrome-silver-*` profile dir after `quit()`** (Chrome doesn't) and `_reap_stale_chrome_profiles` removes stragglers > 1 h each run. The leak (one dir per 10-min cron, never cleaned) once filled `/tmp` with 16 GB → disk 100 % → Postgres PANIC (`No space left on device`) → Odoo crash-loop/502. If Odoo is down, check `df -h /` and `/tmp/chrome-silver-*` before anything else.
- Diamond pricing has no fetch service — it reuses the gold 21K base, applies per-carat **stone tiers** (`get_stone_tier_price`, 5 tiers) and a USD→EGP rate.

### Pricing conventions (in `utils.py`)

- **`Decimal` arithmetic throughout** with `ROUND_HALF_UP`; final sale/min-sale prices are **rounded to the nearest 50** (EGP).
- **Purity factors are relative to 21K** (what the gold API returns): 24K = 8/7, 21K = 1, 18K = 7/8. (`product_template.py` exposes a 24K/21K/18K selection; older docs mentioning 14K/10K are stale.)
- **Bar markup is weight-tiered**: 11 tiers (1g…1000g+) resolved by closest neighbor (`get_markup_per_gram` → `_get_markup_bars_by_weight`); ≥1000g uses the 1000g tier; jewellery types use a single flat per-gram markup. Defaults live in `BAR_TIER_DEFAULT_MARKUP`.
- `min_sale_price` (the POS floor) for gold/silver = `cost + (minimum_making_fee_per_gram × weight)`, where the minimum making fee is a configurable per-gram setting (`markup_jewellery_local_min` / `markup_jewellery_foreign_min` / `silver_markup_per_gram_min`) shown next to each making fee. When the minimum making fee is **0 (the default/"auto")** it falls back to the legacy `cost + markup_total × 0.7`. The POS enforces *only* this floor — the old "50% of markup" discount cap was removed so the minimum making fee is the single source of truth.
- **Diamond floor** = a configurable *share of the sale price* (diamonds have no per-gram making-fee floor): `diamond_min_sale_price = round(diamond_sale_price_egp × jewellery_evaluator.diamond_min_sale_pct)`, default **0.9** (≤ 10 % discount), computed in `compute_diamond_jewellery_price` (utils) and stored on `product.template`. `diamond_min_sale_pct = 0` yields a 0 field but the POS then applies its **80 %-of-entered-price fallback** (same as gold/silver) — so 0 is NOT a full disable; use a tiny value (e.g. 0.01) for near-unlimited discounting.

### Configuration = `ir.config_parameter`

All tunables (API endpoint, regex, fallback price, per-gram and per-tier markups, diamond stone-tier USD prices, exchange rate, silver markup) are stored as `jewellery_evaluator.*` system parameters, edited via the Settings view ([jewellery_evaluator_config.py](jewellery_evaluator/models/jewellery_evaluator_config.py)) or `ir.config_parameter`. There is no hardcoded API config in code.

### POS enforcement (two layers)

- Backend ([models/pos_order.py](jewellery_evaluator/models/pos_order.py)): validates order lines on create — blocks any line below its floor (`gold_min_sale_price` / `silver_min_sale_price` / `diamond_min_sale_price`; when the field is 0 it falls back to `price_unit × 0.8`). Cannot be bypassed except by an authorised **manager override** (a below-min line needs a manager PIN/badge via `pos_hr`, or a master-PIN fallback — sha1-hashed, never plaintext; `_override_is_authorised`). **Refund/return lines (`qty < 0`) are exempt** — the floor is for sales only. Enforced twice: `_order_fields` on create and the persisted-line `_check_gold_minimum_price` constraint.
- Frontend ([static/src/js/pos_discount_override.js](jewellery_evaluator/static/src/js/pos_discount_override.js)): patches the POS UI (`jewelleryFloor` per material) to highlight below-min lines and gate the Pay button behind the manager override. Loaded via the `point_of_sale._assets_pos` bundle in `__manifest__.py`.

### Vault sync (the POS shift count == the whole physical cash drawer)

Each branch has **one cash journal = its physical "Vault"** (Sway Mall's is renamed **"Vault - Sway Mall"**, journal id 11, GL acct 105001). Goal: at shift end the cashier counts the Vault and it reconciles — every cash event posts **once** to the Vault and the POS folds them all in. Stock Odoo only counts the POS's *own* cash sales; everything else (customer invoices paid cash, buy-backs, transfers) drifted.

- **The override** ([models/pos_session.py](jewellery_evaluator/models/pos_session.py)) extends `pos.session`. `_vault_foreign_move_lines()` finds posted move lines on the Vault GL account in the shift window `[start_at, stop_at or now]` (by move **create_date**) that are **not POS-owned**. The exclusion is `'|', ('statement_line_id','=',False), ('statement_line_id.pos_session_id','=',False)` — every POS cash entry (cash-in/out + the session-close cash lines) is a bank-statement line tied to a POS session, so this keeps only foreign payments/JEs and counts each **exactly once** in open (POS sales still only in `pos.payment`) and closed (POS sales on the journal but via excluded statement lines) states. **Must override BOTH** `_compute_cash_balance` (backend `cash_register_balance_end`/`cash_register_difference` — else the close posts the foreign cash as a false profit/loss) and `get_closing_control_data` (the cashier's Expected + the `moves` breakdown). The OR matters: `statement_line_id.pos_session_id = False` alone silently drops NULL-`statement_line_id` rows (Odoo joins through the m2o) — exactly the payment lines. Additive: a shift with no foreign movements is an exact no-op.
- **Direct-posting config is REQUIRED (runtime, per Vault journal):** Odoo 19 routes payments through **Outstanding Receipts/Payments** by default, so cash never reaches the Vault GL acct until statement reconciliation and the override sees nothing. Set the Vault journal's inbound **and** outbound `payment_method_line_id.payment_account_id = the cash account itself` so cash posts straight to the drawer (payment state `paid`, no `in_process`). This is also correct accounting for cash (no clearing delay). Done for Sway Mall; **redo it for every new branch Vault** (any cash payments created *before* this is set stay stuck in Outstanding — a one-time reconcile to fix).
- **Buy-back pays the Vault** ([product_template.py](jewellery_evaluator/models/product_template.py) `_settle_buyback_to_vault`, called from `init_jewellery_from_customer` after receipt): posts the PO's vendor bill and settles it from the branch Vault (`account.payment.register`) → net `Cr Vault`. Idempotent (one bill + one payment per PO, skips when already paid), isolated in a **savepoint** so a payment hiccup logs and retries on re-sync but never blocks the (reliable) stock receipt. Branch→Vault map is `stock.warehouse.vault_journal_id` ([stock_warehouse.py](jewellery_evaluator/models/stock_warehouse.py) `_vault_journal()`), falling back to the company's sole cash journal when unset.
- **Transfers** (bank deposit / branch-to-branch / petty cash) need **no module code** — any posted `Cr Vault` is picked up. Use native `account.payment` (Odoo 19 dropped `is_internal_transfer`/`destination_journal_id`; internal transfers now go via `destination_account_id` = `company.transfer_account_id`) or a manual JE `Dr <dest> / Cr Vault`. **Rule: never use POS Cash-In/Out for anything that already has a document** (payment/bill/JE) — that double-counts.
- **Window caveat:** only movements while a shift is open are attributed to it; a buy-back/transfer made between shifts isn't (the next shift's opening physical count absorbs it). **Replication:** each branch = its own `pos.config` + a `Vault - <branch>` cash journal (direct-posting) + Cash payment method + `warehouse.vault_journal_id`; all the code above is branch-agnostic. The two **InstaPay** journals were consolidated (BNK2 id 13 archived, IPAY id 15 keeps the POS method).

### POS cash-ops popups (Currency + Transfer to Owner) — move cash OUT of the Vault

[models/pos_cash_ops.py](jewellery_evaluator/models/pos_cash_ops.py) adds two `pos.session` `@api.model` RPCs that post real JEs via the general journal so the Vault sync above folds them into the shift automatically (they `Cr` the Vault, are not POS statement lines): `post_currency_conversion` (Dr Vault-Foreign / Cr Vault; the foreign leg carries `amount_currency` in the target currency) and `post_owner_transfer` (Dr Owner / Cr Vault). **Journals resolve BY CONVENTION, company-scoped** — single source of truth in `vault_foreign_journal_domain` / `owner_journal_domain` (reused by `pos.config`): **Vault Foreign** = cash journals in a non-company currency (USD/SAR/AED); **Owner** = cash journals named `Owner%` (Anas/Omar/Mohamed/Ahmed Abbassi). Shipped to the register as JSON on `pos.config.jewellery_vault_foreign_journals` / `jewellery_owner_journals` (injected in `_load_pos_data_read`, same non-field-Char trick as the override hash). **Hardened:** server-side journal **whitelist** (the frontend list is not trusted), an open-session guard, and **idempotency** via `account.move.jewellery_cash_ops_key` (indexed + unique) so a retry/double-click reuses the move instead of double-posting cash. Frontend ([static/src/js/pos_cash_ops.js](jewellery_evaluator/static/src/js/pos_cash_ops.js) + `.xml`) patches the **Navbar burger menu** — next to Cash In/Out (all Vault cash ops together), NOT the ControlButtons popup — registered in the `_assets_pos` bundle.

### Inventory invariant (stock is NEVER touched by sync/edit)

Hard rule: **no sync or edit path may adjust product inventory.** The single exception is initializing on-hand to **1** when an *entirely new* product is first written to Odoo (one unique physical piece). Two methods on `product.template` ([product_template.py](jewellery_evaluator/models/product_template.py)) are the only inventory writes, both called **only on the create branch** of the sync (`syncItemToOdoo` → `ensureStock`), never on write/edit/re-sync:

- **Normal / Lented pieces** → `init_jewellery_stock(warehouse_code, qty=1)`: marks the product `is_storable` (Odoo 19 dropped `type='product'`; a `consu` good only tracks stock when `is_storable` is set, else `stock.quant` raises "Quants cannot be created for consumables") and does an inventory adjustment with **SET (not add) semantics + search-or-create** — idempotent, can't inflate.
- **"Bought from Customer" pieces** → `init_jewellery_from_customer(warehouse_code, price_unit)`: the piece is created with stock 0, then brought on-hand via a real **Purchase Order receipt** (qty 1) from a fixed buy-back vendor (`res.partner` data record `jewellery_evaluator.partner_bought_from_customer`, needs `purchase` in depends) at the operator-entered buy-back amount, received into the selected warehouse's incoming picking type. One XML-RPC call = one transaction (atomic), **idempotent** (one PO per SKU via `origin`), handles serial-tracked goods (lot = SKU), and requires the sync user to be a Purchase Manager (`two_step` validation auto-approves for managers; raises otherwise). After the receipt it also **pays the buy-back cash out of the branch Vault** (`_settle_buyback_to_vault`) so the POS shift count reflects it — see Vault sync above.

The ops side ([marjaan-operations-server/server.js](../marjaan/marjaan-operations-server/server.js)) tracks a `stocked` boolean (DEFAULT true for pre-existing rows so they're never re-stocked; new rows insert `false`, flipped true on success). The `reconcileStranded` sweep retries `odoo_id`-set-but-`stocked=false` pieces — the reliability backstop. `pos_order.py` only *reads* `stock.quant`. Past on-hand inflation came from manual "Administrator" adjustments, not the sync.

**Manual invoices deduct stock (a SALE path, not a sync/edit path).** Stock Odoo never moves stock from an invoice — only deliveries do — so a piece sold from **Invoicing** (not the POS) stayed on-hand while sold (phantom stock). [account_move.py](jewellery_evaluator/models/account_move.py) overrides `_post`: a posted **`out_invoice` that is NOT a POS invoice** (`pos_order_ids` empty) reduces on-hand for each **storable** product line via an inventory adjustment (`_jewellery_reduce_onhand` — same clean primitive as `init_jewellery_stock`, works for serial + non-serial; the legacy no-lot-serial case a delivery can't cleanly handle). This is *not* a violation of the inventory invariant above — that governs sync/edit; this is a real sale, like the POS delivery. **Skips:** POS invoices (the session already delivered — double-count), SO-invoiced lines (the SO delivers), and **non-storable products** (sell-by-weight items: the line just *connects* the product, no stock). Idempotent via the `jewellery_stock_deducted` flag (a re-post never re-deducts); savepoint + `sudo`, so a stock hiccup logs but never blocks the invoice. Refunds are **not** handled (a return should add stock back — separate flow). **Workflow:** the cashier must *select the product* on the invoice line (not type the SKU as free text) for the deduction to fire.

### Purchasing (bulk gold / bars-coins / scrap)

[models/jewellery_purchase.py](jewellery_evaluator/models/jewellery_purchase.py) (extends `product.template`) adds `create_purchase_receipt(items, warehouse_code=None, origin=None, vendor_ref=None, settle_from_vault=False)` — **one PO + one validated receipt** for items matched by SKU (resolved up front, atomic; **idempotent per `origin`**; reuses the buy-back confirm/assign/pick/validate flow; returns `[{sku, product_id, name, qty}]`), and `jewellery_market_value(grams, purity='21K', gold_type='jewellery_local')` → `{base_21k, cost, sale, min_sale}` reference. Vendor = `partner_bulk_supplier` ([data/bulk_supplier_vendor.xml](jewellery_evaluator/data/bulk_supplier_vendor.xml)). Driven by the ops app's `/api/purchase/*` endpoints: **bars/coins/scrap** are pre-seeded SKUs → receipt only; **bulk** creates the pieces (Neon + Odoo) and their normal sync sets on-hand to 1 — it does **NOT** also run a receipt (that would double-count, since the sync already stocks them).

### Website shop (`jewellery_website`, third module)

[jewellery_website/](jewellery_website/) (standard layout, nested like `jewellery_inventory_management`, listed in `remote-deploy.sh` `SUBMODULES`) wires the eCommerce shop to the live catalogue. Kept separate so the POS/pricing module never depends on `website_sale`.
- **Titles:** products are named by SKU for the till (the ops sync sets name = SKU). `product.template.website_title` (stored compute, rules in [website_utils.py](jewellery_website/website_utils.py), tested in `tests/test_website_catalog.py`) builds "18K Gold Ring · 4.45 g" / "Diamond Ring · 18K Gold · 0.52 ct" from **`categ_id.complete_name`** (categories are hierarchical: name is just "Ring"). Shown on shop cards, product page, breadcrumb, `<title>`, search, cart (`name_short`) and order lines; `seo_name` is set once from it for clean URLs.
- **Catalogue sync** (`cron_sync_website_catalog`, every 15 min, 0.2 s when nothing changed): builds/adopts the eCommerce category tree (mirrors the Shopify collections; nodes get `jewellery_website.public_categ_*` xmlids), assigns categories from the internal category, and **publishes a piece exactly while it is in stock with a photo and a price** — a sold unique piece comes off within 15 min. Forces `allow_out_of_stock_order=False` (Odoo defaults it to True — a one-of-a-kind piece could otherwise sell twice). Owner-added categories and `website_catalog_managed=False` products are left alone.
- **Product page specs** read stones via `product.sudo().stone_ids`: visitors have **no ACL on `jewellery.stone`** and must never get one — it holds stone **cost** prices (`unit_price_usd`/`total_price_usd`). Without sudo every diamond page 403s.
- One-time shop config is [scripts/website/configure_shop.py](scripts/website/configure_shop.py) (signup, guest checkout, newest-first, no COD, free shipping Egypt-only, menus → real categories, 301s from the engineer's static mock-up URLs, theme demo categories removed). Open blockers are tracked in [docs/website-launch.md](docs/website-launch.md).
- **Testing on a copy:** restore a nightly dump into a scratch DB and run Odoo with `--no-http --workers=0 --max-cron-threads=0`. `/etc/odoo.conf` pins `db_name = marjaan`; without it the production cron worker runs every job on any database it can see (it did, on 2026-10-05 — Pulse rejected the duplicate daily summary via its idempotency key).

## Packaging & deployment

**Packaging trick (important):** the **repo root is the Odoo module** — root `__init__.py` + `__manifest__.py`, with the actual Python package and all `data`/`views`/`security`/`report` files under the `jewellery_evaluator/` subdirectory (hence manifest paths like `jewellery_evaluator/security/...`). Root `__init__.py` only imports the subpackage when loaded by Odoo (`if __package__`), so pytest/mypy can import `utils.py` even though the repo dir name has hyphens. The addons path must point at the **parent** of a directory named exactly `jewellery_evaluator` (no hyphens).

**Second module is a normal subdir — but the repo root is itself an addon, so the subdir is *nested*, not a sibling Odoo can see.** `jewellery_inventory_management/` lives inside `jewellery_evaluator` (the repo root), so it is NOT a top-level addon on the runtime addons path and won't appear in "Update Apps List" on its own. [scripts/remote-deploy.sh](scripts/remote-deploy.sh) fixes this for each name in its `SUBMODULES` list (default: `jewellery_inventory_management`) by creating a **persistent sibling symlink** in the repo's parent dir (the runtime addons path, e.g. `/opt/odoo/custom-addons/jewellery_inventory_management → …/jewellery_evaluator/jewellery_inventory_management`), plus an ephemeral staging symlink for the upgrade run. **Add any future repo-subdir module to that `SUBMODULES` list.** First install is still manual (Apps → Install); if a module ever fails to show up, check that sibling symlink exists on the addons path.

**Deploy** is push-to-`main` → GitHub Actions ([.github/workflows/deploy.yml](.github/workflows/deploy.yml)) runs `ci.sh`, then SSHes to EC2 and runs [scripts/remote-deploy.sh](scripts/remote-deploy.sh): it `git pull --ff-only`, stops Odoo, **symlinks the repo root to a temp `jewellery_evaluator` addon dir** (plus each `SUBMODULES` entry), runs `odoo -u jewellery_evaluator,jewellery_inventory_management --stop-after-init`, and restarts Odoo. First-time module install is manual (Apps → Install); deploy only upgrades (and `-u` on an installed-elsewhere/not-yet-installed module is a harmless no-op).

**Report XML is DB-cached:** editing `report/report_invoice_gold.xml` (custom gold invoice layout) requires a **module upgrade** (`-u jewellery_evaluator`) to take effect — a plain server restart will not reload it.

**`-u` MUST target the database (`-d`):** the prod `/etc/odoo.conf` has no `db_name`, so `odoo -u <modules>` with no `-d` has no database to act on and **silently upgrades nothing** — every XML/data change (cron records, report templates, views, security) is skipped while Python still reloads via the restart. This silently bit cron-interval and invoice-report changes until `remote-deploy.sh` was fixed (commit `9d70a3c`) to pass `-d "$DB_NAME"` (resolves `$ODOO_DB` → config `db_name` → `marjaan`). Manual reload: `sudo systemctl stop odoo && sudo -u odoo <odoo-bin> -u jewellery_evaluator -d marjaan --stop-after-init -c /etc/odoo.conf && sudo systemctl start odoo`.

**PDF headers/footers need patched-Qt wkhtmltopdf:** Ubuntu's distro `wkhtmltopdf` (`/usr/bin`, 0.12.6 *without* patched qt) silently drops `--header-html`/`--footer-html`, so page headers and footers never render (the report body still does). The prod box has the **patched build installed at `/usr/local/bin/wkhtmltopdf` (`0.12.6.1 (with patched qt)`)**, which is first on PATH. **This is a server-side install, NOT in git — if the EC2 box is rebuilt it must be reinstalled** (jammy `.deb` from the wkhtmltopdf releases) or invoice headers/footers will silently break again. The gold invoice uses a deliberately **blank header** (Marjaan prints on pre-printed letterhead) — see `external_layout_gold.xml` — plus a custom 3-column page footer.

**Odoo self-healing (watchdog) — server-side, NOT auto-deployed:** the stock `odoo.service` had **no `Restart=`**, so any process death (crash, failed start, OOM kill on the 3.7 GB / **zero-swap** box) left Odoo `failed` until a human ran `systemctl restart odoo` — the recurring "502, odoo down again". Fixed by [scripts/install-odoo-watchdog.sh](scripts/install-odoo-watchdog.sh): a `Restart=on-failure` systemd drop-in (auto-restart in 5 s) **plus** a 1-minute watchdog timer (`/opt/odoo/odoo-watchdog.sh`) that restarts Odoo if it's `failed` or `active`-but-unresponsive (502/hung) — the case `Restart=` can't see. The watchdog is **deploy-safe** (ignores the brief `inactive`/`activating` states a deploy produces). **Like wkhtmltopdf, this is installed on the box, not in the deploy path — re-run `install-odoo-watchdog.sh` if the EC2 box is rebuilt.** The original trigger was *overlapping* `remote-deploy.sh` runs (each stop/starting Odoo) flapping a transient `passlib` import failure; `deploy.yml` now has a `concurrency` group to serialize deploys.

**Backups — server-side, NOT auto-deployed:** `marjaan-backup.timer` runs [scripts/backup/server-backup.sh](scripts/backup/server-backup.sh) nightly at 03:15 Cairo: verified `pg_dump` + config snapshot to `/var/backups/marjaan` (7 nights), and — once `/etc/marjaan-backup.env` has the write-only key from [aws-setup-cloudshell.sh](scripts/backup/aws-setup-cloudshell.sh) — DB, config and filestore to S3. Failures alert via Pulse `job-failed`. The Mac mini pulls its own copy with [backup-to-local.sh](scripts/backup/backup-to-local.sh). Restore was tested 2026-09-27 (95 s, row counts matched). Runbook: [scripts/backup/README.md](scripts/backup/README.md). **Re-run `install-server-backup.sh` if the box is rebuilt.**

**Log rotation — server-side, NOT auto-deployed:** [scripts/install-logrotate.sh](scripts/install-logrotate.sh) — `odoo.log` daily ×30 + early rotation at 200 MB, rsyslog `maxsize 200M`, logrotate timer hourly. It replaced `/etc/logrotate.d/00-size-guard`, which listed `/var/log/syslog` a second time and made logrotate fail daily with "duplicate log entry". Never list one path in two logrotate files. Odoo logs via `WatchedFileHandler`, so `create`-style rotation is safe (no `copytruncate`).

## The physical day book (`PHYSICAL_LEDGER/`) — reading and transcribing it

The handwritten Arabic day book (دفتر اليومية) is the **source of truth** for the
business. Odoo is reconciled *against* it, never the other way round. Everything below
was learned the hard way transcribing 53 pages (26 Jun – 16 Aug 2026); re-derive none of it.

### Page anatomy

- Each photo in `PHYSICAL_LEDGER/` is named for its page date (`YYYY-MM-DD.jpeg`; a
  second page for one day gets `-1` / `-2`).
- Every page carries a **red 6-digit serial**. For this set they run **000003–000055
  with no gaps** — the serial is the strongest integrity check available: it proves no
  page is missing or duplicated, and it dates a page whose digits are unreadable.
- **Read the date from the day-name + serial position, not the digits.** Five filenames
  were initially wrong from digit-reading alone (٤ read as ١٤, ٣٠ as ٢٠). The red Arabic
  day name cross-checked against the 2026 calendar settles it.

### Column geometry (memorise — getting this wrong silently corrupts everything)

Printed header, read **left to right** across the page:

```
ملاحظات | مصدر | بيــان | فئة | جرام | مللي | منصرف | وارد
```

- **وارد (money in) is the RIGHTMOST column; ملاحظات is leftmost.**
- **جرام sits to the LEFT of مللي.** Do not swap them.
- `جرام` + `مللي` are the two halves of ONE weight (جرام=10, مللي=91 → 10.91 g).
  Keep them in **separate** columns and do no arithmetic on them.
- `فئة` is karat (18/21/22/24) and is empty on many pages.
- `مصدر`: بيع = sale, مشترى/مشتري = purchase, مرجوع/مرتجع = return, حل, شغل, قلب.

### Notation — three conventions that cause silent, order-of-magnitude errors

1. **Separators are THOUSANDS, not decimals.** `٤٧٫٧٠٠` is **47700**, never 47.7 or 4770.
2. **The trailing tail is two different marks:** a **wavy tail = two zeros (`00`)**, a
   **small comma/dot = one zero (`0`)**. This was the single largest source of ×10
   errors across the whole ledger (81 of 615 cross-pass disagreements).
3. **Money is often BRACKET-GROUPED:** a `}` spans several rows and **one** figure covers
   the whole group, written on the group's **top** row. A blank money cell frequently
   means "included in the brace above", not zero.

### The bottom figure is NOT a page total

Rows at the foot of a page look like totals but are **carried / cumulative balances**.
Proof: `2026-06-30` shows 7,169,450 against entries summing to 1,155,760; `2026-06-28`
shows 2,244,670 against a page وارد sum of 296,230. **Do not reconcile a page against
them, and do not treat them as daily takings when comparing to Odoo.** A solver that
used them to "prove" ambiguous digits by arithmetic was built and correctly found
nothing — the constraint does not exist.

### Sanity band — as a re-read trigger only, never a correction

Implied EGP per gram, 2026: **bars ~4,500 · jewellery ~5,600–7,000 · coins ~10,100–10,650**.
A single 4,000–10,000 band is too crude (coins legitimately exceed it).
If a row falls far outside its band, **re-read it** — but if the digits really are what
they are, **keep them as written and flag**. Never bend a figure to satisfy the check.

### Handwriting traps

`٤` vs `١٤` · `٣٠` vs `٢٠` · `٥`/`٦`/`٠` · `٧`/`٨` · `١١`/`١٧`.
Eastern Arabic digits throughout: `٠١٢٣٤٥٦٧٨٩` = `0123456789`.

### Transcription methodology (the important lesson)

**A single pass's own confidence flags are not trustworthy.** They catch illegibility but
are blind to being *confidently wrong*. Measured on this ledger: pass A self-flagged only
80 `grams` cells across 779 rows, yet an independent second pass **disagreed on 122**.

Use **N independent passes and diff them.** Agreement between blind reads is real
evidence; self-assessment is not.

| passes | result |
|---|---|
| 1 (self-flagged) | looked ~47% trustworthy — overstated |
| 2 (diffed) | **300/779 rows (39%)** agree on every number |
| 3 (June only) | **556/695 cells (80%)** triple-confirmed; 56 cells unresolvable |

Practical rules for any future run:
- Give each pass **enlarged crops** of the numeric columns; at 960×1280 the raw page is
  at the limit of legibility. Enlargement helps the reader resolve strokes but **adds no
  information** — it cannot recover what compression destroyed.
- Diff **per cell**, not per row, and report `CONFIRMED` / `MAJORITY` / `UNRESOLVED`.
- Ship the unresolved cells as an explicit worklist with every candidate reading, so a
  human settles a short finite list instead of re-checking everything.

### Image quality is the binding constraint

The photos are WhatsApp-compressed (960×1280 / 1200×1600, EXIF stripped) and the
originals no longer exist. **No processing recovers that detail.** If more accuracy is
ever needed, re-photograph the book at full camera resolution — that is worth more than
any number of extra passes.

### Artifacts

- `PHYSICAL_LEDGER_TRANSCRIPTION.xlsx` — all 53 pages, 779 rows, passes A and B side by
  side, disagreements highlighted; sheets `Confirmed` (300) and `Needs human` (479).
- `JUNE_LEDGER_VERIFIED.xlsx` — June only, three passes, per-cell consensus, plus
  `Cells needing the book` (the 56 genuinely unresolved cells).

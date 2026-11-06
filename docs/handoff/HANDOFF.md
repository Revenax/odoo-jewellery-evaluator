---

## Handoff: 2026-07-11T17:06:40Z (auto-saved before compaction)

### Compaction Metadata
- Trigger: auto
- Custom instructions: (none)
- Transcript: /Users/abdallah/.claude/projects/-Users-abdallah-Projects-odoo-gold-pricing-engine/baa30455-a9ff-48b3-8491-e2587ecdb564.jsonl
- CWD: /Users/abdallah/Projects/marjaan/marjaan-operations-server

### Last User Message (transcript tail)
(unavailable)

### Last Assistant Message (transcript tail)
(unavailable)

### Git Snapshot
- Branch: main
- Status:
?? docs/
- Recent commits:
ea4dda1 feat(pos): Currency + Transfer-to-Owner popups [HELD, not in manifest]
0578fce feat(pos): backend JEs for currency conversion + owner transfer
d94dd0c fix(purchase): f-string origin (ruff UP031)
d6db041 feat(purchase): batched bulk-receipt method + market-value + bulk supplier
fee0300 feat(pos): surface below-min override approver on the order (audit)

### Model Summary
- Task: "Build all ops and push. then summarize all odoo updates." (HUGE UPDATE: purchasing + POS cash-ops + Silver material). DONE.
- Ops app (repo `marjaan-operations-server`, separate git, deploys to Vercel — isolated from live Odoo) pushed as `87a68e5`.
- New ops endpoints in `server.js`: `GET /api/purchase/companies`, `GET /api/purchase/market-value`, `POST /api/purchase/receipt` (bars/coins/scrap), `POST /api/purchase/bulk` (new gold pieces). All additive; existing routes untouched.
- New `public/purchase.html` (standalone Bulk / Bars-Coins / Scrap screens) + a "Purchase" tab in `index.html` linking to it.
- Silver material picker: `index.html` Silver button + 999.0/999.9 fineness grid; `wizard.js` Silver stepOrder `[1,2,ptype,3,4,5,confirm]` + a `s===3` toggle swapping gold karats for silver fineness; `server.js itemToOdooVals` now maps `silver_purity` (no gold_purity/gold_type when jewellery_type==="silver").
- Correctness catch fixed pre-push: bulk pieces are stocked by the normal sync (init_jewellery_stock SET=1); removed the extra PO receipt from `/api/purchase/bulk` — it would have double-counted (on-hand 2). Also fixed a misaligned bulk INSERT ($8 referenced, warehouse param missing).
- Odoo LIVE (origin/main = `0578fce`): purchase backend `create_purchase_receipt` + `jewellery_market_value` + `bulk_supplier_vendor.xml` (`d6db041`/`d94dd0c`); POS cash-ops backend `post_currency_conversion` + `post_owner_transfer` (`0578fce`, backend-only, no UI yet). Silver `jewellery_type` verified auto-pricing — no Odoo change needed.
- Odoo HELD (local `ea4dda1`, NOT pushed, NOT in manifest): `static/src/{js,xml}/pos_cash_ops.*` — POS "Currency" + "To Owner" popup buttons.
- Verified: `node --check server.js` OK; ESM syntax-check of wizard.js/submit.js/sku.js OK.

### Handoff Context (paste into next session)
- Everything requested this turn is done and pushed. Ops `87a68e5` on `Revenax/marjaan-operations-server` main → Vercel auto-deploys (safe, isolated from Odoo/POS).
- Odoo repo (`odoo-gold-pricing-engine`): local `main` is 1 commit AHEAD of origin — that ahead commit is the HELD `ea4dda1` (POS Currency/To-Owner popups). Do NOT push it standalone; it needs the manifest + pos.config journal loading first.
- To ship the held POS popups (needs a POS-CLOSED window): (1) load `vault_foreign_journal_ids` + `owner_journal_ids` onto `pos.config` via `_load_pos_data`; (2) staging-verify the OWL ControlButtons patch vs core Odoo 19; (3) register `static/src/js/pos_cash_ops.js` + `static/src/xml/pos_cash_ops.xml` in the `point_of_sale._assets_pos` bundle in `__manifest__.py`; (4) push (asset-bundle change → module upgrade).
- Still pending (not code): create the `SCRAP-SILVER` product with `silver_purity='999.0'` (gold scrap SKUs already seeded; silver deferred because silver uses silver_purity not gold karat). Bars/coins full matrix seeding — confirm all GB-*/GC-* SKUs exist on prod before relying on `/api/purchase/receipt` (it errors clearly if a SKU is missing).
- Ops verification TODO when convenient: hit `/purchase.html` on the deployed Vercel app, register one Silver piece end-to-end, and confirm on prod Odoo it lands as `jewellery_type=silver` with `silver_purity` set and a computed `list_price`.
- Constraint still in force: "only push changes that surely won't break prod." Ops/Vercel is isolated; the Odoo held commit stays local until the POS-closed window.

---
---

## Handoff: 2026-07-19T10:30:15Z (auto-saved before compaction)

### Compaction Metadata
- Trigger: auto
- Custom instructions: (none)
- Transcript: /Users/abdallah/.claude/projects/-Users-abdallah-Projects-odoo-gold-pricing-engine/db9b4198-5eaf-4bd2-8409-4341c51bbb9f.jsonl
- CWD: /Users/abdallah/Projects/odoo-gold-pricing-engine

### Last User Message (transcript tail)
(unavailable)

### Last Assistant Message (transcript tail)
(unavailable)

### Git Snapshot
- Branch: main
- Status:
 M docs/handoff/HANDOFF.md
- Recent commits:
0b39036 feat(invoice): redesign — SKU|Desc|Karat|Weight|Value + per-stone rows + footer QR
54b200f fix(pos): parent_id recordset (not bool) — mypy union-attr
5255613 feat(pos): auto-assign POS category from product Material/Shape
1b4982c fix(invoice): diamond weight = gross (gold+stones summed), not split
c7024b8 fix(invoice): weight grams 2dp, carat 3dp (split format_carat)

### Model Summary
- Task in flight: "New Invoice design" — 5-column gold invoice `SKU | Description | Karat | Weight | Value`, per-stone rows under diamond lines, pre-baked footer QR to marjaanjewellery.com. Constraint: "NO DOWN TIME. PLAN AHEAD."
- `report/report_invoice_gold.xml` FULLY REWRITTEN: added SKU col before Description; Description = Title-Case `Material Shape` from `line.product_id.categ_id` (parent.name + ' ' + name when parent in Gold/Diamond/Silver, else line.name); Karat + Weight cols after Description; Weight = `'%.2fg' % wt` (diamond wt = `gross_jewellery_weight_g`, else jewellery/gold weight fallbacks); Value = `t-out price_subtotal` float widget precision 0 + " EGP"; removed Qty/Unit-Price/Discount/Tax cols; stone rows via `//tr[td[@name='account_invoice_line_name']]` position=after, one `<tr>` per `sp.stone_ids`, detail `'%s &#215; %gct%s' % (qty, carat, ' '+shape)` in Weight col, other 4 cells blank.
- `report/external_layout_gold.xml` REWRITTEN: shared `marjaan_invoice_footer_body` template (3-col Contact | QR | Terms) t-called by all 7 layout variants (standard/striped/bold/boxed/folder/wave/bubble) + blank-header override kept. QR = static base64 PNG (Odoo live QR renderer broken on box — needs `rlPyCairo`).
- QR PNG pre-baked with segno (venv `.qrvenv`, PEP 668 blocked direct pip): base64 at `scratchpad/qr_b64.txt` (628 chars, navy #0f1138 on white, err='h'), links https://marjaanjewellery.com.
- Both XML files validated well-formed (`xml.dom.minidom.parse`). Report-template ONLY — no Python field added.
- Committed LOCALLY as `0b39036`, **NOT pushed** (push auto-triggers the -u deploy = restart). Local main 1 ahead of origin.
- Deploy blocker = report XML is DB-cached → needs `-u jewellery_evaluator -d marjaan` → Odoo restart ~15-30s. Cannot render the new invoice for the user to eyeball until deployed. Waiting on user "go" (POS-quiet window).
- Prior shipped this session (already on origin + LIVE): diamond weight = gross sum (`1b4982c`), POS category auto-assign from Material/Shape (`5255613`, mypy fix `54b200f`), format helpers in utils.py + `tests/test_invoice_format.py`.

### Handoff Context (paste into next session)
- IMMEDIATE NEXT STEP: wait for user "go", then `git push origin main` (deploys `0b39036`). Push = GitHub Actions CI (ruff/pytest/mypy) → CD `remote-deploy.sh` → `-u jewellery_evaluator -d marjaan` → ~15-30s Odoo restart.
- After deploy: SSH prod (`ssh -i ~/Documents/marjaan-odoo-19.pem ubuntu@odoo.marjaanjewellery.com`), odoo-shell render a real **diamond** invoice + a **gold** invoice to PDF/HTML (find a posted out_invoice with a diamond_jewellery product line that has stone_ids), verify: 5 columns, Title-Case description, weight 2dp+g (diamond=gross), Value "X,XXX EGP", per-stone rows, footer QR renders. odoo-shell: `sudo -u odoo /opt/odoo/odoo-venv/bin/python3 /opt/odoo/odoo/odoo-bin shell -c /etc/odoo.conf -d marjaan --no-http < script.py` (shell does NOT auto-commit; render is read-only anyway).
- If layout off → quick fix-forward (edit XML, commit, push again).
- Two report files are the whole change: `jewellery_evaluator/report/report_invoice_gold.xml` (table) + `jewellery_evaluator/report/external_layout_gold.xml` (footer QR). QR base64 source: `scratchpad/qr_b64.txt`.
- DO NOT try live `ir.ui.view.arch_base` write to dodge the restart — decided against it (new shared footer view + inherited-view arch reconstruction is error-prone on prod). Coordinated -u-in-quiet-window is the plan.
- Deferred (owner's call, memory `validation-deferred-findings.md`): over-sell guard no-op (skip), forgeable override auth (don't care), manual-invoice sticky flag/refund add-back.
- /v2 ops front-end LIVE at operations.marjaanjewellery.com/v2 (React); cutover to root pending owner sign-off. Legacy `public/` untouched at root.
- Product-side category cleanup (dup "Gold / Coin", legacy "Gold / Ingot") offered, not requested.

---
---

## Handoff: 2026-07-25T11:52:59Z (auto-saved before compaction)

### Compaction Metadata
- Trigger: auto
- Custom instructions: (none)
- Transcript: /Users/abdallah/.claude/projects/-Users-abdallah-Projects-odoo-gold-pricing-engine/0e8316ed-0f1e-4064-8562-c69c9e47e28c.jsonl
- CWD: /Users/abdallah/Projects/marjaan/marjaan-operations-server

### Last User Message (transcript tail)
(unavailable)

### Last Assistant Message (transcript tail)
(unavailable)

### Git Snapshot
- Branch: main
- Status:
 M docs/handoff/HANDOFF.md
- Recent commits:
62210cd feat(diamond): Center Stone jewellery type (loose diamond, no gold) — Odoo side
0dac371 feat(diamond): bundle Rap grid install-seed + post_init_hook
b2e5bc8 feat(diamond): empty discount cells display 0 (absent already prices as 0)
3221653 feat(diamond): show the 5 legacy tiers as the first 5 Rap editor tables (front-end only)
4fccd71 feat(diamond): per-cell Rap discount % (stacked cell) — net = list x (1 - pct)

### Model Summary
- **All 5 workstreams from the "New Target" message are DONE, deployed to prod, and verified.** No pending work at session end.
- **Center Stone** jewellery type (loose diamond, no gold, priced by its one stone; SKU `DS-NNNN`) shipped system-wide — Odoo `62210cd`, ops `4ea1bc3`+`6b290dc`. Reuses all diamond Rap/tier pricing via an `is_cs` branch (weight 0, skips gold checks). Prod-savepoint verified (0.5 ct → SKU `DS`, $950 Rap; 0.10 ct → $95 tier). No existing product is `center_stone`, so legacy pieces are unaffected.
- **v2 promoted to production root** (ops `1ef933f`): React app now at `/`, legacy kept at `/legacy` (owner's safety call). `vite base:'/'`, PWA scope `/`, SPA fallback regex can't shadow `/api`|`/legacy`, `/v2`→301. Live-verified 11/11 serving paths + 148 Vitest.
- **Rap editor tier tables → one read-only cell each** (Odoo `5c352f7`): the 5 `<0.25 ct` tiers now show the live `diamond_stone_tier_N_usd` value ($800/950/1100/1250/1350), display-only. Sub-0.25 pricing untouched. Prod `rap_get` verified: 5 single cells + 13 editable grids.
- **Rap grids install-seed** bundled via `post_init_hook` (Odoo `0dac371`): seeds `diamond_rap_{round,exotic}` from `data/diamond_rap_seed.json` only if empty (install-only). Fresh DB rebuild no longer loses grids.
- **GTC→BTC repair: NOTHING TO REPAIR.** Exhaustive read-only prod scan found zero "GTC" (SKUs, names, POs, invoices+lines, lots, POS lines) and none in git history (only package-lock hash false positives). `BTC` is a bar company, already correct (`GB-BTC-*`/`GC-BTC-*`). Reported honestly to owner; asked for a concrete example if they believe otherwise.
- **CI gate green** (ruff / mypy on utils.py / 85 pytest). Key mypy gotcha: `RAP_STRUCTURE` needed `list[dict[str, object]]` (mixed-shape entries widen to `object`; CI mypy follows the package graph into models even though it only names utils.py).
- **Owner answers applied:** per-cell discounts = out of scope (owner does it); Rap on/off toggle = not built (never needed).
- Memory updated: `ops-frontend-rebuild` (cutover done), `diamond-rap-pricing` (seed + tier cells), new `center-stone-jewellery-type` and `gtc-btc-noop`.

### Handoff Context (paste into next session)
Session is COMPLETE — everything shipped and verified. Nothing is mid-flight. Both repos are clean and in sync with origin (odoo `5c352f7`, ops `1ef933f`); the only dirty file is this `HANDOFF.md` (auto-save).

If resuming to build on this work, key facts:
- **Repos:** Odoo module = `/Users/abdallah/Projects/odoo-gold-pricing-engine` (repo root IS the module). Ops app = `/Users/abdallah/Projects/marjaan/marjaan-operations-server`.
- **Deploy:** Odoo = push to `main` → GitHub Actions CI (ruff/pytest/mypy) → CD `-u jewellery_evaluator -d marjaan`. Ops = push to `main` → Vercel (server.js direct, `web/dist` committed, NO build step, NO vercel.json).
- **Ops front-end going forward lives in `web/` only** (React). `/legacy` (`public/`) is the OLD app, kept as a fallback — do not add features there.
- **Center Stone** = `jewellery_type='center_stone'`, category "Center Stone", SKU `DS`. Priced by its stone (Rap ≥0.25 / tier <0.25), no gold. SKU parity must stay across `server.js` + `web/src/lib/sku.ts` + `public/js/sku.js`.
- **Diamond Rap pricing:** `utils.get_stone_price_usd(env, shape, carat, colour, clarity)`; `<0.25`→`get_stone_tier_price` (flat `_STONE_TIERS`), `≥0.25`→Rap grid `net = cell×100×carat×(1−disc/100)`. Editor = backend client action "Diamond Rap Prices"; `models/diamond_rap.py` `rap_get`/`rap_set`. Tier buckets are read-only (single cell from live param); only `≥0.25` grids are editable.
- **Local CI check** (no venv on the box): `python3 -m venv /tmp/v && /tmp/v/bin/pip install ruff pytest mypy`, then `ruff check ...`, `pytest tests/ -q`, `mypy jewellery_evaluator/utils.py --ignore-missing-imports`.
- **Prod access** (read-only scans / savepoint tests): see memory `prod-server-access` — SSH `ubuntu@odoo.marjaanjewellery.com`, DB `marjaan`, odoo-shell via `sudo -u odoo .../odoo-bin shell -c /etc/odoo.conf -d marjaan --no-http < script.py` (does NOT auto-commit).
- **Open/known items (not this session's scope):** per-cell Rap discounts are owner-populated; `validation-deferred-findings` memory lists pre-existing bugs awaiting owner decision; GTC has nothing to fix unless owner supplies a concrete example.

---
---

## Handoff: 2026-07-26T13:32:29Z (auto-saved before compaction)

### Compaction Metadata
- Trigger: auto
- Custom instructions: (none)
- Transcript: /Users/abdallah/.claude/projects/-Users-abdallah-Projects-odoo-gold-pricing-engine/77864824-93f5-4910-b4b5-bd7ffff78791.jsonl
- CWD: /Users/abdallah/Projects/marjaan/marjaan-operations-server

### Last User Message (transcript tail)
(unavailable)

### Last Assistant Message (transcript tail)
(unavailable)

### Git Snapshot
- Branch: main
- Status:
 M docs/handoff/HANDOFF.md
- Recent commits:
e57f4ec fix(report): blank invoice header via visibility:hidden (never delete)
04c9868 fix(deploy): pin ODOO_BIN to the enterprise wrapper in CI
024ca7c fix(deploy): detect the EFFECTIVE odoo ExecStart (last), not the base unit's
8892852 fix(deploy): don't override --addons-path on the Enterprise box
e31afe9 fix(report): blank invoice header via priority=999 (July-core safe)

### Model Summary
- Prod Odoo `marjaan` was promoted Community 19 → **Enterprise** (deb `19.0+e-20260725` at `/opt/odoo-e`, wrapper `/opt/odoo/ee-odoo-bin`, systemd drop-in `enterprise.conf`). Registered code M260622307196412 (valid to 2027-07-25). Validated live: vault direct-posting 16/16 survived, POS bundle compiles, invoice PDF renders.
- Invoice header blanking finalized: `external_layout_gold.xml` uses `position="attributes"` → `visibility:hidden` (NEVER delete the header — July core `account_edi_ubl_cii`/`l10n_eg` xpath into its inner divs). Commit e57f4ec.
- CD hardened for Enterprise: `deploy.yml` pins `ODOO_BIN=/opt/odoo/ee-odoo-bin` (04c9868); `remote-deploy.sh` detects EFFECTIVE ExecStart + drops `--addons-path` override (024ca7c/8892852). `-u` MUST pass `-d marjaan`.
- POS unique-piece epic DEPLOYED (4bf0525/e50f746/be2e284): hide sold XXXX-NNNN, block re-sale w/ manager override, qty 0/1 watchdog, ref==barcode==SKU, read-only Rap viewer in POS.
- **Stones re-sync investigation (current, UNRESOLVED by data): Odoo already mirrors production Neon exactly.** Pulled the REAL prod DB by reading `operations.marjaanjewellery.com` `/api/items` with a signed admin cookie (prod `COOKIE_SECRET` from Revenax Vercel scope; `DATABASE_URL` is Sensitive/unpullable). Live `products.stones` = uniform 415 G/VVS1, 35 H/VVS1, 1 H/VS1 (259 products/451 stones). Per-SKU diff vs Odoo: only carat 4dp→3dp rounding; colour/clarity/cut/shape/qty identical.
- Local `.env` Neon (`ep-icy-sky-apwbm5qa`) is NOT stale — matches live prod within 2 rows. Earlier re-sync (255 products via odoo-shell) WAS correct. `items` table empty; no other stone column; `parseStones` doesn't default grades.
- **So the user's claimed grade changes are NOT in production `products.stones`.** Asked user to name one SKU + expected grade, or point to the real source (ops-app UI save-failure / spreadsheet / bulk-set).
- Open, non-blocking: MJ-1105 credit note RINV/2026/00004 `payment_state=not_paid` (refund cash not settled to Vault); DRL8-0001 orphan stone (Odoo tmpl 230, not in Neon) ungraded; auto-restock-on-refund feature offered not built.

### Handoff Context (paste into next session)
- CURRENT TASK: resolve "I changed the stones data, reflect in Odoo." Proven: Odoo == live prod Neon (only carat rounding differs). Ball is with the user — awaiting a specific SKU + expected grade, or the real source of their edits. DO NOT re-sync again until the source is confirmed; another blind re-sync repeats the same uniform G/VVS1.
- How to read the REAL prod data without the Sensitive `DATABASE_URL`: `vercel link --yes --project marjaan-operations-server --scope revenax`, `vercel env pull` (DB/ODOO vars come back `[SENSITIVE]`, but `COOKIE_SECRET` + `ADMIN_USERS` are readable). Forge cookie `user=` via `cookie-signature` `s:`+sign('mohamed-abdallah', COOKIE_SECRET), GET `https://operations.marjaanjewellery.com/api/items` (admin returns all rows incl. `stones`). ALWAYS delete pulled `.env.prod`/`.env.local`/`.vercel` after (they hold AWS + cookie secrets) and `git checkout .gitignore` (vercel link appends to it).
- Odoo shell on box: `ssh -i ~/Documents/marjaan-odoo-19.pem ubuntu@odoo.marjaanjewellery.com` then `sudo -u odoo /opt/odoo/ee-odoo-bin shell -c /etc/odoo.conf -d marjaan --no-http < script.py`. Neon `products.odoo_id` = product.TEMPLATE id.
- If user confirms edits were in the ops app: check the write path / re-save; if a spreadsheet: import to Neon then re-sync (`product.template.write({'stone_ids':[(5,0,0)]+creates})` per odoo_id). To WRITE back without DATABASE_URL, use the app API + forged cookie.
- Scratch (no secrets): `<scratchpad>/live_items.json` (full prod pull), `live_stone_map.json` ({sku:stones}).
- Server-side installs NOT in git (re-run if EC2 rebuilt): patched-Qt wkhtmltopdf at `/usr/local/bin`, `install-odoo-watchdog.sh`. Box has 3.7GB RAM / zero swap — if Odoo down, check `df -h /` + `/tmp/chrome-silver-*` first.

---
---

## Handoff: 2026-08-31T06:32:57Z (auto-saved before compaction)

### Compaction Metadata
- Trigger: auto
- Custom instructions: (none)
- Transcript: /Users/abdallah/.claude/projects/-Users-abdallah-Projects-odoo-gold-pricing-engine/cc0bda91-1dfc-4b46-9692-3f602e915eb9.jsonl
- CWD: /Users/abdallah/Projects/odoo-gold-pricing-engine

### Last User Message (transcript tail)
(unavailable)

### Last Assistant Message (transcript tail)
One row you can't get from a plain grep: **`shift-closed-short`**. It's chosen at runtime (`topic = 'shift-closed-short' if abs(diff) >= 0.01 else 'shift-closed'`), so a literal scan misses it — it's in the CSV as its own row.

### Git Snapshot
- Branch: main
- Status:
 M docs/handoff/HANDOFF.md
- Recent commits:
96d52c5 update the invoice footer phone to +2 010 11 480 480
c3458db annotate the payment totals dict for mypy
fad2589 say how a sale was paid in the notification
662c234 kill the chrome processes a failed silver scrape leaves behind
358d04c make every notification non-blocking

### Model Summary
- Session focus: **Revenax Pulse notifications** end-to-end across two repos (this one + `marjaan-operations-server`), plus server cleanup and invoice polish.
- Pulse client lives at [jewellery_evaluator/pulse.py](jewellery_evaluator/pulse.py). `notify()` never raises; `notify_in_background()` resolves credentials on the CALLING thread and hands a plain tuple to a daemon thread (ORM cursor is not thread-safe). Retries only 429/5xx/timeouts, `MAX_ATTEMPTS=3`, `TIMEOUT_SECONDS=5`, `MAX_RETRY_AFTER=30`.
- Credentials: env → `ir.config_parameter` (`jewellery_evaluator.revenax_pulse_*`) → module constants. Single sender **Marjaan** for both repos; topic sets verified disjoint (`comm -12`).
- **44 distinct topics** (19 Odoo + 25 ops), 51 call sites. Delivered `revenax-pulse-notifications.csv` (columns `system, action, topic, title, body, extra, delivery, source`), cross-checked both ways against code — no topic missing, none invented. `shift-closed-short` is runtime-chosen so a literal grep misses it.
- Sale notifications now say HOW it was paid: hook moved from `create()` to `_process_order` (core attaches payments after create), `format_payment_summary()` in `utils.py` — one method = name only, split = amounts largest-first (commit fad2589).
- **gevent crash-loop fixed (biggest win):** `ee-odoo-bin` used `python3 -m odoo`, so Odoo respawned the worker by re-executing `__main__.py` → `ImportError: attempted relative import with no known parent package`, ~43 respawns/sec for weeks. Launch `/opt/odoo-e/usr/bin/odoo` instead. Forks 53→0, CPU ~60%→0%, port 8072 finally listening. **This fix is on the box, NOT in git.**
- Disk 95%→57%: `/var/log/syslog.1` was 7.1 GB of that traceback. Truncated (not deleted — rsyslog holds the fd), added `/etc/logrotate.d/00-size-guard`.
- **Chrome leak fixed** (commit 662c234): `driver.quit()` was unguarded as the first `finally` statement, so 22 orphans held 1.7 GB. Added `pids_for_profile()` (blank profile matches NOTHING) + `_kill_profile_processes()` SIGTERM-then-SIGKILL. Verified by planting 3 live processes.
- Invoice work: footer phone `+2 010 11 480 480` (96d52c5), column rules scoped to `table[name='invoice_line_table']`, diamond line refactored to `17 DR 1.25CT` (both renderers — `invoice_diamond_note` AND the report sub-row share `stone.invoice_display`), Center Stone weight renders blank.
- Terms & Conditions purge: not a live setting — Odoo copies terms into each invoice's `narration` at creation. Cleared company defaults + narration on 8 invoices, matching only auto-inserted text so human notes survived.
- No Arabic in HARDCODED notification text (AST guard `tests/test_no_arabic_in_notifications.py`); runtime VALUES (customer names) deliberately untouched — the user corrected an earlier over-reach here. POS day book stays Arabic.
- Test suite ~180 pytest tests, all pure (no Odoo import). Two AST guards pin the rules: no-Arabic and notifications-never-block.

### Handoff Context (paste into next session)
- Working tree is clean apart from this file. Last commit 96d52c5. Nothing in flight — the CSV request was the last completed task.
- **Do NOT start the pending cleanup items without asking.** Each was offered and not accepted: (1) `/opt/odoo/odoo` 1.4 GB dead Community source + `/opt/odoo/venv` 215 MB (~1.6 GB, needs a reference check first), (2) folding the `ee-odoo-bin` wrapper fix into a setup script so an EC2 rebuild doesn't lose it, (3) silver scrape SSL failures against `edahabapp.com`/dahabmasr (a live scrape did succeed at 108.81).
- `remote-deploy.sh` has a real gap: a failure between `systemctl stop odoo` and the `trap … EXIT` leaves prod DOWN. This bit us once (ran the script as `ubuntu`; `/etc/odoo.conf` is `odoo:odoo 640` so an `awk` read failed mid-window, ~30s outage). Moving the trap earlier was offered, not done.
- Deploy rules that keep biting: `-u` MUST carry `-d marjaan` (no `db_name` in prod config → silently upgrades nothing). Report XML is DB-cached — a restart alone will not reload it. Static assets live at `<repo_root>/static/...` while data/views live at `<repo_root>/jewellery_evaluator/...` — two conventions in one manifest.
- Before any push: run `make check` in full. Skipping mypy once let `Returning Any from function declared to return "str"` reach CI (CD was skipped so prod stayed clean; fixed with `totals: dict[str, float]`).
- Adding a Pulse event: use `pulse.notify_in_background(...)` from model code — `max_cron_threads = 1` on this box, so one blocking call stalls EVERY cron including the gold feed the POS floor depends on. Build the key with `make_idempotency_key(model, id, kind)` — never random. Then add the row to `revenax-pulse-notifications.csv` and check the topic against the ops app so the two senders stay disjoint.
- Ops repo is `../marjaan/marjaan-operations-server`. **Its deploy is MANUAL** — `git push` does not ship it; run `vite build` then `vercel deploy --prod`, and that is the owner's call, not ours.
- Prod access: `ssh -i ~/Documents/marjaan-odoo-19.pem ubuntu@odoo.marjaanjewellery.com`; shell via `sudo -u odoo /opt/odoo/ee-odoo-bin shell -c /etc/odoo.conf -d marjaan --no-http < script.py`. Neon `products.odoo_id` = product.TEMPLATE id.
- If Odoo is down: check `df -h /` and `/tmp/chrome-silver-*` FIRST. Box is 3.7 GB RAM with zero swap.
- Server-side installs not in git (re-run if the box is rebuilt): patched-Qt wkhtmltopdf at `/usr/local/bin`, `scripts/install-odoo-watchdog.sh`, the `ee-odoo-bin` wrapper fix, `/etc/logrotate.d/00-size-guard`.
- Long-standing open items awaiting the owner: SMTP credentials, 14 negative bar quants, street/VAT on documents, `DRL8-0096A` (0.00045 ct, likely mis-keyed), `GEF8-0140` (1 stone in Neon, 0 in Odoo), orphan `diamond_rap_pear` param, MJ-1105 credit note `not_paid`.
- Standing user constraints: never run `vercel deploy` unprompted; prefer hard delete + history rewrite over archiving; production is live — tread carefully.

---
---

## Handoff: 2026-10-05T21:17:42Z (auto-saved before compaction)

### Compaction Metadata
- Trigger: auto
- Custom instructions: (none)
- Transcript: /Users/abdallah/.claude/projects/-Users-abdallah-Projects-odoo-gold-pricing-engine/00754a3c-52d9-4e79-b010-2a34c98cd3df.jsonl
- CWD: /Users/abdallah/Projects/odoo-gold-pricing-engine

### Last User Message (transcript tail)
(unavailable)

### Last Assistant Message (transcript tail)
(unavailable)

### Git Snapshot
- Branch: main
- Status:
 M docs/handoff/HANDOFF.md
?? .DS_Store
?? COMMISSION_SALES_BY_EMPLOYEE.xlsx
?? JUNE_LEDGER_VERIFIED.xlsx
?? PHYSICAL_LEDGER/
?? PHYSICAL_LEDGER_TRANSCRIPTION.xlsx
- Recent commits:
399ab1a wire the website shop to the live jewellery catalogue
24a8ccf never merge identical products into one POS line
98568d4 print one invoice row per piece, never a merged quantity
9b16ae4 show the Marjaan logo on the POS screen saver; stop price-cron chatter
138e899 add verified nightly backups and fix log rotation

### Model Summary
- Task: wire the Odoo website backend (engineer restyled it after the Shopify design). Owner said: no COD, free shipping OK. Stop at real blockers such as payment gateways.
- 6f04dbf: the homepage "Featured products" grid is now a dynamic snippet (Newest Products filter, 8 pieces). It uses the card template `jewellery_website.dynamic_filter_template_product_product_featured_card`, which emits the designer's `.product-item` markup. The stock carousel card shows `website_title`.
- 377e289: analytics.
  - GA4 `G-1GP4YDWNEM` uses the native website field. Its ecommerce items carry title, SKU and `complete_name` (overrides `_get_google_analytics_data` and `order_lines_2_google_api`).
  - The new `website.meta_pixel_id` field (Website settings) holds pixel `3903840599865457`. The pixel loads only after cookie consent. `static/src/js/meta_pixel_events.js` forwards view/add-to-cart/checkout/purchase in the capture phase.
  - The Search Console meta tag was added to the custom head.
- 9393ed7: `sale.order.action_confirm` on website orders sends Pulse `web-order-placed` via `cr.postcommit`. The catalogue sync now publishes on FREE stock (quantity − reserved). Also adds `/refund-policy`, created from the Shopify text.
- f780eef: added `docs/website-launch.md` (status, blockers, decisions) and updated the CLAUDE.md website section. `configure_shop.py` gives each pickup warehouse its own contact.
- Server-side (not in git):
  - nginx `proxy_set_header X-Forwarded-Host $host`. Odoo 19 needs it for proxy_mode → https.
  - `web.base.url` set to https, website domain set to https://odoo.marjaanjewellery.com.
  - All configure_shop.py runs applied on prod.
- Verified live:
  - 8 live cards on the homepage, https canonical, GA and pixel tags present.
  - Pixel stays undefined before consent; the bridge maps ViewContent/AddToCart/Purchase (spy test, nothing sent to Meta).
  - Pulse body tested on a rolled-back order.
- Prod has 855 live pieces. 153 in-stock pieces are hidden for lack of photos. 3 pieces are hidden by the stale transfer SM/INT/00010.
- Every deploy was manual (`[skip ci]`): git pull as odoo → stop → `-u jewellery_website` → start. All succeeded with EXIT 0.

### Handoff Context (paste into next session)
1. The website wiring is DONE up to real blockers. Read `docs/website-launch.md` first; it is the source of truth for status and blockers.
2. Blockers that need the owner:
   - payment gateway (delivery checkout can't be paid)
   - SMTP (no emails)
   - pickup store addresses and opening hours
   - company address and VAT
   - photos for 153 pieces
   - privacy and About text (the Shopify privacy policy is a Shopify template, don't copy it)
   - domain cutover
3. Decisions the owner still owes:
   - The POS ignores web reservations, so a piece can be sold twice. Engineering follow-up: block reserved pieces with a manager override.
   - SM/INT/00010: validate or cancel?
   - robots.txt before launch.
   - Website salesperson is currently Administrator.
4. STILL UNANSWERED from earlier: which invoice to hard-delete, MJ-1442 (a real sale, not deleted) or the suspected duplicates MJ-1444/1445 and MJ-1446/1447. Also unanswered: the physical count for the 7 Bug-A phantom pieces.
5. Re-apply website config (idempotent): scp `scripts/website/configure_shop.py` → `/opt/odoo/tmp` → `odoo shell -d marjaan --no-http < file`.
6. Never place test orders on prod. No sale orders exist yet; rolled-back tests consumed S00001/S00002.
7. GitHub Actions has been unreliable. Deploy manually per memory `manual-deploy-fallback.md`, and never block on `gh run watch`.
8. Don't run `vercel deploy`. The ops idempotency commit 4134249 is still undeployed (the owner's call).
9. The S3 backup step still needs the owner to run `aws-setup-cloudshell.sh`.

---
---

## Handoff: 2026-10-30T16:44:49Z (auto-saved before compaction)

### Compaction Metadata
- Trigger: auto
- Custom instructions: (none)
- Transcript: /Users/abdallah/.claude/projects/-Users-abdallah-Projects-odoo-gold-pricing-engine/2aa70210-9618-42ab-bfad-428cd6372b3e.jsonl
- CWD: /Users/abdallah/Projects/odoo-gold-pricing-engine

### Last User Message (transcript tail)
(unavailable)

### Last Assistant Message (transcript tail)
(unavailable)

### Git Snapshot
- Branch: main
- Status:
 M docs/handoff/HANDOFF.md
?? COMMISSION_SALES_BY_EMPLOYEE.xlsx
?? DIAMOND_SALES_BY_SALESMAN.xlsx
?? DIAMOND_SALES_INVOICES/
?? JUNE_LEDGER_VERIFIED.xlsx
?? PHYSICAL_LEDGER/
?? PHYSICAL_LEDGER_TRANSCRIPTION.xlsx
?? UNSOLD_PIECES_CHECK.xlsx
?? photo_cleanup_example.jpg
- Recent commits:
fb829fd fix checkout: hide the Taxes row instead of removing it [skip ci]
6b98a4f shop: drop the Taxes row from cart/checkout, note prices are tax inclusive [skip ci]
3c4853e docs: server tuning after the t3.small downgrade [skip ci]
977b5b5 shop: whole-EGP price on the product page; fix gold service typing [skip ci]
8e2f53f remove Chrome and Selenium: silver comes from the local price feed [skip ci]

### Model Summary
- Unsold check done: UNSOLD_PIECES_CHECK.xlsx (973 in stock, 49 diffs: 47 branch, 1 missing in ops, GEF8-0140 weight).
- Ops app (f303175, on main, NOT deployed): edit/delete requests with admin approve/cancel, audit table change_requests, soft delete, direct DELETE returns 410.
- Only weight and stones are editable; SKU fields are locked. An approved edit re-syncs Odoo and re-queues printing.
- An approved delete calls Odoo retire_jewellery_piece (stock 0 + archive, refused if sold).
- Ops products gain sold/sold_at/sold_ref, written by POST /api/odoo/sold (Bearer ODOO_SOLD_SYNC_TOKEN, already set on Vercel prod).
- Odoo e561e50: jewellery.ops.sold.sync pushes after POS/invoice posts and runs a nightly reconcile; utils.fold_sold_state is tested.
- Odoo params ops_sold_sync_url/token are set in prod.
- Rehearsed on a prod copy: 1623 SKUs, 464 sold, 0 sold-but-on-hand.
- Odoo upgrade is scheduled via systemd timer odoo-upgrade-sold-sync, 2026-10-31 00:00 UTC (log /var/log/odoo-scheduled-upgrade.log).
- The user was pinged; the next step is the user's heavy UI overhaul.

### Handoff Context (paste into next session)
1. Check /var/log/odoo-scheduled-upgrade.log for "upgrade exit 0" and "http 200".
2. Confirm the owner deployed the ops app: f303175 from a clean worktree of origin/main, never the WIP checkout.
3. Verify the backfill: the Neon products sold count should be about 464. If not, run env['jewellery.ops.sold.sync'].cron_reconcile() in the odoo shell.
4. Open question for the user: should the sync also align warehouse/branch for the 47 pieces that differ?
5. Pending: the real weights for GEF8-0140 and DRL8-0102A.
6. Next big task: the UI overhaul of the ops SPA (web/src). The Requests page and RequestForm are minimal placeholders.
7. Rules: never run vercel deploy yourself; don't restart Odoo during Cairo hours; commit with [skip ci] and deploy Odoo manually or with a timer.

---
---

## Handoff: 2026-10-30T18:01:44Z (auto-saved before compaction)

### Compaction Metadata
- Trigger: auto
- Custom instructions: (none)
- Transcript: /Users/abdallah/.claude/projects/-Users-abdallah-Projects-odoo-gold-pricing-engine/2aa70210-9618-42ab-bfad-428cd6372b3e.jsonl
- CWD: /Users/abdallah/Projects/odoo-gold-pricing-engine

### Last User Message (transcript tail)
(unavailable)

### Last Assistant Message (transcript tail)
- **Next:** your UI overhaul.

### Git Snapshot
- Branch: main
- Status:
 M docs/handoff/HANDOFF.md
?? COMMISSION_SALES_BY_EMPLOYEE.xlsx
?? DIAMOND_SALES_BY_SALESMAN.xlsx
?? DIAMOND_SALES_INVOICES/
?? JUNE_LEDGER_VERIFIED.xlsx
?? PHYSICAL_LEDGER/
?? PHYSICAL_LEDGER_TRANSCRIPTION.xlsx
?? UNSOLD_PIECES_CHECK.xlsx
?? photo_cleanup_example.jpg
- Recent commits:
e561e50 ops app sold sync: push sold state on sale/invoice/refund, nightly reconcile; retire_jewellery_piece for approved deletes [skip ci]
fb829fd fix checkout: hide the Taxes row instead of removing it [skip ci]
6b98a4f shop: drop the Taxes row from cart/checkout, note prices are tax inclusive [skip ci]
3c4853e docs: server tuning after the t3.small downgrade [skip ci]
977b5b5 shop: whole-EGP price on the product page; fix gold service typing [skip ci]

### Model Summary
- Unsold check done: 973 in-stock pieces, 49 issues in UNSOLD_PIECES_CHECK.xlsx (47 branch differs, 1 missing in ops, GEF8-0140 weight 4.72 vs 4.52).
- Issues sheet now has "Registered branch (old data)" (ops app) and "Current status in Odoo" (in-stock branch) columns for the 47 branch rows.
- OW was labelled "Owner" as a guess; the user should confirm the real name.
- Ops app f303175 (on main, NOT deployed): sold/sold_at/sold_ref/deleted_at columns, change_requests table, request edit/delete with admin approve/cancel, POST /api/odoo/sold.
- Odoo e561e50 (pushed): jewellery.ops.sold.sync pushes sold state on POS/invoice post, daily reconcile cron, retire_jewellery_piece.
- Odoo upgrade scheduled via the odoo-upgrade-sold-sync timer at 2026-10-31 00:00 UTC; log /var/log/odoo-scheduled-upgrade.log.
- Prod params ops_sold_sync_url and ops_sold_sync_token are set; the same token is on Vercel.
- Branch sync (copy the Odoo branch into the ops app) is NOT built; it is offered to the user.

### Handoff Context (paste into next session)
1. Check whether the owner deployed ops f303175 (never run vercel deploy yourself).
2. After 02:00 Cairo on 2026-10-31, read /var/log/odoo-scheduled-upgrade.log on 44.207.94.139.
3. Then check that about 464 pieces are sold=true in Neon (the cron reconcile, or trigger it manually).
4. Await the user's answers:
   - the real branch name for OW;
   - whether to sync the Odoo branch into the ops app (keep the registered branch as an audit column);
   - the real weights for GEF8-0140 and DRL8-0102A.
5. Next big task: the user's heavy UI overhaul of the ops app (web/ React SPA; commit web/dist).
6. Rules:
   - No Odoo restarts in Cairo opening hours.
   - Commits use [skip ci] and carry no attribution lines.
   - Never put credentials in chat.

---
---

## Handoff: 2026-10-30T23:19:39Z (auto-saved before compaction)

### Compaction Metadata
- Trigger: auto
- Custom instructions: (none)
- Transcript: /Users/abdallah/.claude/projects/-Users-abdallah-Projects-odoo-gold-pricing-engine/7bd8d7f4-0b7a-4799-ac46-2cdd283b58c4.jsonl
- CWD: /Users/abdallah/Projects/odoo-gold-pricing-engine

### Last User Message (transcript tail)
(unavailable)

### Last Assistant Message (transcript tail)
Message me after 02:00 and I'll check the upgrade log and confirm the live balances.

### Git Snapshot
- Branch: main
- Status:
 M docs/handoff/HANDOFF.md
?? ACCOUNTING_WORKSHEET.xlsx
?? COMMISSION_SALES_BY_EMPLOYEE.xlsx
?? DIAMOND_SALES_BY_SALESMAN.xlsx
?? DIAMOND_SALES_INVOICES/
?? JUNE_LEDGER_VERIFIED.xlsx
?? PHYSICAL_LEDGER/
?? PHYSICAL_LEDGER_TRANSCRIPTION.xlsx
?? UNSOLD_PIECES_CHECK.xlsx
?? photo_cleanup_example.jpg
- Recent commits:
190452a Accounting: stones at the market USD rate; historical COGS estimate per month [skip ci]
9646bfd docs: accounting setup (perpetual valuation, scripts, open items) [skip ci]
d31060f Accounting: perpetual valuation at today's metal price, per-material accounts, no taxes, branch Vaults, correcting entries [skip ci]
e561e50 ops app sold sync: push sold state on sale/invoice/refund, nightly reconcile; retire_jewellery_piece for approved deletes [skip ci]
fb829fd fix checkout: hide the Taxes row instead of removing it [skip ci]

### Model Summary
(TODO: fill after compaction — 8–12 bullets)

### Handoff Context (paste into next session)
(TODO: fill after compaction — 10–20 lines of concrete resume instructions)

---
---

## Handoff: 2026-10-31T16:29:53Z (auto-saved before compaction)

### Compaction Metadata
- Trigger: auto
- Custom instructions: (none)
- Transcript: /Users/abdallah/.claude/projects/-Users-abdallah-Projects-odoo-gold-pricing-engine/7bd8d7f4-0b7a-4799-ac46-2cdd283b58c4.jsonl
- CWD: /Users/abdallah/Projects/odoo-gold-pricing-engine

### Last User Message (transcript tail)
(unavailable)

### Last Assistant Message (transcript tail)
- Today's first sale already posted correctly: Sales - Gold 10,900 against its cost of goods sold in the same entry.

### Git Snapshot
- Branch: main
- Status:
 M docs/handoff/HANDOFF.md
?? ACCOUNTING_WORKSHEET.xlsx
?? COMMISSION_SALES_BY_EMPLOYEE.xlsx
?? DIAMOND_SALES_BY_SALESMAN.xlsx
?? DIAMOND_SALES_INVOICES/
?? JUNE_LEDGER_VERIFIED.xlsx
?? PHYSICAL_LEDGER/
?? PHYSICAL_LEDGER_TRANSCRIPTION.xlsx
?? UNSOLD_PIECES_CHECK.xlsx
?? photo_cleanup_example.jpg
- Recent commits:
190452a Accounting: stones at the market USD rate; historical COGS estimate per month [skip ci]
9646bfd docs: accounting setup (perpetual valuation, scripts, open items) [skip ci]
d31060f Accounting: perpetual valuation at today's metal price, per-material accounts, no taxes, branch Vaults, correcting entries [skip ci]
e561e50 ops app sold sync: push sold state on sale/invoice/refund, nightly reconcile; retire_jewellery_piece for approved deletes [skip ci]
fb829fd fix checkout: hide the Taxes row instead of removing it [skip ci]

### Model Summary
- Accounting overhaul: deployed to prod at 2026-10-31 00:00 UTC. Perpetual valuation at today's metal price, no taxes, branch Vaults.
- Chart of accounts tidy-up: commit 1f9dbee, applied to prod 21:55 UTC. Backup taken first: /var/backups/marjaan/pre-coa-20261031-2153.dump.
- Gold Bullion (Bar/Coin/Ingot categories) now has its own accounts: Sales 500106 and COGS 400204. The Gold accounts were renamed Gold Jewellery.
- 118 unused template accounts archived. BNK1 and IFRS journals archived. Account groups added (1 Assets ... 9 Cash Differences).
- Owner accounts recoded to equity: 300101-4 Owner Current Account. Legal Reserve recoded to 300002. 500001 renamed "Sales - Other".
- Reclass entries posted in MISC:
  - Legacy 500001 sales split by material.
  - Bullion split of sales, COGS and the historical estimate.
  - Buy-back bills (278,750) moved from Others to Owners' Capital.
- Prod trial balance totals 0.
- Margins to date:
  - Gold jewellery: 11.54M sales against 10.05M cost.
  - Bullion: 38.82M against 37.74M.
  - Diamond: 2.07M against 1.71M.
- The nightly inventory re-mark cron never ran: its nextcall was set to the next day. Moved it to "now" by hand at 21:54 UTC.
- Rehearsal DB acct_rehearsal and /opt/odoo/tmp/rehearsal dropped.
- The first nightly closing posted a 5.2M phantom revaluation loss.
  - Cause: negative bullion stock (bars sold but never received).
  - Fixed: correcting_entries §9 on prod, plus a nightly `_jewellery_settle_negative_bullion` (02aeef8, deployed).
  - Revaluation is now -152k, the real move.
- 2026-11-01: gold booked by karat, plus making fee (6057a0b). History re-booked.
- Marjaan P&L and Balance Sheet reports built (f470862).
- Server apt-upgraded and rebooted. All services are active.
- Open: session Sway Mall/00018 stays open (40.1M in POS AR). Accountant worksheet items: 6.69M cash-difference loss, Vault at -550k, refunds RINV/00002 and RINV/00004.

### Handoff Context (paste into next session)
1. Read CLAUDE.md, section "Accounting (perpetual valuation...)". It includes the chart tidy notes.
2. Scripts: scripts/accounting/configure_accounting.py (config + chart tidy) and correcting_entries.py (sections 1-8; re-runs post only the difference). Both are idempotent and run as a dry run unless COMMIT=1.
3. To run on prod: scp the script, `sudo install -o odoo` into /opt/odoo/tmp, then `sudo -u odoo env COMMIT=1 bash -c '/opt/odoo/ee-odoo-bin shell -c /etc/odoo.conf -d marjaan --no-http < script'`.
4. Rehearse first on a fresh copy:
   - `createdb acct_rehearsal`, then `pg_dump -Fc marjaan | pg_restore -d acct_rehearsal --no-owner --role=odoo`.
   - prod Odoo is pinned with db_name/dbfilter to marjaan, so the copy is safe.
5. Check that the cron "Jewellery: Re-mark Inventory Cost + Close Stock Valuation" ran:
   - Look for `[costing]` lines in /var/log/odoo/odoo.log.
   - Look for a 500102 Metal Price Revaluation entry.
6. account.group_id is not stored: read it through the ORM, not SQL.
7. Archived accounts are reversible: un-archive one instead of recreating it, because the scripts refuse a code that already exists under another name.
8. Odoo commits carry [skip ci]. Push to main triggers a deploy (CI + -u) unless [skip ci] is set.
9. Pending owner/accountant items: ACCOUNTING_WORKSHEET.xlsx (not in git), the accountant user (email needed), lock dates after the accountant's review.

---
---

## Handoff: 2026-10-31T23:21:48Z (auto-saved before compaction)

### Compaction Metadata
- Trigger: auto
- Custom instructions: (none)
- Transcript: /Users/abdallah/.claude/projects/-Users-abdallah-Projects-odoo-gold-pricing-engine/7bd8d7f4-0b7a-4799-ac46-2cdd283b58c4.jsonl
- CWD: /Users/abdallah/Projects/odoo-gold-pricing-engine

### Last User Message (transcript tail)
(unavailable)

### Last Assistant Message (transcript tail)
- Session 00018 is still open as you asked. It holds the 40.1M of POS sales that show as receivables.

### Git Snapshot
- Branch: main
- Status:
 M docs/handoff/HANDOFF.md
?? ACCOUNTING_WORKSHEET.xlsx
?? COMMISSION_SALES_BY_EMPLOYEE.xlsx
?? DIAMOND_SALES_BY_SALESMAN.xlsx
?? DIAMOND_SALES_INVOICES/
?? JUNE_LEDGER_VERIFIED.xlsx
?? MARJAAN_BALANCE_SHEET_2026-10-31.xlsx
?? MARJAAN_PROFIT_LOSS_Jun-Oct_2026.xlsx
?? PHYSICAL_LEDGER/
?? PHYSICAL_LEDGER_TRANSCRIPTION.xlsx
?? UNSOLD_PIECES_CHECK.xlsx
?? photo_cleanup_example.jpg
- Recent commits:
f470862 Accounting reports: Marjaan Profit & Loss and Balance Sheet [skip ci]
6057a0b Accounting: gold by karat (inventory, metal sales, cost) and a separate making fee
02aeef8 Costing: settle negative bullion stock nightly before the closing
1f9dbee Accounting: chart of accounts tidy-up, gold bullion accounts, legacy sales and buy-back reclass [skip ci]
190452a Accounting: stones at the market USD rate; historical COGS estimate per month [skip ci]

### Model Summary
- Gold booked by karat: stock 132111-3, metal sales 500111-3, COGS 400211-3 (24K/21K/18K); silver 132103/500105/400203; diamond unchanged (132102/500104/400202).
- Making fee split out: 500121 jewellery, 500122 bullion premium, 500123 silver. Fee = revenue minus that day's metal cost (`utils.making_fee_split`), posted as hidden cogs-type lines in `models/karat_accounts.py`.
- `_get_product_accounts` override routes invoices, bills, COGS and the valuation closing to karat accounts.
- Negative bullion quants (bars sold before receipt) zeroed nightly by `_jewellery_settle_negative_bullion`, booked Dr Inventory / Cr 300001; removed a phantom 5.2M revaluation loss.
- History Jun-Oct re-booked by `correcting_entries.py` sections 6-11 (idempotent target-state reclass); 400,581 of free-text-line cost now included.
- Chart tidy-up: 118 unused accounts archived, owner accounts recoded to equity 300101-4, legal reserve 300002, buy-back bills moved to capital, account groups added.
- Reports: "Marjaan Profit & Loss" and "Marjaan Balance Sheet" variants via `scripts/accounting/configure_reports.py`; exported to MARJAAN_*.xlsx (untracked).
- Prod figures Jun-Oct: revenue 52.55M, GP 2.55M, net -4.29M (6.69M cash differences); BS 84.76M both sides; TB = 0, stock = books.
- Server: apt upgrade, vacuumdb, reboot 22:22 UTC 2026-10-31; all services healthy. Commits 1f9dbee, 02aeef8, 6057a0b (deployed), f470862 [skip ci].

### Handoff Context (paste into next session)
- All requested work is DONE and reported to the user; nothing mid-flight.
- Waiting on owner: (1) record bar/coin purchases via ops purchase flow? (2) accountant's email for an Odoo user; (3) accountant to resolve the 6.69M cash-difference worksheet (ACCOUNTING_WORKSHEET.xlsx).
- Other open items: Vault balance -550k, refunds RINV/00002 and RINV/00004, lock dates, session Sway Mall/00018 stays open by owner choice (holds 40.1M POS receivables).
- Expenses: owner will enter vendor bills on 4000xx accounts (rent 400016, salary 400003, utilities 400018); they flow into the P&L "Operating expenses" line automatically.
- Re-run `configure_reports.py` (COMMIT=1, odoo shell on prod) if report lines change; it rebuilds lines idempotently.
- Pre-change DB dumps on the box: /var/backups/marjaan (pre-coa, pre-negbullion, pre-karat).
- Rules: no Odoo restarts during Cairo opening hours; [skip ci] unless a deploy is wanted; no attribution lines; no taxes; never `vercel deploy`.
- This handoff file is uncommitted; commit with [skip ci] when convenient.

---
---

## Handoff: 2026-11-03T14:05:45Z (auto-saved before compaction)

### Compaction Metadata
- Trigger: auto
- Custom instructions: (none)
- Transcript: /Users/abdallah/.claude/projects/-Users-abdallah-Projects-odoo-gold-pricing-engine/7bd8d7f4-0b7a-4799-ac46-2cdd283b58c4.jsonl
- CWD: /Users/abdallah/Projects/odoo-gold-pricing-engine

### Last User Message (transcript tail)
(unavailable)

### Last Assistant Message (transcript tail)
The steps are already written and tested; I've saved them so they aren't forgotten. Tell me when the session is closed.

### Git Snapshot
- Branch: main
- Status:
 M docs/handoff/HANDOFF.md
?? ACCOUNTING_WORKSHEET.xlsx
?? COMMISSION_SALES_BY_EMPLOYEE.xlsx
?? DIAMOND_SALES_BY_SALESMAN.xlsx
?? DIAMOND_SALES_INVOICES/
?? JUNE_LEDGER_VERIFIED.xlsx
?? MARJAAN_BALANCE_SHEET_2026-10-31.xlsx
?? MARJAAN_PROFIT_LOSS_Jun-Oct_2026.xlsx
?? MJ-1550-24740.pdf
?? MJ-1550.pdf
?? PHYSICAL_LEDGER/
?? PHYSICAL_LEDGER_TRANSCRIPTION.xlsx
?? RINV-2026-00006.pdf
?? UNSOLD_PIECES_CHECK.xlsx
?? photo_cleanup_example.jpg
- Recent commits:
d5a5f8d Stock count: clearer admin-approval dialog; camera scan buttons
01ce7c6 Stock count: buzzer on every scan that isn't a clean match
264ae06 Stock count: a piece scanned here that Odoo has elsewhere moves here at once
c63578a CLAUDE.md: SCSS min()/max() mixed-units gotcha [skip ci]
0f86e01 Fix backend CSS build: no min(px, vw) in stock count SCSS

### Model Summary
- Odoo: diamond rate follows eDahab feed (diamond_rate_from_feed True); shop USD = feed ask +2% (usd_markup_pct); USD jump guard 10%.
- 18K purity factor fixed 7/8 -> 6/7 (b423986); history re-booked (correcting_entries §10/§12/§13).
- POS price banner (gold 24/21/18K, silver 999, USD; sell + buy) live.
- Stock count (jewellery_inventory_management): full-width side panel, decisions for missing pieces (lost -> 400071 Inventory Loss, sold w/o invoice -> COGS, other location, keep), admin-badge approval, auto-move of pieces scanned here that Odoo has elsewhere, buzzer, camera scan, simpler start form.
- Stock count scan screen crashed (wrong import of isBarcodeScannerSupported); fix b878dd4 pushed, deploy was in progress at handoff.
- Ops app (separate repo, auto-deploys from main): users table with scrypt hashes (no env), renamed admins, push notifications for requests, barcode scan button, photo edits via requests, request cards show photos.
- MJ-1550: 8,000 refunded by InstaPay; credit note RINV/2026/00006 + payment PIPAY/2026/00123 posted; customer got a 24,740 PDF rendered in a rolled-back transaction.
- Backend CSS broke once from min(px, vw) in SCSS; fixed, documented in CLAUDE.md.

### Handoff Context (paste into next session)
- First: confirm deploy of b878dd4 succeeded (gh run list -L1) and the stock count scan screen opens (no OwlError on isBarcodeScannerSupported).
- Pending: when POS session Sway Mall/00018 closes, reconcile MJ-1550 to a real 24,740 invoice: cancel RINV/2026/00006, reset MJ-1550, price 24,740, re-post, reconcile POSS/2026/11/0005 (32,740) with MJ-1550 (24,740) + PIPAY/2026/00123 (8,000). POS blocks invoice reset while the session is open.
- DBL8-0065 sits in OW/Stock (moved from SM on 14 Sep by user sway, SM/INT/00016); 16 pieces in OW total, owner to verify.
- Ops: owners should change their passwords (old ones are in git history); test push notifications and a real photo-edit approval end to end.
- Rules: Odoo commits [skip ci] unless deploying; deploy restarts Odoo; no attribution lines; never vercel deploy; ops main auto-deploys.
- Before deploying frontend changes: compile web.assets_web in an odoo shell with staged addons; check imports exist in Odoo source (grep ^export).
- MJ-1550*.pdf and RINV-2026-00006.pdf at repo root are untracked deliverables; this handoff file is uncommitted.

---
---

## Handoff: 2026-11-03T15:19:39Z (auto-saved before compaction)

### Compaction Metadata
- Trigger: auto
- Custom instructions: (none)
- Transcript: /Users/abdallah/.claude/projects/-Users-abdallah-Projects-odoo-gold-pricing-engine/7bd8d7f4-0b7a-4799-ac46-2cdd283b58c4.jsonl
- CWD: /Users/abdallah/Projects/odoo-gold-pricing-engine

### Last User Message (transcript tail)
(unavailable)

### Last Assistant Message (transcript tail)
If moved-in pieces will be common, I'd keep Expected fixed at what Odoo had here at the start. Moved-in pieces would get their own **"Moved in"** number and list instead of Found; they'd still move into this location on scan. Say yes and I'll make that change.

### Git Snapshot
- Branch: main
- Status:
 M docs/handoff/HANDOFF.md
?? ACCOUNTING_WORKSHEET.xlsx
?? COMMISSION_SALES_BY_EMPLOYEE.xlsx
?? DIAMOND_SALES_BY_SALESMAN.xlsx
?? DIAMOND_SALES_INVOICES/
?? JUNE_LEDGER_VERIFIED.xlsx
?? MARJAAN_BALANCE_SHEET_2026-10-31.xlsx
?? MARJAAN_PROFIT_LOSS_Jun-Oct_2026.xlsx
?? MJ-1550-24740.pdf
?? MJ-1550.pdf
?? PHYSICAL_LEDGER/
?? PHYSICAL_LEDGER_TRANSCRIPTION.xlsx
?? RINV-2026-00006.pdf
?? UNSOLD_PIECES_CHECK.xlsx
?? photo_cleanup_example.jpg
- Recent commits:
d007318 Full stock count: a warehouse count split into one mini count per prefix
b878dd4 Fix stock count screen crash: import isBarcodeScannerSupported from barcode_video_scanner
d5a5f8d Stock count: clearer admin-approval dialog; camera scan buttons
01ce7c6 Stock count: buzzer on every scan that isn't a clean match
264ae06 Stock count: a piece scanned here that Odoo has elsewhere moves here at once

### Model Summary
- Stock count (Odoo, jewellery_inventory_management): full counts `jewellery.stock.take` split into one mini count per prefix (d007318); old counts migrated into ST/0001-0004.
- Unexpected-scan counters explained: a truly unexpected scan only adds Unexpected +1; a same-prefix piece auto-moved from another location adds Expected +1 and Found +1. Offered a separate "Moved in" counter; no answer yet.
- Ops app: direct photo set `PUT /api/items/:sku/photo` (10af0fa, live on Vercel). Anyone adds a missing photo; an admin replaces one; others replace via an edit request.
- The photo goes to Odoo via `write({image_1920})` only (no reprice, no stock). Each change is logged as an approved change_requests row ("Photo added"/"Photo replaced").
- Inventory has a "No photo" filter (filter.ts PhotoFilter, Toolbar select). The web tests (150) and the build pass.
- Not yet verified: a real photo upload end to end in prod (ops plus the Odoo image).
- The ops work was done in a worktree at scratchpad/ops-photo (branch feat/photo-edit), pushed to ops main. The user's local ops checkout is on feat/admin-product-edit with uncommitted work; it was not touched.
- Open: the MJ-1550 reconcile after POS session Sway Mall/00018 closes; the old open counts SC/0012/0014/0015 (reset or close?); 16 pieces in OW to verify; owners should change their ops passwords; test the push notifications.

### Handoff Context (paste into next session)
1. Ops repo: /Users/abdallah/Projects/marjaan/marjaan-operations-server. Push to main = live on Vercel. Never run `vercel deploy`. Work in a worktree off origin/main.
2. Latest ops commit 10af0fa: the direct photo endpoint is in server.js before "Sold state from Odoo". The UI is in web/src/features/inventory/ItemDetail.tsx (Add/Change photo label), with the useSetPhoto hook in useItemMutations.ts.
3. Ask the user to test: open a piece with no photo, Add photo, then check that the Odoo product image updated.
4. If the user wants moved-in pieces counted separately in the stock count: change process_scan in jewellery_inventory_management/models/jewellery_stock_count.py so that a same-prefix auto-moved piece gets a 'moved_in' status instead of 'found'. Exclude it from expected in `_stats_dict` and add a counter and list in the scanner JS/XML.
5. Odoo deploy: push to main, then GitHub Actions. Use [skip ci] for no deploy. Rehearse on the sc_rehearsal DB copy first (see the earlier handoff entries).
6. MJ-1550: after session 00018 closes, cancel RINV/2026/00006, reset MJ-1550, price 24,740, re-post, then reconcile POSS/2026/11/0005 with PIPAY/2026/00123.
7. No attribution lines in commits. Never take credentials in chat.

---
---

## Handoff: 2026-11-04T13:04:56Z (auto-saved before compaction)

### Compaction Metadata
- Trigger: auto
- Custom instructions: (none)
- Transcript: /Users/abdallah/.claude/projects/-Users-abdallah-Projects-odoo-gold-pricing-engine/7bd8d7f4-0b7a-4799-ac46-2cdd283b58c4.jsonl
- CWD: /Users/abdallah/Projects/odoo-gold-pricing-engine

### Last User Message (transcript tail)
(unavailable)

### Last Assistant Message (transcript tail)
- **Little data:** one session is a thin base. The estimate will be much firmer after 3–4 more days of registering.

### Git Snapshot
- Branch: main
- Status:
 M docs/handoff/HANDOFF.md
?? ACCOUNTING_WORKSHEET.xlsx
?? COMMISSION_SALES_BY_EMPLOYEE.xlsx
?? DIAMOND_SALES_BY_SALESMAN.xlsx
?? DIAMOND_SALES_INVOICES/
?? JUNE_LEDGER_VERIFIED.xlsx
?? MARJAAN_BALANCE_SHEET_2026-10-31.xlsx
?? MARJAAN_PROFIT_LOSS_Jun-Oct_2026.xlsx
?? MJ-1550-24740.pdf
?? MJ-1550.pdf
?? PHYSICAL_LEDGER/
?? PHYSICAL_LEDGER_TRANSCRIPTION.xlsx
?? RINV-2026-00006.pdf
?? UNSOLD_PIECES_CHECK.xlsx
?? photo_cleanup_example.jpg
- Recent commits:
d007318 Full stock count: a warehouse count split into one mini count per prefix
b878dd4 Fix stock count screen crash: import isBarcodeScannerSupported from barcode_video_scanner
d5a5f8d Stock count: clearer admin-approval dialog; camera scan buttons
01ce7c6 Stock count: buzzer on every scan that isn't a clean match
264ae06 Stock count: a piece scanned here that Odoo has elsewhere moves here at once

### Model Summary
- Ops app photo edit: anyone adds/replaces a photo directly (`PUT /api/items/:sku/photo`), logged as an approved change_request; "No photo" inventory filter.
- Deleted 4 test pieces (DBL8-0071, GRL8-0008, GBL1-1000, GBL1-1002) from Neon, Odoo (templates 2576/2580/2581, unlink after available_in_pos=False) and S3.
- IR registration speed report: 56/2500 pieces, ~39/hr for 2 people, ETA ~21 Dec at one evening session/day; recheck after 3-4 more days.
- Ops inventory (commit 4969f6d, live, bundle index-DqCqQkjy.js): list + detail share `ITEM_COLUMNS`/`itemFromRow` in server.js, adding registeredBy/registeredByName (users LEFT JOIN), productType, netGoldWeight, buybackAmount, printed, stocked, createdAt.
- Cards show the registrant; toolbar "Registered by" filter (2+ people only); search matches person.
- Item detail modal: two columns on desktop (photo/barcode | Piece, Registration, Status, stones with total + per-stone carat), header with type/status chips and "Registered by X · date".
- Not visually verified in browser (pane not signed in to ops); tsc, 153 vitest tests and live Neon query OK.
- Staff mohamed-ashraf, abelrazak, ahmed-fathy have username as display name; owner can rename on the Users page.

### Handoff Context (paste into next session)
Ops worktree: /private/tmp/claude-501/-Users-abdallah-Projects-odoo-gold-pricing-engine/7bd8d7f4-0b7a-4799-ac46-2cdd283b58c4/scratchpad/ops-photo (branch feat/photo-edit, has node_modules). Deploy = `git push origin feat/photo-edit:main` (Vercel auto-deploys; never `vercel deploy`). Don't touch the user's local ops checkout (feat/admin-product-edit, uncommitted work).
Neon scripts: process.loadEnvFile(ops .env) + require(process.env.PGMOD) with PGMOD=<worktree>/node_modules/pg.
Odoo shell: ssh -i ~/Documents/Marjaan/marjaan-odoo-19.pem ubuntu@odoo.marjaanjewellery.com; script to /opt/odoo/tmp/x.py; sudo -u odoo bash -c "/opt/odoo/ee-odoo-bin shell -c /etc/odoo.conf -d marjaan --no-http < /opt/odoo/tmp/x.py".
Next: ask the user to eyeball the new item detail on phone + desktop and adjust.
Open items: "Moved in" stock-count counter offer; old open counts SC/0012, 0014, 0015; MJ-1550 reconcile after session Sway Mall/00018 closes (don't close it ourselves); real photo upload end-to-end test; owners change ops passwords + test push; 16 pieces in OW to verify; recheck IR ETA after a few days.

---
---

## Handoff: 2026-11-04T17:42:13Z (auto-saved before compaction)

### Compaction Metadata
- Trigger: auto
- Custom instructions: (none)
- Transcript: /Users/abdallah/.claude/projects/-Users-abdallah-Projects-odoo-gold-pricing-engine/acce6b8a-1513-44c1-962f-2a59e0f3c4ca.jsonl
- CWD: /Users/abdallah/Projects/odoo-gold-pricing-engine

### Last User Message (transcript tail)
(unavailable)

### Last Assistant Message (transcript tail)
**Still open:** DRL8-0072B, sold 11 Sep in MJ-1382 (80,000, together with GNF8-0069) but scanned in the shop. If that sale was also returned, the fix is the same delete. Note that MJ-1382 also contains GNF8-0069, so I need to know whether that one came back too.

### Git Snapshot
- Branch: main
- Status:
 M docs/handoff/HANDOFF.md
?? ACCOUNTING_WORKSHEET.xlsx
?? COMMISSION_SALES_BY_EMPLOYEE.xlsx
?? DIAMOND_SALES_BY_SALESMAN.xlsx
?? DIAMOND_SALES_INVOICES/
?? DUPLICATES_TO_DELETE.jpg
?? JUNE_LEDGER_VERIFIED.xlsx
?? MARJAAN_BALANCE_SHEET_2026-10-31.xlsx
?? MARJAAN_PROFIT_LOSS_Jun-Oct_2026.xlsx
?? MJ-1550-24740.pdf
?? MJ-1550.pdf
?? PHYSICAL_LEDGER/
?? PHYSICAL_LEDGER_TRANSCRIPTION.xlsx
?? RINV-2026-00006.pdf
?? SUSPECTED_DUPLICATES.jpg
?? UNSOLD_PIECES_CHECK.xlsx
?? photo_cleanup_example.jpg
- Recent commits:
b8f380f Stock counts: archive old full counts (and their mini counts)
f13ac6f Full stock count: optional Scan together screen over several mini counts
d007318 Full stock count: a warehouse count split into one mini count per prefix
b878dd4 Fix stock count screen crash: import isBarcodeScannerSupported from barcode_video_scanner
d5a5f8d Stock count: clearer admin-approval dialog; camera scan buttons

### Model Summary
- MJ-1330 hard deleted (POS order 406 in open session Sway Mall/00018, POSS/2026/08/0098, picking WH/POS/00347); GNF8-0045 back on hand at SM, found in SC/0034.
- Delta: sales 500001 -17,300; open-session InstaPay receivable 102012 -17,300. correcting_entries.py re-run would post a small August diff.
- Suspected duplicates reported (SUSPECTED_DUPLICATES.jpg): GNF8-0205 (IR) vs GNF8-0164 (SM, to_find SC/0034) strong; GBF8-0113 (to_find SC/0024) vs sold GBF8-0049 (MJ-1012) weak. Delete only after count + owner OK.
- DRL8-0072B open: sold in MJ-1382 (with GNF8-0069) yet scanned in shop; awaiting owner.
- New diamond shape Cushion: Odoo d263655 (STONE_SHAPE_SELECTION, invoice code C, fancy Rap grid), manually deployed, selection verified in DB.
- Ops e2c552d: Cushion in SHAPE_OPTIONS, ODOO_STONE_SHAPES, scripts; pushed feat/cushion:main (Vercel auto-deploy).
- pytest not installed locally; CI will run tests on the queued Actions deploy.
- Standing: don't close Sway Mall/00018; hard delete only after owner confirms; no vercel deploy by hand.

### Handoff Context (paste into next session)
Repo: /Users/abdallah/Projects/odoo-gold-pricing-engine (main at d263655, deployed manually on prod).
Ops: worktree scratchpad/ops-cushion branch feat/cushion, pushed to ops main (e2c552d).
Odoo shell: ssh -i ~/Documents/Marjaan/marjaan-odoo-19.pem ubuntu@odoo.marjaanjewellery.com; script to /opt/odoo/tmp/x.py; sudo -u odoo [env COMMIT=1] /opt/odoo/ee-odoo-bin shell -c /etc/odoo.conf -d marjaan --no-http < x.py (dry run first).
Manual deploy: git pull as odoo in /opt/odoo/custom-addons/jewellery_evaluator, stop odoo, ee-odoo-bin -u jewellery_evaluator -d marjaan --stop-after-init, start odoo.
Next:
1. Confirm Vercel deployed e2c552d and Cushion appears in registration pills.
2. After GNF8 count (SC/0034) ends: if GNF8-0164 still to_find, propose deleting it (twin GNF8-0205).
3. After GBF8 count (SC/0024): if GBF8-0113 still to_find, propose deleting it.
4. Ask owner about DRL8-0072B / GNF8-0069 return in MJ-1382.
5. Remind owner later about the "Moved in" counter.
6. Owner will split Sway Mall/00018 later; do not close it.

---
---

## Handoff: 2026-11-05T14:06:19Z (auto-saved before compaction)

### Compaction Metadata
- Trigger: auto
- Custom instructions: (none)
- Transcript: /Users/abdallah/.claude/projects/-Users-abdallah-Projects-odoo-gold-pricing-engine/acce6b8a-1513-44c1-962f-2a59e0f3c4ca.jsonl
- CWD: /Users/abdallah/Projects/odoo-gold-pricing-engine

### Last User Message (transcript tail)
(unavailable)

### Last Assistant Message (transcript tail)
I couldn't view it myself because the in-app browser isn't logged in to Odoo. I checked on the server that the stylesheet builds and the new block's markup comes out right. If anything looks off, send a screenshot.

### Git Snapshot
- Branch: main
- Status:
 M docs/handoff/HANDOFF.md
?? ACCOUNTING_WORKSHEET.xlsx
?? COMMISSION_SALES_BY_EMPLOYEE.xlsx
?? DIAMOND_SALES_BY_SALESMAN.xlsx
?? DIAMOND_SALES_INVOICES/
?? DUPLICATES_TO_DELETE.jpg
?? JUNE_LEDGER_VERIFIED.xlsx
?? MARJAAN_BALANCE_SHEET_2026-10-31.xlsx
?? MARJAAN_PROFIT_LOSS_Jun-Oct_2026.xlsx
?? MJ-1550-24740.pdf
?? MJ-1550.pdf
?? PHYSICAL_LEDGER/
?? PHYSICAL_LEDGER_TRANSCRIPTION.xlsx
?? RINV-2026-00006.pdf
?? SUSPECTED_DUPLICATES.jpg
?? UNSOLD_PIECES_CHECK.xlsx
?? photo_cleanup_example.jpg
- Recent commits:
d4ddadb Stock count forms: one summary block (meta line, Found/Missing/Total cards, progress, weight table); drop the Scan together banner
05421c3 Stock counts: Found / Missing / Total everywhere (extras count as found), weight matrix on scan screen and forms
d263655 Stones: add Cushion diamond shape (fancy Rap grid, invoice code C)
b8f380f Stock counts: archive old full counts (and their mini counts)
f13ac6f Full stock count: optional Scan together screen over several mini counts

### Model Summary
- Stock counts: Found/Missing/Total vocabulary everywhere (extras count as Found); weight matrix on scan screen + forms (05421c3).
- Count/full-count forms: one summary_html block (meta line, 3 cards, progress, weights table), Scan together banner removed (d4ddadb, deployed via -u jewellery_inventory_management).
- Cushion diamond shape added in Odoo (d263655) and ops (e2c552d); ops header Restart button (34d9cd3).
- Hard deletes done: DS-0054/55/56, 16 pieces from owner list, MJ-1305 + MJ-1479 sales erased (pieces back on hand, count lines found).
- GEF8-0001: MJ-1105 sale erased in closed session 00016, piece moved to OW/Stock, count line deleted.
- DS-0012 sold 2026-08-31: invoice MJ-1569, 45,000 EGP, customer عماد الشريف (new partner), InstaPay PIPAY/2026/00124 (invoice 'in payment' until bank match).
- DS-0012 cost 52,200 vs sale 45,000 = 7,200 loss booked; flagged to owner, awaiting confirmation.
- DS-0012 count line 2867 removed from SC/0023 (51 found/1 missing/52 total); Neon sold=true.

### Handoff Context (paste into next session)
Prod Odoo shell: scp script to /tmp/x.py, sudo cp to /opt/odoo/tmp/x.py, run
  sudo -u odoo [env COMMIT=1] bash -c "/opt/odoo/ee-odoo-bin shell -c /etc/odoo.conf -d marjaan --no-http < /opt/odoo/tmp/x.py"
  (ssh -i ~/Documents/Marjaan/marjaan-odoo-19.pem ubuntu@odoo.marjaanjewellery.com). Always dry-run first.
Backdated manual sale recipe: create out_invoice (invoice_date+date), action_post (auto-deducts stock),
  account.payment.register with journal (IPAY=15, CSH1=11) + payment_date, then delete/settle count line, Neon sold=true.
Neon: pg installed in scratchpad/neon; process.loadEnvFile(ops .env), DATABASE_URL.
Open items awaiting owner:
- DS-0012 sale price 45,000 below cost 52,200: confirm or give correct amount.
- GBF8-0001 (sold, INV/2026/00017) held back from hard delete.
- DRL8-0072B (MJ-1382), GNF8-0069 decisions; suspected dupes GNF8-0164/GBF8-0113.
- Remind later: 'Moved in' counter on scan screen.
Do NOT close Sway Mall/00018 session. Never vercel deploy by hand. No attribution lines in commits.
correcting_entries.py re-run: deleted/added sales change July/Aug reclass, review before running.

---
---

## Handoff: 2026-11-05T21:24:05Z (auto-saved before compaction)

### Compaction Metadata
- Trigger: auto
- Custom instructions: (none)
- Transcript: /Users/abdallah/.claude/projects/-Users-abdallah-Projects-odoo-gold-pricing-engine/ccb5950c-60df-497a-af67-79cda244afc9.jsonl
- CWD: /Users/abdallah/Projects/odoo-gold-pricing-engine

### Last User Message (transcript tail)
(unavailable)

### Last Assistant Message (transcript tail)
I created it directly in Odoo and the ops database rather than through the app's register screen. It isn't listed in the ops app's registration log, and "registered by" shows ahmed-tarek, copied from the original.

### Git Snapshot
- Branch: main
- Status:
 M docs/handoff/HANDOFF.md
?? ACCOUNTING_WORKSHEET.xlsx
?? COMMISSION_SALES_BY_EMPLOYEE.xlsx
?? DIAMOND_SALES_BY_SALESMAN.xlsx
?? DIAMOND_SALES_INVOICES/
?? DUPLICATES_TO_DELETE.jpg
?? JUNE_LEDGER_VERIFIED.xlsx
?? MARJAAN_BALANCE_SHEET_2026-10-31.xlsx
?? MARJAAN_PROFIT_LOSS_Jun-Oct_2026.xlsx
?? MJ-1550-24740.pdf
?? MJ-1550.pdf
?? PHYSICAL_LEDGER/
?? PHYSICAL_LEDGER_TRANSCRIPTION.xlsx
?? RINV-2026-00006.pdf
?? SUSPECTED_DUPLICATES.jpg
?? SUSPECTED_DUPLICATES_2.jpg
?? UNSOLD_PIECES_CHECK.xlsx
?? photo_cleanup_example.jpg
- Recent commits:
d4ddadb Stock count forms: one summary block (meta line, Found/Missing/Total cards, progress, weight table); drop the Scan together banner
05421c3 Stock counts: Found / Missing / Total everywhere (extras count as found), weight matrix on scan screen and forms
d263655 Stones: add Cushion diamond shape (fancy Rap grid, invoice code C)
b8f380f Stock counts: archive old full counts (and their mini counts)
f13ac6f Full stock count: optional Scan together screen over several mini counts

### Model Summary
- Hard deletes (Odoo + Neon + S3, count lines removed): GBL8-0003, GEF8-0067/68/70/71 dupes, GRL8-0006, GDL8-0002, GNL8-0003, GRF8-0084/0087/0107/0115/0124/0126, GNF8-0078/0122/0125, GCF8-0014, GEF8-0088.
- Empty mini counts deleted (SC/0025,27,30,32,33,35,38); ST/0004 now 16 minis.
- Backdated sales: DS-0012 MJ-1569 (31 Aug, 45k InstaPay, owner confirmed below cost); MJ-1570 (26 Jun, 4 pcs, 55.7k IPAY+cash); MJ-1572 (26 Jun walk-in 58.5k cash); MJ-1573 GRF8-0094 (6 Jul, 25.4k cash, salesman Wael Samir in ref).
- 26 Jun purchase P00031: 5 g SCRAP-GOLD-18K at 22k cash (karat assumed 18K, owner not yet confirmed), moved to OW/Stock.
- 20 uncounted walk-in buy-back pieces moved SM -> OW/Stock (Odoo + Neon warehouse).
- GIF8-0011 created as copy of GIF8-0009 (Odoo id 3120 at OW/Stock, Neon row printed=false).
- Duplicate scan: no byte-identical photos left; GBF8-0130 strong dup of sold GBF8-0131 (not deleted, awaiting owner); sheet SUSPECTED_DUPLICATES_2.jpg.
- Ops: web/dist is committed and NOT built by Vercel; Cushion + Restart button were never live until rebuild 8f37c0b (pushed to ops main).
- DS-0059..0065 (ahmed-tarek, registered at IR by mistake) moved to SM in Odoo + Neon, still in print queue.

### Handoff Context (paste into next session)
Odoo shell: scp script -> /tmp/x.py, sudo cp to /opt/odoo/tmp/x.py, run
  sudo -u odoo [env COMMIT=1] bash -c "/opt/odoo/ee-odoo-bin shell -c /etc/odoo.conf -d marjaan --no-http < /opt/odoo/tmp/x.py"
  (ssh -i ~/Documents/Marjaan/marjaan-odoo-19.pem ubuntu@odoo.marjaanjewellery.com). Dry run first.
Hard delete template: assert no pos/aml/po lines; SQL delete stock_move_line/stock_move/stock_quant; available_in_pos=False;
  unlink count lines + template; delete now-empty in-progress mini counts; then Neon change_requests+products and S3 products/<SKU>.jpg.
Backdated sale: out_invoice with invoice_date/date, action_post (auto stock deduction), account.payment.register (IPAY=15, CSH1=11),
  then SQL-backdate payment move create_date so it stays out of open session Sway Mall/00018's vault window.
Neon helper: pg + @aws-sdk/client-s3 + sharp installed in old scratchpad .../acce6b8a.../scratchpad/neon; loadEnvFile(ops .env).
Ops front-end: any web/src change must rebuild web/dist (cd web && npm ci && npm run build) and commit dist; push to ops main = live.
Open: confirm scrap karat (18K assumed); GBF8-0130 dup?; GBF8-0001 sold piece held; labels possibly still on shelf for GEF8-0067/0068/0088, GRF8-0107/0115;
  remind owner of 'Moved in' counter; never close Sway Mall/00018; no attribution lines in commits.

---

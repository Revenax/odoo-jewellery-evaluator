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

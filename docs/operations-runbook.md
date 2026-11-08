# Marjaan operations runbook

How day-to-day data fixes are done on the live system: who connects to what,
the step-by-step procedures, the rules the owner has set, and a log of every
request handled. Written 2026-11-06. Pair it with `CLAUDE.md` (architecture)
and `docs/handoff/HANDOFF.md` (session hand-offs).

---

## 1. The systems and how they connect

```
 Staff phones / PCs                    Owner / admin
 ┌──────────────────┐                  ┌──────────────────────┐
 │ Ops app (PWA)    │                  │ Odoo backend + POS   │
 │ register pieces, │                  │ odoo.marjaanjewellery│
 │ photos, requests │                  │ .com                 │
 └────────┬─────────┘                  └──────────┬───────────┘
          │ HTTPS                                 │
 ┌────────▼─────────────────┐   XML-RPC  ┌────────▼────────────────────┐
 │ marjaan-operations-server │ ─────────► │ Odoo 19 Enterprise (EC2)    │
 │ Node/Express on Vercel    │ ◄───────── │ DB `marjaan` (Postgres)     │
 │ serves web/dist (React)   │ sold sync  │ modules: jewellery_evaluator│
 └──┬───────────────┬────────┘            │  + inventory_management,    │
    │               │                     │  website, payment_kashier   │
 ┌──▼─────┐   ┌─────▼──────────────────┐  └─────────────────────────────┘
 │ Neon   │   │ S3 marjaan-products-   │
 │ Postgres│  │ photos  products/<SKU> │
 │ products│  │ .jpg                   │
 └────────┘   └────────────────────────┘
          ▲
          │ polls /api/print-queue, acks /api/print-ack
 ┌────────┴────────┐
 │ Label printer   │  prints every row with printed = false
 │ agent (shop PC) │
 └─────────────────┘
```

- **A piece exists in three places:** Neon `products` (the ops app's record),
  Odoo `product.template` (pricing, stock, sales), and its photo in S3
  `products/<SKU>.jpg`. Neon `odoo_id` links to the Odoo template id.
- **Ops → Odoo:** on registration `syncItemToOdoo` creates the template and
  `ensureStock` sets on-hand to 1 at the chosen warehouse (the only inventory
  write the sync ever makes). See CLAUDE.md "Inventory invariant".
- **Odoo → Ops:** Odoo pushes the sold state back (`sold`, `sold_at`, `sold_ref`).
- **Labels:** the print queue is simply Neon rows with `printed = false`; the
  ticket shows SKU, weight and stones, not the branch.

### Connection details (no secrets in this file)

| What | How |
|---|---|
| Odoo server | `ssh -i ~/Documents/Marjaan/marjaan-odoo-19.pem ubuntu@odoo.marjaanjewellery.com` |
| Odoo shell | `sudo -u odoo bash -c "/opt/odoo/ee-odoo-bin shell -c /etc/odoo.conf -d marjaan --no-http < script.py"` (script copied to `/opt/odoo/tmp/` first; the `odoo` user cannot read `/tmp` files of ubuntu reliably) |
| Odoo SQL | `sudo -u postgres psql marjaan` |
| Neon + S3 | credentials in `~/Projects/marjaan/marjaan-operations-server/.env` (`DATABASE_URL`, AWS keys); load with `process.loadEnvFile(...)` |
| Ops app deploy | push to `origin/main` of marjaan-operations-server = live on Vercel. Never `vercel deploy` by hand. |
| Odoo deploy | push to `main` here runs CI then `remote-deploy.sh`; manual fallback in CLAUDE.md |

Warehouses: **SM** Sway Mall (Vault CSH1), **IR** Ismail Ramzy (VIR), **BC** Black
Closet (VBC), **AS** Abbassi Sagha (VAS), **OW** Owners (no vault; holding stock).
Payment journals: **CSH1** Sway Mall Vault (cash), **IPAY** InstaPay (id 15), **CIB** bank.

---

## 2. Ground rules (owner decisions)

1. **Dry run first, always.** Every script rolls back unless `COMMIT=1`.
2. **Hard delete only after the owner names the SKU.** Never on suspicion.
3. **Sold pieces are not hard-deleted** with the normal procedure; their sale
   must be erased first (section 4.6) or the owner must decide.
4. **Never close Sway Mall/00018** (open since 16 Jul); the owner will split it.
5. **No taxes**, anywhere.
6. **Never `vercel deploy` by hand**; never paste credentials in chat.
7. **An empty mini count is deleted** (owner, 2026-11-06).
8. **The physical day book is the source of truth**; past sales are entered
   with their real date (backdated), not today's.
9. Restarting systems is pre-approved when a change needs it.
10. Commits carry no AI attribution lines.

---

## 3. Reusable scripts (`scripts/ops/`)

| Script | Does |
|---|---|
| `run_odoo.sh <script> KEY=VAL...` | copies a script to the server and runs it in the production Odoo shell |
| `hard_delete.py` (`SKUS=A,B`) | deletes pieces + stock history + count lines; deletes counts left empty; refuses pieces with any sale/purchase document |
| `backdated_sale.py` (`SALE=<base64 json>`) | manual invoice on the sale date, payments on the sale date, cash kept out of open shifts, count lines removed |
| `move_pieces.py` (`SKUS=… TO=SM [DROP_COUNT=1]`) | internal move to a warehouse's Stock location |
| `employee_attribution.py` (data block from Neon) | archived Odoo user per employee + re-points piece/PO creation and edit history at them (4.11) |
| `neon.js delete\|sold\|warehouse\|reprint\|show` | the ops-app (Neon) and photo (S3) half of each procedure |

`neon.js` needs `pg` and `@aws-sdk/client-s3`: `npm i pg @aws-sdk/client-s3` in a
scratch folder and run with `NODE_PATH=<that>/node_modules`.

---

## 4. Procedures

### 4.1 Hard delete a piece

Use when the owner says a piece never existed (duplicate registration, test, mistake).

```bash
scripts/ops/run_odoo.sh scripts/ops/hard_delete.py SKUS=GRF8-0124            # read the dry run
scripts/ops/run_odoo.sh scripts/ops/hard_delete.py SKUS=GRF8-0124 COMMIT=1
NODE_PATH=... node scripts/ops/neon.js delete GRF8-0124
```

- Odoo: stock move lines, moves and quants are deleted by SQL (Odoo refuses to
  unlink a product with done moves), then the template; count lines cascade.
- The nightly valuation closing books the stock drop to `500102 Metal Price
  Revaluation`; nothing else to post.
- If the piece was **scanned as found** in an old count, a label with that SKU
  may still be on a real piece: tell the owner (it happened with GEF8-0068,
  GEF8-0088, GRF8-0107, GRF8-0115).

### 4.2 Record a past sale (from the day book)

```bash
SALE=$(printf '%s' '{"date":"2026-06-26","customer":"Mohamed Adel Tawfik",
  "lines":[["GCF8-0024",17519],["GEF8-0036",4690]],
  "payments":[["IPAY",12209],["CSH1",10000]]}' | base64)
scripts/ops/run_odoo.sh scripts/ops/backdated_sale.py SALE=$SALE
scripts/ops/run_odoo.sh scripts/ops/backdated_sale.py SALE=$SALE COMMIT=1
NODE_PATH=... node scripts/ops/neon.js sold GCF8-0024 GEF8-0036
```

- One price for a group of pieces is **split by their list prices** (say so to the owner).
- Customer is found by exact name or created. Walk-in sales use **"Walk-In
  Customer"** (not "Walk-in Customer (Buy-back)", which is the buy-back vendor).
- Salesman without an Odoo user (e.g. Wael Samir, an `hr.employee`) goes in the
  invoice reference `Salesman: <name>`.
- Posting the invoice deducts on-hand automatically (`account_move._post`, the
  cashier-invoice path); COGS and making fee post by karat.
- **Why the create_date backdate:** the Vault sync attributes cash to the open
  POS shift by the move's `create_date`. Cash for a June sale entered today
  would otherwise inflate open shift 00018's expected cash.
- InstaPay payments leave the invoice "in payment" until the bank line is matched.
- Lines in **closed** counts are left as history; open counts lose the line.

### 4.3 Record a past purchase (loose / scrap gold)

Done once by hand (P00031, 5 g at 22,000 cash). Steps:
1. `product.template.create_purchase_receipt([{'sku': 'SCRAP-GOLD-18K', 'qty': grams,
   'price': per_gram}], warehouse_code='SM', origin='LOOSE-GOLD-<date>',
   vendor_ref='jewellery_evaluator.partner_bought_from_customer')`.
2. Backdate by SQL: `purchase_order.date_order/date_approve`, `stock_picking.date_done/scheduled_date`, `stock_move.date`, `stock_move_line.date`.
3. `po.action_create_invoice()`, set `invoice_date`/`date`, post; pay from CSH1 on the
   date via `account.payment.register`; backdate the payment move's `create_date`.
4. Move the scrap quant where it belongs (`move_pieces.py` does not cover scrap
   SKUs; use `stock.quant.move_quants`).

Scrap products are per karat (`SCRAP-GOLD-18K/21K/24K`, qty = grams). Pick the
karat from the owner; if not given, compare the per-gram price with that day's
21K price in `ir_logging` (gold cron messages) and say which was assumed.

### 4.4 Move pieces between branches / to OW

```bash
scripts/ops/run_odoo.sh scripts/ops/move_pieces.py SKUS=DS-0059,DS-0060 TO=SM COMMIT=1
NODE_PATH=... node scripts/ops/neon.js warehouse SM DS-0059 DS-0060
NODE_PATH=... node scripts/ops/neon.js reprint DS-0059 DS-0060     # only if labels are wanted again
```

An internal move has no accounting effect. Add `DROP_COUNT=1` when the piece
leaves the place an open count is checking.

### 4.5 Copy a piece under a new SKU

Used for GIF8-0011 (a second identical piercing of sold GIF8-0009):
1. Odoo: `src.copy({'name': NEW, 'default_code': NEW, 'barcode': NEW,
   'available_in_pos': True, 'is_storable': True})`, copy `stone_ids` if any,
   then `new.init_jewellery_stock('<WH>', 1)`.
2. S3: copy `products/<SRC>.jpg` to `products/<NEW>.jpg`.
3. Neon: `INSERT ... SELECT` from the source row with the new sku, `odoo_id`,
   warehouse, `printed=false`, `sold=false`, `stocked=true`.
4. The gold cron reprices it within a minute.

Next free SKU = highest existing number for the prefix + 1 (check both Neon and Odoo).

### 4.6 Erase a recorded sale (sale was a mistake)

Not scripted; it touches posted accounting. Pattern used for MJ-1305, MJ-1479
(open session) and MJ-1105 (closed session):
- unreconcile; delete the POS order's picking moves, payments, lines and order
  by SQL; `button_draft` + unlink the invoice and payment entries;
- `init_jewellery_stock(wh, 1)` to put the piece back; count line to found; Neon `sold=false`;
- for a **closed** session also fix the session closing entry and the CSH1
  statement lines (`check_move_validity=False`, `skip_account_move_synchronization=True`)
  and re-reconcile.

### 4.7 Stock-count fixes

- **"Remove from the count as if never scanned":** delete the extra lines, set
  expected lines back to `to_find`.
- **Empty mini count:** delete it (rule 7); then `take._check_done()`.
- Counts read **Found / Missing / Total**; an extra scan counts as Found.
- Full count ST/0004 closes itself when its last mini count is approved.

### 4.8 Find duplicate registrations

1. **Identical photo bytes:** list S3 objects, group by ETag + size. Strongest signal.
2. **Same specs:** group Neon rows by type, category, karat, weight, net gold, stones.
   Plain gold at common weights collides a lot, so this alone proves nothing.
3. **Photo look-alike:** 8x8 difference hash of each photo inside a spec group
   (sharp). Too coarse alone: real twins and same-design pieces score alike.
4. **Count evidence:** a piece Missing while its twin was **sold** is the classic
   duplicate (the sale took the real piece, the double stayed in stock).
5. Check Odoo history before calling it a phantom: GBF8-0130 looked like a
   double of sold GBF8-0131 but was itself sold (MJ-1067) and returned
   (RINV/2026/00003), so it is a real piece.
6. Build a side-by-side photo sheet and let the owner decide.

### 4.9 Ops app front-end change

`web/dist` is **committed** and served as-is; Vercel does not build it.
Edit `web/src`, then `cd web && npm ci && npm run build`, check with
`grep -l "<new text>" web/dist/assets/*.js`, commit `web/dist` with the change,
push to `main`. (Cushion and the Restart button sat unshipped for two days
because this step was missed; fixed in ops `8f37c0b`.)

### 4.10 Adding a diamond shape

Odoo: `STONE_SHAPE_SELECTION` (jewellery_stone.py) + `STONE_SHAPE_CODES`
(utils.py) + `tests/test_invoice_format.py`; non-Round shapes use the fancy Rap
grid automatically. Ops: `server.js` shape list, `web/src/features/register/types.ts`
`SHAPE_OPTIONS`, the scripts' shape lists, then rebuild `web/dist` (4.9).

### 4.11 Who created / edited a piece (employee attribution)

The ops app syncs to Odoo as ONE user (id 2), so Odoo used to show that user as the
creator of every piece and buy-back PO. Every employee now has an **archived** Odoo
user (cannot log in, takes no seat; login `first.last@marjaanjewellery.com`, its own
archived contact, so the employee's work contact stays active). `hr.employee.user_id`
was set by SQL so hr does not swap the work contact/photo. Archived users do not
change the POS: orders keep the session user, manager rights come from the
register's advanced-employee list.

`employee_attribution.py` takes the truth from Neon: `products.registered_by`
→ creator, approved `edit` change_requests → editor (the requester). It sets
`create_uid` on product.template/product.product/jewellery.stone, the "created"
chatter note + creation-sync tracking (≤10 min), buy-back POs (origin = SKU:
create/write uid + Buyer + chatter), and tracking within 5 min of an edit approval
+ `write_uid`. Bulk re-syncs (13/15/25 Jun) stay on the sync user. Ops username →
employee map is `OPS_TO_EMP` in the script; add new staff there. Re-runnable
(only touches rows still on the sync user). Regenerate the data block: dump
`{reg: {sku: registered_by}, edits: [[sku, requested_by, decided_at]]}` from Neon
and substitute `__ATTRIB__`. Pieces registered after a run show the sync user
again until the next run (or until the sync passes the registrant).

**Live attribution (since 2026-11-08, Odoo `product_template_actor.py` + ops 11578d1):**
the ops server passes `context={'jewellery_actor': <ops login>}` on every Odoo call
it makes for a person: the registrant on create (+ stock init / buy-back PO), the
requester on an approved edit, the uploader on a photo change. Odoo maps the login
through `res.users.jewellery_ops_login` (shown on the user form under the phone)
and, just before that call commits, re-stamps only the rows/chatter stamped with
the sync user in THAT transaction. Reconcile and admin re-syncs pass no actor.
Unknown login = no-op. **New staff:** create the Odoo user (archive it), put their
ops username in "Operations app login"; nothing else. Users are ids 19–29
(employees 3–13); user 2 = mohamed-a-abdallah.

---

## 5. Request log (2026-11-04 to 2026-11-06)

| Request | Result |
|---|---|
| Add Cushion diamond shape | Odoo d263655 (fancy grid, invoice code C); ops e2c552d, live only after dist rebuild 8f37c0b |
| Restart button in ops header | ops 34d9cd3, live with 8f37c0b |
| Stock counts: precise Found / Missing, extras count as found, weight matrix, one vocabulary | 05421c3 |
| Remove the Scan-together banner, refine count forms | d4ddadb (one summary block) |
| Hard delete DS-0054, DS-0055, DS-0056 | done, removed from SC/0023 |
| Erase sales MJ-1305, MJ-1479 | pieces back on hand at SM, lines found |
| 19 SKUs "added by mistake" to counts | 13 extra lines deleted, 3 reset to missing |
| Hard delete 16 pieces (GBF8/GNF8/GRF8 list) | done; GBF8-0001 kept (sold, INV/2026/00017) |
| GEF8-0001: erase sale, move to OW, off count | MJ-1105 erased in closed session 00016 |
| What is IR up to | 290 pieces, ~33/hr as a team |
| Sell DS-0012 31 Aug, 45,000 InstaPay, عماد الشريف | MJ-1569; below cost 52,200, owner confirmed |
| Hard delete GBL8-0003 | done |
| Hard delete GEF8-0071, GEF8-0068, GEF8-0070 (duplicates of 0067/0070) | done; dup scan run, sheet `SUSPECTED_DUPLICATES_2.jpg` |
| Sale 26 Jun, 4 pieces, Mohamed Adel Tawfik, 28,700 IPAY + 27,000 cash | MJ-1570 |
| Sale 26 Jun, 3 pieces, walk-in, 58,500 cash | MJ-1572 |
| Purchase 26 Jun, 5 g loose gold, 22,000 cash, to OW | P00031, SCRAP-GOLD-18K (karat assumed) |
| Walk-in purchases not counted → OW | 20 pieces moved SM → OW |
| Delete empty mini counts | SC/0025, 0027, 0030, 0032, 0033 (later 0035, 0038) |
| Hard delete GRL8-0006, GDL8-0002, GNL8-0003, GRF8-0084, GRF8-0087, GRF8-0124, GNF8-0122, GNF8-0125, GRF8-0107, GRF8-0126, GRF8-0115, GNF8-0078, GCF8-0014, GEF8-0088 | done |
| Sale 6 Jul GRF8-0094, sara elmkawy, 25,400 cash, salesman Wael Samir | MJ-1573 |
| One more GIF8-0009 under a new code, to OW | GIF8-0011 (Odoo 3120) |
| Cushion missing in ops app | dist rebuilt, 8f37c0b |
| Add Triangle diamond shape (2026-11-07) | Odoo caa688b (fancy grid, invoice code T); ops cd76baa (lists + dist rebuilt) |
| Archived Odoo account per employee; history points at them (2026-11-08) | users 19–29; 2,142 pieces (+7 on re-run), 199 stones, 2,146 creation notes, 21 buy-back POs (+42 notes), 15 edited pieces re-attributed |
| Sync sends the real creator from now on | Odoo 61251ad + ops 11578d1; ziad-zaza = Ziad Mohamed |
| ahmed-tarek pieces registered at IR by mistake → SM, reprint | DS-0059 … DS-0065 moved; already printed since |
| Hard delete GEF8-0034; copy sold GEF8-0139 at 1.06 g to OW (2026-11-08) | GEF8-0034 gone (off SC/0011, SC/0031); GEF8-0228 (Odoo 3578) in OW/Stock, 6,600, label queued |

## 6. Open items

- **Scrap karat** for P00031: booked 18K (4,400/g vs 21K 5,745/g that day); owner to confirm.
- **Labels possibly on the shelf** for deleted or sold SKUs that had been scanned
  as found: GEF8-0067, GEF8-0068, GEF8-0088, GRF8-0107, GRF8-0115.
- **GBF8-0001** (sold, INV/2026/00017): owner to decide.
- **GBF8-0113**: missing in SC/0024, photo does not match GBF8-0105; likely lost, not a duplicate.
- **IR count** not started; same-design pairs there (e.g. GRL8-0113/0115) settle at count time.
- Remind the owner about the "Moved in" counter on the scan screen.
- `correcting_entries.py` re-runs would now see the added/erased sales; review before running.

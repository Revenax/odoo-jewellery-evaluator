# POS Gift Invoice

**Date:** 2026-07-19
**Status:** approved design → implementation
**Scope:** `jewellery_evaluator` — gift-invoice report variant + POS receipt-screen button + backend Print binding.

## Problem

After a completed POS sale the cashier wants to print a **gift invoice**: the same
branded gold invoice, but with **prices removed** (Value column + Total), so the
piece can be gifted with its authenticity/spec details but not the price.

Every POS order is already invoiced (`pos.order._process_saved_order` forces
`to_invoice`), so the gift invoice always renders from the order's `account.move`.

## Decisions (from brainstorming)

1. Hide **prices only** — the **Value** column and **Total Amount**. Keep SKU,
   Description, Karat, Weight, customer, date, QR footer.
2. Format: the **same gold invoice**, exactly like the regular one (same document
   template + paper format), prices stripped. Prints via the browser PDF dialog.
3. Available on the **POS receipt screen** (post-payment) **and** the **backend**
   invoice (Print ▾ menu).

## A. Report — one `gift` flag

In `report_invoice_document_gold` (the gold layout, inherits
`account.report_invoice_document`), derive a flag from the report `data` and hide
the price elements when set:

```xml
<t t-set="jew_gift" t-value="bool(data and data.get('gift'))"/>
```

Wrap in `t-if="not jew_gift"`:
- the **Value** `<th name="th_subtotal">` and `<td name="td_subtotal">`,
- each **stone row's trailing (Value) `<td/>`**,
- the **Total Amount** block.

Normal render → `data` has no `gift` → prices shown (unchanged). Gift render →
prices hidden. Column count drops 5 → 4 uniformly (header, product cells, stone
rows), so the table stays aligned.

## B. Gift report action + wrapper template

A thin wrapper forces the flag so both the backend binding and the POS controller
share one code path:

```xml
<template id="report_gift_invoice">
  <t t-set="data" t-value="{'gift': True}"/>
  <t t-call="account.report_invoice"/>
</template>

<record id="action_report_gift_invoice" model="ir.actions.report">
  <field name="name">Gift Invoice</field>
  <field name="model">account.move</field>
  <field name="report_type">qweb-pdf</field>
  <field name="report_name">jewellery_evaluator.report_gift_invoice</field>
  <field name="report_file">jewellery_evaluator.report_gift_invoice</field>
  <field name="binding_model_id" ref="account.model_account_move"/>
  <field name="binding_type">report</field>
  <field name="print_report_name">'Gift Invoice - %s' % (object.name or '').replace('/', '_')</field>
</record>
```

`t-set data` shadows the engine's `data` for the called templates, so the gold
document reads `{'gift': True}`. (Verified read-only before deploy — see F.)

## C. POS receipt-screen button

- **Controller** `controllers/gift_invoice.py`:
  `GET /jewellery/gift_invoice/<int:order_id>` (`type='http'`, `auth='user'`).
  Resolve `pos.order(order_id)`, check it is in the user's allowed companies,
  take `order.account_move`; 404 if missing. Render
  `jewellery_evaluator.report_gift_invoice` for that move (`sudo` for rendering)
  → return the PDF **inline** (`Content-Type: application/pdf`).
- **Frontend** `static/src/js/pos_gift_invoice.js` + `.xml`: patch the core
  **ReceiptScreen**, add a **"Print Gift Invoice"** button in the button row that
  does `window.open('/jewellery/gift_invoice/' + this.currentOrder.id)` → the
  browser's print dialog. Registered in `point_of_sale._assets_pos`.

## D. Backend binding

The `action_report_gift_invoice` binding on `account.move` adds **Print ▾ → Gift
Invoice** on any invoice form/list — the reprint-later path.

## E. Wiring

- New `controllers/__init__.py` + `jewellery_evaluator/__init__.py` imports
  `controllers`.
- `__manifest__.py`: add `report/report_gift_invoice.xml` to `data`; add the JS +
  XML to the `point_of_sale._assets_pos` assets.

## F. Validation & deploy (proven no-downtime pattern)

- **Read-only on prod first:** in a SAVEPOINT, render a real posted invoice **both**
  ways — normal `account.account_invoices` (assert the Value/Total/EGP still
  present) and `report_gift_invoice` (assert Value column header, Total, and the
  price numbers are **gone**, but SKU/Karat/Weight still present) — then ROLLBACK.
  This confirms the `data` flag propagates into the gold document before any
  deploy.
- Report XML + controller + POS asset → **needs `-u` + ~15–30s restart**. The POS
  ReceiptScreen `t-inherit` xpath is validated at `-u`; reproduce its combine
  read-only first (same method used for the invoice redesign). Deploy in a quiet
  window; re-verify live (backend Print binding + the controller route).

## Out of scope

- No change to prices, totals maths, or the normal invoice.
- No separate gift paper format (reuses the regular one).
- No thermal-receipt gift variant.

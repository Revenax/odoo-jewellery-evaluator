# Sale markup analytics — design

**Date:** 2026-07-28
**Status:** approved (design), pending implementation
**Goal:** every sold line carries a frozen, hidden `markup` value so profit can be analysed after the fact.

## Problem

A jewellery product's price has three layers: the metal/stone **cost**, the **minimum sale price**
(the POS floor), and the **sale price**. Today none of that is preserved on the sale itself — only
the amount charged.

The gold base price is refetched **every 10 minutes** and `fallback_price` is overwritten in place;
there is no price history. So the moment a sale completes, the cost basis behind it becomes
**permanently unrecoverable**. Profit per sale is therefore not computable retroactively — it must
be captured at the instant of sale or it is lost.

## Decision

Stamp two frozen floats on each sold line at the moment the sale becomes real:

| Field | Meaning |
|---|---|
| `jewellery_markup` | revenue − cost basis (profit over intrinsic value, in EGP) |
| `jewellery_cost_basis` | the cost actually used, so any markup is auditable later |

Both are **stored, readonly, and absent from every view** (hidden — analytics only).

### Formula

```
cost_basis = unit_cost × quantity
markup     = price_subtotal − cost_basis
```

- **revenue = `price_subtotal`** — untaxed and *after* discount. That is the money actually earned.
- **quantity is signed**, so a refund/return line (`qty < 0`) yields a negative markup and correctly
  reverses the original profit. No special-casing.

### Cost basis by material

Read from the product at stamp time:

| `jewellery_type` | Unit cost |
|---|---|
| `gold_local`, `gold_foreign`, `gold_bars` | `gold_cost_price` (EGP) |
| `silver` | `silver_cost_price` (EGP) |
| `diamond_jewellery`, `center_stone` | (`diamond_total_gold_cost_usd` + `diamond_total_stones_cost_usd`) × exchange rate |
| anything else (non-jewellery) | not applicable — short-circuits, see below |

**Non-jewellery lines short-circuit before the formula.** A product with no `jewellery_type` has no
cost basis, so applying `markup = revenue − 0` would record the entire sale amount as profit and
inflate every aggregate. Instead both fields are stamped `0` directly and the formula is skipped.

Diamond costs are stored only in USD, so they are converted using the exchange rate in effect at
stamp time, read via the existing `product.template._diamond_pricing_config()`
(`jewellery_evaluator.diamond_exchange_rate_usd`).

## The core constraint: write-once

`jewellery_markup` **must not** be an `@api.depends` computed field on product cost.

Gold reprices every 10 minutes. A reactive field would silently rewrite last month's profit on every
cron tick, and the analytics would be fiction. The value is computed once, at the point of sale, and
never recomputed.

### Stamp points

| Channel | Hook | Why here |
|---|---|---|
| POS | `pos.order.line.create()` (model already inherited, `pos_order.py:544`) | POS lines are created already-final; a single choke point covering the UI and backend-created lines |
| Invoice | `account.move._post()` (already overridden, `account_move.py:41`) | A draft invoice can still be edited; posting is when the sale becomes real |

Order-level rollups (`pos.order`, `account.move`) are **stored sums of their lines** — safe to
compute reactively, because they depend on the frozen line values, not on live product cost.

## Architecture

Per the repo convention (CLAUDE.md): arithmetic lives in `utils.py` as a pure, unit-tested function;
the Odoo models stay thin.

```
utils.py
  compute_line_markup(revenue, unit_cost, quantity) -> {markup, cost_basis}
    Decimal arithmetic, ROUND_HALF_UP, quantised to 2 dp (EGP piastres).
    Pure — no Odoo imports. mypy-checked, covered by tests/.

models/product_template.py
  jewellery_unit_cost_egp() -> float
    Resolves the per-material cost above, incl. the USD->EGP conversion.
    Single source of truth, reused by both stamp points.

models/pos_order.py       PosOrderLine.create()   -> stamps both fields
models/account_move.py    AccountMove._post()     -> stamps both fields on its lines
```

## Edge cases

- **Non-jewellery line** → both fields stamped `0` via the short-circuit above (never
  `revenue − 0`). Because cost basis is stored alongside, "not applicable" (`cost_basis == 0`)
  stays distinguishable from a genuine zero-margin jewellery sale (`cost_basis > 0`).
- **Jewellery product with zero cost** (gold source misconfigured → base price 0) would produce a
  markup equal to full revenue. Such a product also prices at 0 and so cannot be sold at a real
  price; `cost_basis == 0` on a jewellery line is the signal that this happened.
- **Re-post of an invoice** must not re-stamp. Reuse the existing idempotency pattern
  (`jewellery_stock_deducted`-style guard) so values are written once.
- **POS refund** — negative qty flows through the same formula; no separate path.

## Explicitly out of scope

- **No backfill.** Historical sales keep `0`/unset. The cost basis of a past sale is unrecoverable
  (no gold price history), and stamping today's gold price onto old orders would manufacture
  confidently wrong numbers. Analytics begins at deploy.
- No UI surface, report, or dashboard. Fields are hidden; analysis happens through Odoo's existing
  pivot/list reporting over the stored values.
- Markup vs the *minimum* sale price (discount-discipline analytics) is not stored. Only profit over
  cost, per decision.

## Testing

- `tests/test_markup.py` (pytest, no Odoo) covering `compute_line_markup`: positive markup, zero
  markup, negative (refund), zero cost basis, quantity > 1, Decimal rounding at 2 dp.
- The existing Odoo-side suite is unaffected; the new fields are additive.

## Deployment

Adding stored fields requires a module upgrade — the standard push-to-`main` CD path already runs
`-u jewellery_evaluator -d marjaan`, so no manual step. Additive and reversible: the fields default
to 0 and nothing reads them yet.

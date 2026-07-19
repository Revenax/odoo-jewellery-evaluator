# POS Jewellery Details

**Date:** 2026-07-19
**Status:** approved design → implementation
**Scope:** `jewellery_evaluator` — enrich the POS product-info popup with jewellery details + a dedicated button.

## Problem

Cashiers want to see a piece's **jewellery details — weight and stones** — from the
POS. Odoo POS already has a **ProductInfoPopup** (opened by the core **Info**
control button on the selected line + **long-press** on a product) fed by
`product.template.get_product_info_pos` — but it shows only price/stock/margins,
no jewellery data.

## Decisions (from brainstorming)

1. **Both** entry points: enrich the existing popup **and** add a dedicated
   button — both open the **same** enhanced popup (one RPC, least code).
2. Stones: **full per-stone table** — carat · quantity · shape · color · clarity.
3. Also show: **weight breakdown**, **karat/purity**, **SKU + category**.
   **No pricing** (customer-safe — cost/min excluded).
4. Online-only (RPC), same as the core Info popup.

## 1. Backend — extend `get_product_info_pos`

`models/pos_product_info.py` inherits `product.template` and appends a
`jewellery` block to the dict (the method exists to be overridden — core says so):

```python
info = super().get_product_info_pos(price, quantity, pos_config_id, product_variant_id)
info['jewellery'] = self._jewellery_pos_info()
return info
```

`_jewellery_pos_info()` returns, for a jewellery piece:

```
{
  is_jewellery: True,
  sku:      default_code or '',
  category: categ_id.complete_name        # "Gold / Bracelet"
  type:     <jewellery_type label>,
  purity:   <gold_purity or silver_purity label>,   # "18K" / "999"
  weights:  gold/silver → [{'label': 'Weight', 'value': '12.5 g'}]
            diamond     → [{'label':'Gold','value':'2.7 g'},
                           {'label':'Stones','value':'0.2 g'},
                           {'label':'Gross','value':'2.93 g'}],
  stones:   [{'carat':'0.024','quantity':15,'shape':'Round',
              'color':'G','clarity':'VS1'}, ...],   # diamond only
}
```

- Weights formatted with the existing `format_weight_g` util; carats with
  `format_carat`. Diamond weights use `net_gold_weight_g` / `diamond_weight_g` /
  `gross_jewellery_weight_g`; gold/silver use `jewellery_weight_g`
  (fallback `gold_weight_g`).
- Selection labels (jewellery_type, purity, shape, color, clarity) resolved via
  each field's selection mapping so the popup shows human text.
- Non-jewellery product → `{'is_jewellery': False}` (section hides).

## 2. Frontend — one XML asset, no JS

`static/src/xml/pos_product_info.xml` with two `t-inherit` extensions:

- **`point_of_sale.ProductInfoPopup`** — insert a **"Jewellery Details"** section
  at the top (before `section-public-description`), shown when
  `props.info.productInfo.jewellery?.is_jewellery`: SKU · category · type · purity, the
  weight rows, and a per-stone `<table>` (carat · qty · shape · color · clarity).
- **`point_of_sale.ControlButtons`** — add a **"Details"** button (gem icon)
  after the core Info button, shown when a line is selected
  (`currentOrder?.getSelectedOrderline()`), calling the existing
  `this.pos.onProductInfoClick(line.product_id.product_tmpl_id, line.product_id)`.

No new JS: the button reuses the store's `onProductInfoClick`; the popup section
just renders strings from `props.info.productInfo.jewellery` (the RPC dict is
nested at `info.productInfo`, confirmed against the core template).

## 3. Validation & deploy

- **Read-only on prod:** call `get_product_info_pos` for a **diamond** and a
  **gold** product; assert the `jewellery` block (weights, purity, SKU, category,
  per-stone rows) — no writes.
- **Owl xpaths aren't `-u`-validated** (client-side inheritance). Validate both
  (`ProductInfoPopup`, `ControlButtons`) with **lxml against the core template
  files** on the box (venv python), asserting each anchor matches exactly 1.
- `-u` deploy (backend model + POS asset), verify live; the popup loads on a POS
  **browser refresh**.

## Wiring

- `models/__init__.py` imports `pos_product_info` (sorted — ruff I001).
- `__manifest__.py`: add `static/src/xml/pos_product_info.xml` to
  `point_of_sale._assets_pos`.

## Out of scope

- No pricing/cost in the popup. No offline preloading (RPC-only, like core Info).
- No change to the invoice, cash-ops, or gift invoice.

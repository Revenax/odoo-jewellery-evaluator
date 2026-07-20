# Diamond Rap Pricing

**Date:** 2026-07-20
**Status:** approved design → implementation
**Scope:** `jewellery_evaluator` — Rapaport-grid stone pricing for stones ≥ 0.25 ct, an editable PDF-style Rap page in Settings, and a single stone-price function.

## Problem

Diamond stones are priced by 5 flat carat tiers (`get_stone_tier_price`, USD/ct ×
carat). Coarse for larger stones. Use the **Rapaport price list** (per
colour/clarity/carat) for stones **≥ 0.25 ct**; keep the 5 tiers for **< 0.25 ct**.
Prices must be **editable in a PDF-style grid** in Settings.

## Decisions (from brainstorming)

1. `< 0.25 ct` → 5 tiers (unchanged). `≥ 0.25 ct` → Rap. 0.25 itself = Rap.
2. Grid holds **Rap LIST**; a configurable **`Rap discount %`** is applied at
   lookup (`× (1 − pct)`), default **0**.
3. **Two grids: Round + Pear.** `Round` shape → Round grid; `Pear` → Pear grid;
   **all other shapes → Round grid**.
4. Settings: a **custom PDF-style grid editor** (click-to-edit cells).
5. Missing/blank cell → fall back to the 5-tier price (never zero-price a stone).

## Data shape

The report mixes two table formats; both are stored natively:

- **`0.23-0.29`** (covers 0.25–0.29): **grouped** — rows `DF, GH, IJ, KL, MN`;
  cols `IF-VVS, VS, SI1, SI2, SI3, I1, I2, I3`.
- **`0.30-0.39` … `10.00-10.99`**: **full** — rows `D…M`; cols
  `IF, VVS1, VVS2, VS1, VS2, SI1, SI2, SI3, I1, I2, I3`.

Buckets (≥ 0.25): `0.23-0.29, 0.30-0.39, 0.40-0.49, 0.50-0.69, 0.70-0.89,
0.90-0.99, 1.00-1.49, 1.50-1.99, 2.00-2.99, 3.00-3.99, 4.00-4.99, 5.00-5.99,
10.00-10.99`. A stone of 6.00–9.99 ct → `5.00-5.99` bucket; ≥ 11 → `10.00-10.99`.

**Cell value = the PDF number (hundreds USD/ct)** — e.g. `54` = $5,400/ct. Editing
matches the sheet 1:1.

## Stone → Rap axis mapping

| Stone | Rap col |
|---|---|
| `LC` | `IF` |
| `VVS1 VVS2 VS1 VS2 SI1 SI2` | same |
| `P1 P2 P3` | `I1 I2 I3` |
| (no stone SI3) | SI3 col only used if a stone ever has it |

Grouped bucket collapses: `IF/VVS*`→`IF-VVS`, `VS*`→`VS`, `SI1`→`SI1`, `SI2`→`SI2`,
`SI3`→`SI3`, `I1/I2/I3`→`I1/I2/I3`; colour `D/E/F`→`DF`, `G/H`→`GH`, `I/J`→`IJ`,
`K/L`→`KL`, `M/N`→`MN`. Full bucket: colour `N`→`M` row.

## A. Storage

Two `ir.config_parameter` JSONs: `jewellery_evaluator.diamond_rap_round` and
`…diamond_rap_pear`. Each `{ bucket: { rowKey: { colKey: number } } }`. Seeded from
the March-2026 report via a data file; the editor overwrites them. One config
field `jewellery_evaluator.diamond_rap_discount_pct` (Float, default 0).

## B. Pricing function (`utils.py`, pure + unit-tested)

```
get_stone_price_usd(env, shape, carat, colour, clarity) -> float
    carat < 0.25  -> get_stone_tier_price(env, carat)
    carat >= 0.25 -> rap_stone_price_usd(...)  (falls back to tier if no cell)

rap_stone_price_usd(env, shape, carat, colour, clarity) -> float
    sheet   = 'pear' if shape == 'Pear' else 'round'
    bucket  = bucket_for_carat(carat)
    row,col = rap_keys(bucket, colour, clarity)     # grouped vs full
    cell    = grid[sheet][bucket][row][col]         # missing -> None
    return cell * 100 * carat * (1 - discount_pct)  # None -> tier fallback
```

Helpers (`bucket_for_carat`, `rap_keys`, colour/clarity collapse) are pure and
tested. Grid JSON parsed from config (cached per call is fine).

## C. Settings — PDF-style grid editor

A dedicated menu **Diamond Rap Prices** (under the jewellery settings area) →
OWL client component:
- **Round / Pear** tabs.
- One `<table>` per bucket in its native format (grouped small, full large),
  colour rows × clarity columns, each cell an editable number input.
- **Save** → writes the JSON back via a `@api.model` method
  (`diamond.rap.price.save(sheet, data)`); **Reload** re-reads.
- `Rap discount %` shown/edited here too.
- Backed by `res.config.settings`-adjacent model methods
  `diamond_rap_get()` / `diamond_rap_set()` for read/write (server-side validated:
  numbers only, known buckets/keys).

## D. Integrate

`compute_diamond_jewellery_price` (utils) currently sums `get_stone_tier_price(env,
carat)` per stone. Change the caller (`product_template` diamond compute) to pass
each stone's `shape/carat/colour/clarity` into `get_stone_price_usd`. Signature of
the diamond compute grows a per-stone list of dicts (shape/carat/colour/clarity)
instead of just carats.

## E. Tests

`tests/test_stone_price.py`: 0.25 boundary; grouped-bucket lookup (0.27 ct);
full-bucket lookup (1.20 ct G/VS1 = 54 → $5,400/ct); `LC→IF`, `P2→I2`, `N→M`;
discount applied; Pear vs Round; non-Round/Pear → Round grid; missing cell → tier
fallback; 6 ct → 5.00-5.99 bucket.

## F. Validation & deploy

Backend + new OWL asset + data seed → needs `-u`. Read-only on prod: call
`get_stone_price_usd` for sample stones and assert against the sheet; render a
diamond product's price both ways (tier vs Rap by size). Deploy in a quiet window;
verify the editor loads + saves.

## Out of scope

- Only Round + Pear sheets (report only provided those). No auto-fetch of Rap
  (manual editing). No change to gold/silver pricing.
- Seed accuracy: transcribed from the provided images; the editor is the
  correction path.

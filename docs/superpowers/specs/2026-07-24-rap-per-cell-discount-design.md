# Rapaport per-cell discount

**Date:** 2026-07-24
**Status:** approved design → implementation
**Scope:** `jewellery_evaluator` — a per-cell discount % on the Rap grid + the editor UI.

## Problem

The old flat Rap discount was removed. Now each Rap grid cell carries **two**
values: the Rapaport **list** (existing, black) and a **per-cell discount %**
(new, red). Net price = `list × (1 − disc%/100)`. Discount differs per cell.

## Decisions (from brainstorming)

1. Cell layout **A · stacked**: list on top (black), discount % below (red); both
   editable in place.
2. Discount is a **percent off** (`net = list × (1 − pct/100)`).
3. Discount clamped **0–100** (no premiums over list).

## A. Data

Keep the list grids untouched; add a **parallel discount grid** per sheet:
- `jewellery_evaluator.diamond_rap_round_disc` / `…_fancy_disc` — same
  `{ bucket: { rowKey: { colKey: pct } } }` shape, `pct` a number 0–100.
- List grids `diamond_rap_round` / `_fancy` unchanged.

## B. Pricing (`utils.py`)

`rap_stone_price_usd` returns the **net**:

```
list = grid[sheet][bucket][row][col]           # None -> tier fallback (unchanged)
disc = disc_grid[sheet][bucket][row][col] or 0 # clamped 0..100
net  = list × 100 × carat × (1 − disc/100)
```

New `_rap_disc_grid(env, sheet)` reader (mirrors `_rap_grid`); disc looked up with
the same `(bucket, row, col)` from `rap_keys`. Missing/blank/invalid disc → 0 (full
list). Clamp 0–100 at read time (defence in depth).

## C. Editor (layout A)

`static/src/{js,xml,scss}/diamond_rap_editor.*`:
- Each cell = two stacked inputs — **list** (black, top) + **discount %** (red,
  bottom, `0–100`).
- `rap_get` returns `round`, `fancy`, `round_disc`, `fancy_disc`, `structure`.
- `rap_set(sheet, grid, disc)` stores the list grid (whitelisted numeric > 0 as
  today) **and** the disc grid (whitelisted, clamped 0–100), then recomputes
  stones. Client state gains `discs = { round, fancy }`; `discCell` / `onDiscCell`
  mirror `cell` / `onCell`.
- SCSS: taller cells for the two stacked inputs; red disc input.

## D. Tests (`tests/test_stone_price.py`)

Net math (`list 54, disc 25, 1.20 ct → 54×100×1.2×0.75 = 4860`); missing disc →
full list; disc 0 → list; clamp (disc 150 → treated as 100 by the reader); per-cell
(two cells, different disc). Round/Fancy unaffected by each other's disc.

## E. Deploy

Ships with **empty discount grids** → disc 0 everywhere → net == list == today's
prices → **no price change on deploy**. Backend + POS/backend asset → `-u`.
Read-only prod validation (net math on samples; deployed `rap_set` round-trips a
disc grid; editor payload has the disc keys) then verify live.

## Out of scope

- No premiums (negative disc). No net-column display in the editor (net is computed
  in pricing; can add later). No change to tiers / gold / silver / invoice.

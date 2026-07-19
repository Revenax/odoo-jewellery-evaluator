# POS Cash-Ops v2 — Currency Conversion + Transfer to Owner

**Date:** 2026-07-19
**Status:** approved design → implementation
**Scope:** `jewellery_evaluator` — POS Navbar cash-ops popups + backend RPCs.

## Problem

The two POS cash-ops popups (added 2026-07-11) are each **one-directional** and
**EGP-centric**, and the UI does not make the money movement legible:

- **Currency Conversion** only *buys* foreign with EGP (EGP Vault → Vault Foreign).
  You cannot *sell* foreign back to EGP. No summary of what actually moves.
- **Transfer to Owner** only sends **EGP** *out* to an owner (EGP Vault → Owner).
  You cannot move foreign cash to an owner, and you cannot record an owner
  *depositing* cash back into the vault.

## Prod journal setup (Sway Mall, company currency EGP)

| Journal | Currency | GL acct |
|---|---|---|
| Vault - Sway Mall | EGP | 105001 |
| Vault Foreign USD | USD | 105002 |
| Vault Foreign SAR | SAR | 105004 |
| Vault Foreign AED | AED | 105005 |
| Owner - Anas / Omar / Mohamed / Ahmed Abbassi | EGP | 105006–105009 |

Journals resolve **by convention, company-scoped** (unchanged): Vault Foreign =
cash journals in a non-company currency; Owner = cash journals named `Owner%`.
EGP Vault box = the session's `cash_journal_id`.

## Decisions (from brainstorming)

1. Currency conversion: **two-way**, cashier enters **both amounts** (EGP + foreign),
   **no manual rate** — a **read-only implied rate** (`EGP ÷ foreign`) is displayed.
2. Owner transfer: **both directions** (owner takes out / owner deposits in),
   **every currency** (EGP Vault or any foreign box).
3. Foreign owner transfer valuation: **both amounts** (enter the foreign amount +
   its EGP value), **no manual rate**; **read-only implied rate** displayed.
4. **Two labeled popups** kept (`Currency`, `Transfer to Owner`).
5. **Any cashier** may use both — drop the `minimal`-role gate.

## A. Currency Conversion popup

- **Direction toggle:** `Buy foreign (EGP → ccy)` | `Sell foreign (ccy → EGP)`.
- **Currency** select: the Vault Foreign journals (USD / SAR / AED).
- **Two amount inputs**; labels flip with direction:
  - Buy: "EGP out of drawer" + "Foreign into box".
  - Sell: "Foreign out of box" + "EGP into drawer".
- **Read-only implied rate** = `amount_egp ÷ to_amount` (blank until both > 0).
- **Plain summary line** above Confirm, e.g. *"Take 5,000 EGP out of the drawer,
  add $100.00 to the USD box (≈ 50.00 EGP/USD)."*

### Backend `post_currency_conversion(session_id, direction, journal_id, amount_egp, to_amount, key)`

`direction ∈ {'buy','sell'}`. Foreign leg carries `currency_id` + `amount_currency`.

| direction | EGP leg (Vault 105001) | Foreign leg (Vault Foreign ccy) |
|---|---|---|
| buy | Cr `amount_egp` | Dr `amount_egp`, `amount_currency = +to_amount` |
| sell | Dr `amount_egp` | Cr `amount_egp`, `amount_currency = −to_amount` |

## B. Transfer to Owner popup

- **Direction toggle:** `Owner takes out (Vault → Owner)` | `Owner deposits in (Owner → Vault)`.
- **Owner** select (4 owners).
- **Box** select: `EGP Vault` | USD | SAR | AED (EGP Vault = session cash journal,
  added client-side, whitelisted server-side).
- **Amount** in the box currency. If the box is **foreign**: a second **EGP value**
  input + **read-only implied rate** (`egp ÷ foreign`). If **EGP box**: single
  amount, no rate.
- **Plain summary** + Confirm.

### Backend `post_owner_transfer(session_id, direction, owner_journal_id, box_journal_id, amount, amount_egp, key)`

`direction ∈ {'out','in'}`. `egp = amount_egp` (EGP box: `amount_egp == amount`,
no currency leg). Foreign box legs carry `currency_id` + `amount_currency`, signed
to match the leg: **debit leg → `+amount`, credit leg → `−amount`** (Odoo
convention). The owner leg mirrors the box leg's currency/amount with the opposite
debit/credit (so it carries the opposite `amount_currency` sign).

| direction | Owner leg (105006–09) | Box leg |
|---|---|---|
| out | Dr `egp` (`amount_currency +amount`) | Cr `egp` (`amount_currency −amount`) |
| in | Cr `egp` (`amount_currency −amount`) | Dr `egp` (`amount_currency +amount`) |

(Same sign rule applies to Currency Conversion: the buy foreign leg is a **debit**
→ `+to_amount`; the sell foreign leg is a **credit** → `−to_amount`.)

## C. Accounting / Vault-sync correctness

- The **EGP-Vault leg (105001)** auto-folds into the shift via the existing
  `pos.session` Vault override (posted move lines on 105001, not POS statement
  lines): **out/buy** lowers expected EGP, **in/sell** raises it. Exactly one count.
- **Foreign-box** operations never touch 105001 (physical EGP drawer unchanged;
  the foreign box's own journal balance tracks the movement). So they do not
  affect the EGP shift reconciliation — correct.
- All legs post via the **general journal** (`move_type='entry'`), so they are not
  POS statement lines and the override counts them once. Unchanged pattern.

## D. Server hardening (reuse + extend)

- **Open-session guard** (`_cash_ops_check_session`).
- **Journal whitelist recomputed server-side** — the frontend list is not trusted.
  Currency: foreign journals only. Owner: owner journals for the owner leg; the
  **box** must be the session EGP Vault **or** a foreign journal (new
  `_cash_ops_resolve_box` whitelist).
- **Idempotency** via `account.move.jewellery_cash_ops_key` (one move per client
  key; retries/double-clicks reuse it).
- **Validation:** positive amounts; `direction` in the allowed set; foreign legs
  require a currency; EGP box requires `amount_egp == amount`.

## E. Config

Owner + foreign journal lists already shipped on `pos.config`
(`jewellery_vault_foreign_journals`, `jewellery_owner_journals`). No new stored
field: the EGP-Vault box is derived from the session cash journal on the client
and whitelisted on the server.

## F. Validation & deploy

- **Read-only on prod first:** in a SAVEPOINT, post **all 6 JE variants**
  (buy, sell; owner out/in × EGP/foreign box) → assert each is **balanced**, hits
  the **right accounts**, and carries the correct **`amount_currency` sign** →
  ROLLBACK. No permanent change.
- Backend Python + POS JS/XML assets → **needs `-u` + ~15–30s restart**. Deploy in
  a quiet window; re-verify live after.

## Out of scope

- No FX gain/loss revaluation of the foreign boxes (they carry book value at the
  amounts entered; consistent with the current buy flow).
- No change to the Vault-sync override, POS min-price override, or invoice report.

# -*- coding: utf-8 -*-
# Copyright 2026 Revenax Digital Services
# Author: Mohamed A. Abdallah
# Website: https://www.revenax.com
"""Move the history of the shared gold accounts onto the karat accounts.

One-time, 2026-11-16, after configure_accounting.py created the karat
accounts. A pure reclass: no amount leaves revenue/revaluation, so profit is
unchanged. Run in the Odoo shell (scripts/ops/run_odoo.sh); rolls back unless
COMMIT=1. Safe to re-run: what is already moved is not moved again.

1. Making fees: 500121 (gold jewellery) and 500122 (bullion premium) are
   emptied month by month into the karat fee accounts (500124-500129). Each
   month's balance is shared by karat in proportion to that month's making
   fee per karat, as correcting_entries.py section 10 computes it (its targets
   on 2026-11-16, below). A proportional share keeps the reclass exact even
   where those targets have drifted from what was booked.
2. Revaluation: every stock closing that booked a gold karat's re-mark on the
   shared 500102 moves it to that karat's revaluation account (500151-500153).
   A closing pairs each inventory line with an equal and opposite 500102 line,
   so this is exact. One entry per closing, on the closing's date.
"""
import os
from collections import defaultdict

from odoo import fields
from odoo.addons.jewellery_evaluator.jewellery_evaluator.utils import (
    GOLD_KARAT_ACCOUNTS, GOLD_KARAT_OTHER_ACCOUNTS, LEGACY_MAKING_FEE_ACCOUNTS)

COMMIT = os.environ.get('COMMIT') == '1'
company = env.company
Account = env['account.account'].sudo()
Move = env['account.move'].sudo()
today = fields.Date.context_today(Move)
misc = env['account.journal'].sudo().search([('type', '=', 'general'), ('code', '=', 'MISC')], limit=1)
RECLASS = 'Reclass'


def acc(code):
    a = Account.search([('code', '=', code), ('company_ids', 'in', company.id)], limit=1)
    if not a:
        raise ValueError(f'account {code} missing: run configure_accounting.py first')
    return a


def post(ref, date, amounts):
    """amounts: {account: balance}; posts them if any is non-zero."""
    lines = [(0, 0, {'account_id': a.id, 'name': ref, 'debit': max(v, 0), 'credit': max(-v, 0)})
             for a, v in amounts.items() if not company.currency_id.is_zero(v)]
    if not lines:
        return
    move = Move.create({'journal_id': misc.id, 'date': date, 'ref': ref, 'line_ids': lines})
    move.action_post()
    print('POSTED', ref, move.name, ', '.join(f'{l.account_id.code} {l.balance:,.2f}' for l in move.line_ids))


# 1. making fees: month -> legacy account -> karat account -> weight (credit).
FEE_WEIGHTS = {
    '2026-06': {'500121': {'500126': 357493.92}, '500122': {'500127': 57864.79, '500128': 17498.50}},
    '2026-07': {'500121': {'500125': 4758.50, '500126': 480034.18},
                '500122': {'500127': 120542.55, '500128': 23172.75}},
    '2026-08': {'500121': {'500126': 306017.41}, '500122': {'500127': 143404.96, '500128': 10257.60}},
    '2026-09': {'500121': {'500125': 6826.80, '500126': 305676.02},
                '500122': {'500127': 154542.23, '500128': 12532.35}},
    '2026-10': {'500121': {'500126': 229149.29}, '500122': {'500127': 151066.59, '500128': 18459.75}},
    '2026-11': {'500121': {'500126': 160169.38}, '500122': {'500127': 62212.84}},
}
legacy = {acc(code): code for code in LEGACY_MAKING_FEE_ACCOUNTS.values()}
env.cr.execute("""
    SELECT to_char(l.date, 'YYYY-MM'), l.account_id, SUM(l.balance)
      FROM account_move_line l WHERE l.parent_state = 'posted' AND l.account_id IN %s GROUP BY 1, 2
""", (tuple(a.id for a in legacy),))
for month, account_id, balance in sorted(env.cr.fetchall()):
    source = Account.browse(account_id)
    balance = round(float(balance), 2)
    if company.currency_id.is_zero(balance):
        continue
    weights = FEE_WEIGHTS.get(month, {}).get(legacy[source])
    if not weights:
        raise ValueError(f'{month} {source.code} {balance:,.2f}: no karat weights for this month')
    total = sum(weights.values())
    amounts, left = {}, balance
    items = sorted(weights.items())
    for i, (code, weight) in enumerate(items):
        share = left if i == len(items) - 1 else round(balance * weight / total, 2)
        amounts[acc(code)] = share
        left = round(left - share, 2)
    amounts[source] = -balance
    end = fields.Date.end_of(fields.Date.to_date(month + '-01'), 'month')
    post(f'{RECLASS}: making fee by karat {month} ({source.code})', min(end, today), amounts)

# 2. revaluation per stock closing.
shared = acc('500102')
karat_reval = {acc(GOLD_KARAT_ACCOUNTS[k]['stock']): acc(GOLD_KARAT_OTHER_ACCOUNTS[k]['revaluation'])
               for k in GOLD_KARAT_ACCOUNTS}
closings = Move.search([('state', '=', 'posted'), ('line_ids.account_id', '=', shared.id),
                        ('line_ids.account_id', 'in', [a.id for a in karat_reval])], order='date, id')
for closing in closings:
    ref = f'{RECLASS}: gold revaluation by karat {closing.name}'
    if Move.search_count([('ref', '=', ref), ('state', '=', 'posted')]):
        continue
    amounts = defaultdict(float)
    for line in closing.line_ids.filtered(lambda l: l.account_id in karat_reval):
        # The inventory line's counterpart on 500102 is its opposite.
        amounts[karat_reval[line.account_id]] += round(-line.balance, 2)
        amounts[shared] += round(line.balance, 2)
    post(ref, closing.date, dict(amounts))

env.cr.execute("""SELECT a.code_store->>%s, round(SUM(l.balance), 2) FROM account_move_line l
                    JOIN account_account a ON a.id = l.account_id
                   WHERE l.parent_state = 'posted' AND a.code_store->>%s IN %s GROUP BY 1 ORDER BY 1""",
               (str(company.id), str(company.id), ('500102', '500121', '500122', '500124', '500125', '500126',
                                                    '500127', '500128', '500129', '500151', '500152', '500153')))
for code, balance in env.cr.fetchall():
    print('BALANCE', code, f'{balance:,.2f}')
if COMMIT:
    env.cr.commit()
    print('COMMITTED')
else:
    env.cr.rollback()
    print('ROLLED BACK (dry run)')

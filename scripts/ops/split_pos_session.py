# -*- coding: utf-8 -*-
# Copyright 2026 Revenax Digital Services
# Author: Mohamed A. Abdallah
# Website: https://www.revenax.com
"""Split a long-open POS shift into one closed shift per day.

Run inside the Odoo shell (scripts/ops/run_odoo.sh). Rolls back unless COMMIT=1.

    SESSION   the open shift to split (default "Sway Mall/00018")
    CUTOFF    first day that stays in the open shift (default: today, Cairo).
              Orders from earlier days move to their own day shift; the open
              shift keeps the rest and stays open for the cashiers.
    BALANCES  base64 JSON {"YYYY-MM-DD": [opening, closing], ...} of the cash
              counted in the Vault. Every split day needs an entry, unless
    REHEARSE=1  opening = previous closing, closing = expected (no differences).

Per day: a new session is created and opened over the Cairo day (to the next
split day, so no time falls between shifts: the Vault sync counts every
non-POS Vault movement created in a shift's window). The day's orders, their
payments and pickings, and its cash in/out lines move to it; it is closed like
the cashier would close it, with the counted cash, and every entry it posts is
dated that day (Odoo dates a session close "today": fields.Date.context_today
is patched for the close). Opening = the counted opening, as when a cashier
opens a shift; a gap between a day's opening and the previous closing is NOT
posted (Odoo doesn't either) and is reported, because overnight cash that left
the Vault should be booked as what it was (owner transfer, bank deposit).

Shifts are then numbered by date: the first day takes the open shift's
number, the open shift takes the next free one.
"""
import base64
import datetime
import json
import os
from unittest.mock import patch

import pytz

from odoo import fields

COMMIT = os.environ.get('COMMIT') == '1'
REHEARSE = os.environ.get('REHEARSE') == '1'
TZ = pytz.timezone('Africa/Cairo')
CUTOFF = datetime.date.fromisoformat(os.environ.get('CUTOFF') or str(datetime.datetime.now(TZ).date()))
BAL = {datetime.date.fromisoformat(k): v for k, v in
       json.loads(base64.b64decode(os.environ['BALANCES']) if os.environ.get('BALANCES') else '{}').items()}

S = env['pos.session'].sudo()
src = S.search([('name', '=', os.environ.get('SESSION', 'Sway Mall/00018'))])
assert len(src) == 1 and src.state == 'opened', f'{src.name} is not one open session'
cfg = src.config_id
cash_journal = src.cash_journal_id
vault = cash_journal.default_account_id
cr = env.cr


def utc_midnight(day):
    return TZ.localize(datetime.datetime.combine(day, datetime.time())).astimezone(pytz.utc).replace(tzinfo=None)


def cairo_day(dt):
    return pytz.utc.localize(dt).astimezone(TZ).date()


by_day = {}
for order in src.order_ids:
    day = cairo_day(order.date_order)
    if day < CUTOFF:
        by_day.setdefault(day, []).append(order.id)
days = sorted(by_day)
assert days, 'nothing to split'
missing = [d for d in days if d not in BAL]
assert REHEARSE or not missing, f'no balances for {len(missing)} days: {missing[:10]}'

cash_io = {l.id: l.date for l in src.statement_line_ids}
payments = {p.id: p.date for p in env['account.payment'].sudo().search([('pos_session_id', '=', src.id)])}


def owner_day(date):
    """The split day a dated record belongs to: the last split day on or before it."""
    if date >= CUTOFF:
        return None
    earlier = [d for d in days if d <= date]
    return earlier[-1] if earlier else days[0]


first_start = src.start_at
VAULT_BEFORE = sum(env['account.move.line'].sudo().search([('account_id', '=', vault.id), ('parent_state', '=', 'posted')]).mapped('balance'))
print('VAULT GL BEFORE', round(VAULT_BEFORE, 2))
prev_close = src.cash_register_balance_start if REHEARSE else None
created = env['pos.session']
report = []
gaps = []
for i, day in enumerate(days):
    start = first_start if i == 0 else utc_midnight(day)
    end = (utc_midnight(days[i + 1]) if i + 1 < len(days) else utc_midnight(CUTOFF)) - datetime.timedelta(seconds=1)
    ns = S.with_context(onboarding_creation=True).create({'config_id': cfg.id, 'user_id': src.user_id.id})
    ns.write({'state': 'opened', 'start_at': start, 'stop_at': end})
    ids = tuple(by_day[day])
    cr.execute('UPDATE pos_order SET session_id=%s WHERE id IN %s', (ns.id, ids))
    cr.execute('UPDATE pos_payment SET session_id=%s WHERE pos_order_id IN %s', (ns.id, ids))
    cr.execute('UPDATE stock_picking SET pos_session_id=%s WHERE pos_order_id IN %s', (ns.id, ids))
    io = tuple(k for k, d in cash_io.items() if owner_day(d) == day)
    if io:
        cr.execute('UPDATE account_bank_statement_line SET pos_session_id=%s WHERE id IN %s', (ns.id, io))
    pays = tuple(k for k, d in payments.items() if owner_day(d) == day)
    if pays:
        cr.execute('UPDATE account_payment SET pos_session_id=%s WHERE id IN %s', (ns.id, pays))
    env.invalidate_all()
    ns.modified(['order_ids', 'statement_line_ids'])

    if REHEARSE:
        opening = prev_close
    else:
        opening, closing = (float(x) for x in BAL[day])
        if prev_close is not None and abs(opening - prev_close) > 0.005:
            gaps.append((day, prev_close, opening))
    ns.cash_register_balance_start = opening
    env.flush_all()
    ns.invalidate_recordset()
    cash_sales = sum(ns.order_ids.payment_ids.filtered(lambda p: p.payment_method_id.is_cash_count).mapped('amount'))
    io_total = sum(ns.statement_line_ids.mapped('amount'))
    foreign = ns._vault_foreign_move_lines()
    foreign_total = sum(foreign.mapped('balance'))
    expected = ns.cash_register_balance_end
    if REHEARSE:
        closing = expected
    ns.cash_register_balance_end_real = closing
    # cash_register_difference is a non-stored compute that does not depend on
    # the counted cash: drop the value cached when Expected was read above.
    env.flush_all()
    ns.invalidate_recordset(['cash_register_balance_end', 'cash_register_difference'])
    assert abs(ns.cash_register_difference - (closing - expected)) < 0.01, f'{day}: difference {ns.cash_register_difference}'
    with patch.object(fields.Date, 'context_today', staticmethod(lambda record=None, timestamp=None, _d=day: _d)):
        res = ns.action_pos_session_closing_control()
    assert res is True and ns.state == 'closed', f'{day}: close did not finish ({res})'
    assert not ns.move_id or ns.move_id.date == day, f'{day}: move dated {ns.move_id.date}'
    other = {m.name: sum(ns.order_ids.payment_ids.filtered(lambda p, m=m: p.payment_method_id == m).mapped('amount'))
             for m in ns.order_ids.payment_ids.payment_method_id if not m.is_cash_count}
    report.append((day, len(ids), cash_sales, io_total, foreign_total, opening, expected, closing,
                   closing - expected, ns.move_id.name or '', other))
    created |= ns
    if os.environ.get('DEBUG') and i < int(os.environ['DEBUG']):
        for ml in ns.move_id.line_ids | ns.statement_line_ids.move_id.line_ids:
            print('  ML', day, ml.move_id.name, ml.account_id.code, ml.balance, ml.name)
    prev_close = closing

# Number shifts by date: the first day takes the open shift's number.
seq = env['ir.sequence'].sudo().with_context(company_id=cfg.company_id.id).search(
    [('code', '=', 'pos.session'), ('company_id', 'in', [cfg.company_id.id, False])], order='company_id', limit=1)
first_name = src.name
for i, ns in enumerate(created):
    ns.name = first_name if i == 0 else cfg.name + seq.next_by_code('pos.session')
src.write({'name': cfg.name + seq.next_by_code('pos.session'), 'start_at': utc_midnight(CUTOFF)})
env.invalidate_all()

AML = env['account.move.line'].sudo()
open_rec = AML.search([('account_id', '=', cfg.company_id.account_default_pos_receivable_account_id.id),
                       ('parent_state', '=', 'posted'), ('reconciled', '=', False)])
for r in report:
    day, n, cash, io_amt, fgn, op, exp, cl, diff, move, other = r
    print(f'DAY {day} orders={n} cash={cash:,.0f} cash_io={io_amt:,.0f} other_vault={fgn:,.0f} '
          f'open={op:,.0f} expected={exp:,.0f} counted={cl:,.0f} diff={diff:,.0f} {move} {other}')
for day, prev, op in gaps:
    print(f'GAP {day}: opening {op:,.0f} vs previous closing {prev:,.0f} ({op - prev:+,.0f})')
print('SESSIONS', len(created), created[:1].name, '->', created[-1:].name, '| open shift now', src.name,
      'orders', len(src.order_ids), 'start', src.start_at)
print('POS RECEIVABLE open lines', len(open_rec), round(sum(open_rec.mapped('amount_residual')), 2))
vault_bal = sum(AML.search([('account_id', '=', vault.id), ('parent_state', '=', 'posted')]).mapped('balance'))
print('VAULT GL', vault.code, round(vault_bal, 2))
if COMMIT:
    cr.commit()
    print('COMMITTED')
else:
    cr.rollback()
    print('ROLLED BACK (dry run)')

# -*- coding: utf-8 -*-
# Copyright 2026 Revenax Digital Services
# Author: Mohamed A. Abdallah
# Website: https://www.revenax.com
"""One-time correcting entries after configure_accounting.py (idempotent).

Run through the Odoo shell (dry run unless COMMIT=1):
  sudo -u odoo env COMMIT=1 bash -c '/opt/odoo/ee-odoo-bin shell -c /etc/odoo.conf -d marjaan --no-http < correcting_entries.py'

1. Owner cash-ins/outs: four Vault (CSH1) shift entries naming an owner sat
   in Bank Suspense. Each is pointed at that owner's account.
2. June InstaPay: 41 InstaPay payments from before direct posting (29 POS,
   12 manual) stayed in Outstanding Receipts, the POS ones "in process". InstaPay settles into CIB, so one
   entry moves them to CIB and matches each payment (they become Paid). The
   accountant should tick them against the CIB statement.
3. A 37,500 card payment from shift 00010 that was credited to VAT
   Receivable is moved to the POS receivable it settles.
4. Opening inventory: the pieces in stock become the opening balance of the
   new Inventory accounts at today's metal value, against Owners' Capital,
   then the stock valuation is closed (it should find nothing left to post).

The open POS shift is not touched.
"""
import os

from odoo import fields

COMMIT = os.environ.get('COMMIT') == '1'
LOG = []
company = env.company
Move = env['account.move'].sudo()
Account = env['account.account'].sudo()


def log(msg):
    LOG.append(msg)
    print('FIX', msg)


def acc(code):
    a = Account.search([('code', '=', code), ('company_ids', 'in', company.id)], limit=1)
    if not a:
        raise ValueError(f'account {code} missing: run configure_accounting.py first')
    return a


misc = env['account.journal'].sudo().search([('type', '=', 'general'), ('code', '=', 'MISC')], limit=1)

# ── 1. owner entries out of suspense ────────────────────────────────────
OWNERS = {'anas': 'OWANA', 'omar': 'OWOMA', 'mohamed': 'OWMOH', 'ahmed': 'OWAHM'}
vault = env['account.journal'].sudo().search([('code', '=', 'CSH1')], limit=1)
for st in env['account.bank.statement.line'].sudo().search(
        [('journal_id', '=', vault.id), ('is_reconciled', '=', False)]):
    ref = (st.payment_ref or '').lower()
    owner = [code for name, code in OWNERS.items() if name in ref]
    if len(owner) != 1:
        log(f'LEFT for the accountant: {st.date} {st.amount} "{st.payment_ref}" (no single owner named)')
        continue
    owner_acc = env['account.journal'].sudo().search([('code', '=', owner[0])], limit=1).default_account_id
    suspense = st.move_id.line_ids.filtered(lambda l: l.account_id == vault.suspense_account_id)
    st.set_account_bank_statement_line(suspense.ids, owner_acc.id)
    log(f'{st.date} {st.amount:>10} "{st.payment_ref}" -> {owner_acc.code} {owner_acc.name}')

# ── 2. June InstaPay out of Outstanding Receipts ────────────────────────
outstanding = acc('101002')
cib = acc('101013')
lines = env['account.move.line'].sudo().search([
    ('account_id', '=', outstanding.id), ('reconciled', '=', False), ('parent_state', '=', 'posted'),
    ('journal_id.code', '=', 'IPAY'), ('balance', '>', 0)])
if lines:
    total = sum(lines.mapped('balance'))
    move = Move.create({
        'journal_id': misc.id,
        'date': max(lines.mapped('date')),
        'ref': 'June InstaPay payments received in CIB (recorded before direct posting)',
        'line_ids': [(0, 0, {'account_id': cib.id, 'name': 'InstaPay received in CIB', 'debit': total})] + [
            (0, 0, {'account_id': outstanding.id, 'partner_id': l.partner_id.id,
                    'name': l.move_id.name, 'credit': l.balance}) for l in lines],
    })
    move.action_post()
    for line in lines:
        (line | move.line_ids.filtered(lambda m: m.name == line.move_id.name)).reconcile()
    payments = lines.move_id.origin_payment_id
    log(f'{len(lines)} InstaPay payments ({total:,.2f}) moved to CIB in {move.name}; '
        f'still in process: {len(payments.filtered(lambda p: p.state == "in_process"))}')

# ── 3. card payment posted to VAT ───────────────────────────────────────
# PIPAY/2026/00047 collected shift 00010's card takings (37,500) but credited
# VAT Receivable instead of POS receivables, leaving both wrong.
vat = acc('100103')
pos_ar = acc('102012')
card = env['account.move.line'].sudo().search([
    ('account_id', '=', pos_ar.id), ('reconciled', '=', False), ('parent_state', '=', 'posted'),
    ('name', '=', 'Marjaan Jewellery/00010 - Card')], limit=1)
vat_balance = sum(env['account.move.line'].sudo().search(
    [('account_id', '=', vat.id), ('parent_state', '=', 'posted')]).mapped('balance'))
if card and company.currency_id.compare_amounts(vat_balance, -card.amount_residual) == 0:
    move = Move.create({
        'journal_id': misc.id,
        'date': card.date,
        'ref': 'PIPAY/2026/00047 was posted to VAT Receivable; it settles shift 00010 card takings',
        'line_ids': [(0, 0, {'account_id': vat.id, 'name': 'Reverse wrong VAT posting', 'debit': card.amount_residual}),
                     (0, 0, {'account_id': pos_ar.id, 'name': card.name, 'credit': card.amount_residual})],
    })
    move.action_post()
    (card | move.line_ids.filtered(lambda l: l.account_id == pos_ar)).reconcile()
    log(f'card takings of shift 00010 ({move.amount_total:,.2f}) moved off VAT in {move.name}')

# ── 4. opening inventory ────────────────────────────────────────────────
capital = acc('300001')
key = 'Opening inventory (perpetual valuation start)'
if not Move.search([('ref', '=', key), ('state', '=', 'posted')], limit=1):
    T = env['product.template'].sudo()
    env.cr.execute("""SELECT DISTINCT pp.product_tmpl_id FROM stock_quant q
                      JOIN stock_location l ON l.id = q.location_id
                      JOIN product_product pp ON pp.id = q.product_id
                      WHERE l.usage = 'internal' AND q.quantity > 0""")
    changed = T.browse([r[0] for r in env.cr.fetchall()])._jewellery_mark_cost()
    log(f'{changed} pieces re-marked to today\'s cost')
    by_account = {a: v for a, v in company.stock_value().items() if not company.currency_id.is_zero(v)}
    booked = company.stock_accounting_value()
    if any(not company.currency_id.is_zero(v) for v in booked.values()):
        raise ValueError(f'inventory accounts already carry a balance: {booked}')
    total = sum(by_account.values())
    move = Move.create({
        'journal_id': company.account_stock_journal_id.id,
        'date': fields.Date.context_today(Move),
        'ref': key,
        'line_ids': [(0, 0, {'account_id': a.id, 'name': key, 'debit': v}) for a, v in by_account.items()]
        + [(0, 0, {'account_id': capital.id, 'name': key, 'credit': total})],
    })
    move.action_post()
    for a, v in by_account.items():
        log(f'opening {a.code} {a.name}: {v:,.2f}')
    log(f'opening inventory {total:,.2f} against {capital.code} in {move.name}')
    left = company._action_close_stock_valuation()
    log(f'stock valuation closing after opening: {len(left)} lines left to post (expected 0)')

if COMMIT:
    env.cr.commit()
    print('FIX done,', len(LOG), 'items')
else:
    env.cr.rollback()
    print('FIX dry run,', len(LOG), 'items rolled back')

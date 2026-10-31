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

5. Historical cost of goods sold: an estimate for every sale before
   perpetual valuation, at the metal price of the sale date, one entry per
   month against Owners' Capital.
6. Sales before go-live all sat in one "Sales Account" (500001). They are
   moved, per month, to the sales account of each piece's material (Gold
   Jewellery, Gold Bullion, Diamond, Silver), so margins compare like with
   like. Free-text lines are matched by the SKU they name.
7. Gold bullion split: bullion sold since go-live (and its share of the
   historical cost estimate) moves from the Gold Jewellery accounts to the
   Gold Bullion ones.
8. Buy-back bills before go-live were booked as an expense ("Others"). The
   pieces are already in the opening inventory or the historical cost
   estimate, both credited to Owners' Capital, so the cash the shop paid for
   them comes off the capital instead.

9. Negative bullion stock: bars and coins were sold without ever being
   received in Odoo, so their on-hand went negative (GB-BTC-10G at -73).
   Once a sale re-marked their cost, the first nightly closing valued that
   negative stock and booked a 5.2M phantom revaluation loss. The negative
   on-hand is set to zero (the closing reverses the phantom loss), and the
   bars sold since go-live, whose cost of goods sold was posted for real,
   are booked as bought with the owners' money. From then on the nightly
   cron does this itself (_jewellery_settle_negative_bullion).

Sections 6-8 post only the difference between what should have moved and
what earlier runs moved, so a re-run never moves anything twice.

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

# ── 5. historical cost of goods sold (estimate) ─────────────────────────
# Sales before perpetual valuation posted no COGS. Estimate it per sold piece
# at the metal price of its sale date (gold/silver price history from the
# price crons' ir.logging lines; stones at the feed USD rate), one entry per
# month against Owners' Capital (the pieces were never on the books).
import bisect
import re
from collections import defaultdict

from odoo.addons.jewellery_evaluator.jewellery_evaluator.utils import gold_price_for_purity, inventory_cost_egp

HIST = 'Historical cost of goods sold (estimate)'


def material_of(jtype, bullion=True):
    if jtype == 'silver':
        return 'Silver'
    if jtype in ('diamond_jewellery', 'center_stone'):
        return 'Diamond'
    return 'Bullion' if bullion and jtype == 'gold_bars' else 'Gold'


def historical_cost_by_month(before=None, bullion=False):
    """{month: {material: cost}} for every sale and return (before ``before``)."""
    def series(logger, patterns):
        env.cr.execute("SELECT create_date, message FROM ir_logging WHERE name = %s ORDER BY create_date", (logger,))
        points = []
        for when, msg in env.cr.fetchall():
            for pat in patterns:
                m = re.search(pat, msg or '')
                if m:
                    points.append((when, float(m.group(1))))
                    break
        return points

    gold = series('jewellery_evaluator.gold_price_cron', [r'-> ([\d.]+) EGP/g', r'base ([\d.]+)/g'])
    silver = series('jewellery_evaluator.silver_price_cron', [r'-> ([\d.]+) EGP/g', r'base ([\d.]+)/g'])
    gold_times = [t for t, _ in gold]
    silver_times = [t for t, _ in silver]

    def price_at(points, times, when):
        if not points:
            return 0.0
        i = bisect.bisect_right(times, when) - 1
        return points[max(i, 0)][1]

    usd_rate = float(env['ir.config_parameter'].sudo().get_param('jewellery_evaluator.feed_usd_egp') or 0)
    # Every sale and return so far: POS lines, then manual (non-POS) invoices.
    env.cr.execute("""
        SELECT o.date_order, l.product_id, l.qty FROM pos_order_line l
          JOIN pos_order o ON o.id = l.order_id
         WHERE o.state IN ('paid', 'done', 'invoiced')
        UNION ALL
        SELECT m.create_date, aml.product_id,
               CASE WHEN m.move_type = 'out_refund' THEN -aml.quantity ELSE aml.quantity END
          FROM account_move_line aml JOIN account_move m ON m.id = aml.move_id
         WHERE m.state = 'posted' AND m.move_type IN ('out_invoice', 'out_refund')
           AND aml.display_type = 'product' AND aml.product_id IS NOT NULL
           AND NOT EXISTS (SELECT 1 FROM pos_order po WHERE po.account_move = m.id)
    """)
    sales = env.cr.fetchall()
    Product = env['product.product'].sudo().with_context(active_test=False)
    by_month = defaultdict(lambda: defaultdict(float))
    unknown = defaultdict(int)
    for when, product_id, qty in sales:
        if before and when >= before:
            continue
        tmpl = Product.browse(product_id).product_tmpl_id
        jtype = tmpl.jewellery_type
        if not jtype or not qty:
            continue
        if jtype == 'silver':
            metal = price_at(silver, silver_times, when) * (tmpl.jewellery_weight_g or 0)
        else:
            metal = gold_price_for_purity(price_at(gold, gold_times, when), tmpl.gold_purity or '') * (tmpl.jewellery_weight_g or 0)
        cost = inventory_cost_egp(
            jtype, metal_cost_egp=metal, base_gold_price_21k=price_at(gold, gold_times, when),
            gold_purity=tmpl.gold_purity, gold_weight_g=tmpl.jewellery_weight_g,
            stones_cost_usd=sum(st.total_price_usd for st in tmpl.stone_ids if st.total_price_usd > 0),
            usd_rate=usd_rate)
        if cost is None:
            unknown[jtype] += 1
            continue
        material = material_of(jtype, bullion)
        by_month[when.strftime('%Y-%m')][material] += cost * qty
    return by_month, len(sales), len(gold), usd_rate, unknown


if not Move.search([('ref', '=like', HIST + '%'), ('state', '=', 'posted')], limit=1):
    by_month, n_sales, n_gold, usd_rate, unknown = historical_cost_by_month()
    COGS = {'Gold': '400201', 'Diamond': '400202', 'Silver': '400203'}
    today = fields.Date.context_today(Move)
    for month in sorted(by_month):
        amounts = {m: round(v, 2) for m, v in by_month[month].items() if round(v, 2)}
        if not amounts:
            continue
        end = fields.Date.end_of(fields.Date.to_date(month + '-01'), 'month')
        total = sum(amounts.values())
        move = Move.create({
            'journal_id': misc.id,
            'date': min(end, today),
            'ref': f'{HIST} {month}',
            'line_ids': [(0, 0, {'account_id': acc(COGS[m]).id, 'name': f'{HIST}: {m}', 'debit': v} if v > 0 else
                          {'account_id': acc(COGS[m]).id, 'name': f'{HIST}: {m}', 'credit': -v})
                         for m, v in amounts.items()]
            + [(0, 0, {'account_id': capital.id, 'name': HIST, 'credit': total} if total > 0 else
                {'account_id': capital.id, 'name': HIST, 'debit': -total})],
        })
        move.action_post()
        log(f'{HIST} {month}: ' + ', '.join(f'{m} {v:,.2f}' for m, v in amounts.items()) + f' in {move.name}')
    log(f'historical COGS: {n_sales} sale/return lines, gold price points {n_gold}, '
        f'USD rate {usd_rate}; cost unknown (no weight/price): {dict(unknown) or "none"}')

# ── 6-8. reclassifications ──────────────────────────────────────────────
SALES = {'Gold': '500103', 'Bullion': '500106', 'Diamond': '500104', 'Silver': '500105'}
COST = {'Gold': '400201', 'Bullion': '400204', 'Diamond': '400202', 'Silver': '400203'}
RECLASS = 'Reclass'
today = fields.Date.context_today(Move)


def reclass(key, source, amounts):
    """Move ``amounts`` {(month, target code): balance} out of ``source``.

    Posts, per month, only what earlier ``key`` entries have not moved yet.
    """
    src = acc(source)
    by_month = defaultdict(dict)
    for (month, target), balance in amounts.items():
        by_month[month][target] = balance
    for month in sorted(by_month):
        ref = f'{RECLASS}: {key} {month}'
        done = env['account.move.line'].sudo().search([
            ('move_id.ref', '=', ref), ('parent_state', '=', 'posted'), ('account_id', '!=', src.id)])
        lines = []
        for target, balance in sorted(by_month[month].items()):
            todo = round(balance - sum(done.filtered(lambda l: l.account_id.code == target).mapped('balance')), 2)
            if company.currency_id.is_zero(todo):
                continue
            for account_id, value in ((acc(target).id, todo), (src.id, -todo)):
                lines.append((0, 0, {'account_id': account_id, 'name': ref,
                                     'debit': max(value, 0), 'credit': max(-value, 0)}))
        if not lines:
            continue
        end = fields.Date.end_of(fields.Date.to_date(month + '-01'), 'month')
        move = Move.create({'journal_id': misc.id, 'date': min(end, today), 'ref': ref, 'line_ids': lines})
        move.action_post()
        moved = ', '.join(f'{Account.browse(v["account_id"]).code} {v["debit"] - v["credit"]:,.2f}'
                          for _, _, v in lines)
        log(f'{ref}: {moved} in {move.name}')


def source_lines(code, extra=''):
    """Posted lines on ``code`` (not from a reclass entry) with their product's type."""
    env.cr.execute(f"""
        SELECT l.date, l.balance, l.name, pt.jewellery_type, m.move_type, m.partner_id
          FROM account_move_line l JOIN account_move m ON m.id = l.move_id
          LEFT JOIN product_product pp ON pp.id = l.product_id
          LEFT JOIN product_template pt ON pt.id = pp.product_tmpl_id
         WHERE l.account_id = %s AND m.state = 'posted' AND COALESCE(m.ref, '') NOT LIKE %s {extra}
    """, (acc(code).id, RECLASS + ':%'))
    return env.cr.fetchall()


Tmpl = env['product.template'].sudo().with_context(active_test=False)


def material_of_text(text):
    """Material of a free-text invoice line, from the SKU it names."""
    sku = (text or '').strip().split()[0] if (text or '').strip() else ''
    tmpl = Tmpl.search(['|', ('default_code', '=', sku), ('name', '=', sku)], limit=1) if sku else Tmpl
    if tmpl.jewellery_type:
        return material_of(tmpl.jewellery_type)
    if re.match(r'^G[BCI]-', sku):
        return 'Bullion'
    return {'G': 'Gold', 'D': 'Diamond', 'S': 'Silver'}.get(sku[:1])


# 6. legacy sales by material
amounts = defaultdict(float)
left = 0.0
for date, balance, name, jtype, *_ in source_lines('500001'):
    material = material_of(jtype) if jtype else material_of_text(name)
    if not material:
        left += balance
        continue
    amounts[(date.strftime('%Y-%m'), SALES[material])] += balance
reclass('legacy sales by material', '500001', amounts)
if not company.currency_id.is_zero(left):
    log(f'left in 500001 Sales - Other (no jewellery product): {left:,.2f}')

# 7. gold bullion out of the Gold Jewellery accounts
for key, source, target in (('gold bullion sales', SALES['Gold'], SALES['Bullion']),
                            ('gold bullion cost', COST['Gold'], COST['Bullion'])):
    amounts = defaultdict(float)
    for date, balance, name, jtype, *_ in source_lines(source, "AND l.product_id IS NOT NULL"):
        if jtype == 'gold_bars':
            amounts[(date.strftime('%Y-%m'), target)] += balance
    reclass(key, source, amounts)

hist = Move.search([('ref', '=like', HIST + '%'), ('state', '=', 'posted')], order='create_date')
if hist:
    by_month, *_ = historical_cost_by_month(before=hist[0].create_date, bullion=True)
    posted = defaultdict(float)
    for line in hist.line_ids.filtered(lambda l: l.account_id.code == COST['Gold']):
        posted[line.move_id.ref[len(HIST) + 1:]] += line.balance
    off = {m: round(posted[m] - (by_month[m]['Gold'] + by_month[m]['Bullion']), 2) for m in posted}
    if any(abs(v) > 1 for v in off.values()):
        log(f'SKIPPED historical bullion split: the estimate no longer reproduces {off}')
    else:
        reclass('historical cost estimate, gold bullion', COST['Gold'],
                {(m, COST['Bullion']): round(by_month[m]['Bullion'], 2) for m in posted})

# 8. buy-back bills to Owners' Capital
buyback = env.ref('jewellery_evaluator.partner_bought_from_customer')
amounts = defaultdict(float)
for date, balance, name, jtype, move_type, partner_id in source_lines('400028'):
    if move_type in ('in_invoice', 'in_refund') and partner_id == buyback.id:
        amounts[(date.strftime('%Y-%m'), capital.code)] += balance
reclass("buy-back bills to Owners' Capital", '400028', amounts)

# 9. negative bullion stock
LABEL = 'Bullion sold before it was received in Odoo (bought outside Odoo)'
quants = env['stock.quant'].sudo().search([
    ('company_id', '=', company.id), ('location_id.usage', '=', 'internal'),
    ('quantity', '<', 0), ('product_id.product_tmpl_id.jewellery_type', '=', 'gold_bars')])
if quants and hist and not Move.search([('ref', '=', LABEL + ' since go-live'), ('state', '=', 'posted')], limit=1):
    env.cr.execute("""
        SELECT COALESCE(SUM(l.balance), 0) FROM account_move_line l
          JOIN account_move m ON m.id = l.move_id
          JOIN product_product pp ON pp.id = l.product_id
          JOIN product_template pt ON pt.id = pp.product_tmpl_id
         WHERE m.state = 'posted' AND pt.jewellery_type = 'gold_bars' AND m.create_date >= %s
           AND l.account_id IN %s AND COALESCE(m.ref, '') NOT LIKE %s
    """, (hist[0].create_date, (acc(COST['Gold']).id, acc(COST['Bullion']).id), RECLASS + ':%'))
    sold = round(float(env.cr.fetchone()[0]), 2)
    log(f'{len(quants)} negative bullion quants ({-sum(quants.mapped("quantity")):g} units) set to 0')
    quants.with_context(inventory_mode=True).write({'inventory_quantity': 0})
    quants.with_context(inventory_mode=True).action_apply_inventory()
    if sold:
        move = Move.create({
            'journal_id': company.account_stock_journal_id.id, 'date': today, 'ref': LABEL + ' since go-live',
            'line_ids': [(0, 0, {'account_id': acc('132101').id, 'name': LABEL, 'debit': sold}),
                         (0, 0, {'account_id': capital.id, 'name': LABEL, 'credit': sold})]})
        move.action_post()
        log(f'bullion sold since go-live from unrecorded stock: {sold:,.2f} against {capital.code} in {move.name}')
    left = company._action_close_stock_valuation()
    if left:
        closing = Move.create({'journal_id': company.account_stock_journal_id.id, 'date': today,
                               'ref': 'Stock Closing', 'line_ids': [(0, 0, v) for v in left]})
        closing.action_post()
        company._save_closing_id(closing.id)
        log(f'stock closing after the fix in {closing.name}: ' + ', '.join(
            f'{l.account_id.code} {l.balance:,.2f}' for l in closing.line_ids))

if COMMIT:
    env.cr.commit()
    print('FIX done,', len(LOG), 'items')
else:
    env.cr.rollback()
    print('FIX dry run,', len(LOG), 'items rolled back')

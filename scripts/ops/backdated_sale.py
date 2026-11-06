# -*- coding: utf-8 -*-
# Copyright 2026 Revenax Digital Services
# Author: Mohamed A. Abdallah
#
# Odoo-shell script: record a PAST sale from the day book as a manual invoice.
# Pass the sale as base64 JSON (no spaces allowed through run_odoo.sh):
#   SALE=$(printf '%s' '{"date":"2026-07-06","customer":"sara elmkawy","salesman":"Wael Samir",
#     "lines":[["GRF8-0094",25400]],"payments":[["CSH1",25400]]}' | base64)
#   scripts/ops/run_odoo.sh scripts/ops/backdated_sale.py SALE=$SALE [COMMIT=1]
# lines: [[sku, price], ...]; a group price may be split by list price beforehand.
# payments: [[journal_code, amount], ...]; CSH1 = Sway Mall Vault (cash), IPAY = InstaPay.
# What it does: invoice dated `date` (posting deducts on-hand, see account_move.py),
# payments dated `date`, payment moves' create_date backdated so the cash does
# NOT land in an open POS shift's Vault window, count lines of open counts removed.
# Afterwards: node scripts/ops/neon.js sold <SKUS...>
import base64, datetime, json, os
COMMIT = os.environ.get('COMMIT') == '1'
S = json.loads(base64.b64decode(os.environ['SALE']))
D = datetime.date.fromisoformat(S['date']); DT = S['date'] + ' 12:00:00'
cr = env.cr
Partner = env['res.partner']
partner = Partner.search([('name', '=', S['customer'])], limit=1) or Partner.create({'name': S['customer'], 'customer_rank': 1})
prods = []
for sku, price in S['lines']:
    p = env['product.product'].search([('default_code', '=', sku)])
    assert len(p) == 1, sku
    assert not env['pos.order.line'].search_count([('product_id', '=', p.id)]), f'{sku} already sold in POS'
    prods.append((p, price))
vals = {'move_type': 'out_invoice', 'partner_id': partner.id, 'invoice_date': D, 'date': D,
        'invoice_line_ids': [(0, 0, {'product_id': p.id, 'quantity': 1, 'price_unit': pr}) for p, pr in prods]}
if S.get('salesman'):
    vals['ref'] = 'Salesman: ' + S['salesman']
inv = env['account.move'].create(vals)
inv.action_post()
assert abs(sum(a for _, a in S['payments']) - inv.amount_total) < 0.01, 'payments != total'
pays = env['account.payment']
for code, amt in S['payments']:
    j = env['account.journal'].search([('code', '=', code)], limit=1)
    wiz = env['account.payment.register'].with_context(active_model='account.move', active_ids=inv.ids).create(
        {'journal_id': j.id, 'payment_date': D, 'amount': amt})
    pays |= wiz._create_payments()
mids = tuple(pays.mapped('move_id').ids)
cr.execute("UPDATE account_move SET create_date=%s WHERE id IN %s", (DT, mids))
cr.execute("UPDATE account_move_line SET create_date=%s WHERE move_id IN %s", (DT, mids))
env.invalidate_all()
print('invoice', inv.name, inv.amount_total, inv.payment_state, [(p.name, p.journal_id.code, p.amount) for p in pays])
lines = env['jewellery.stock.count.line'].search([('product_id', 'in', [p.id for p, _ in prods]),
                                                  ('count_id.state', '=', 'in_progress')])
counts = lines.mapped('count_id'); lines.unlink()
for p, _ in prods:
    print(' ', p.default_code, [(q.location_id.complete_name, q.quantity) for q in env['stock.quant'].search(
        [('product_id', '=', p.id), ('location_id.usage', '=', 'internal')])])
for c in counts:
    print(' ', c.name, 'found', c.found_count, 'missing', c.missing_count, 'total', c.expected_count)
if COMMIT:
    cr.commit(); print('COMMITTED')
else:
    cr.rollback(); print('DRY RUN (add COMMIT=1)')

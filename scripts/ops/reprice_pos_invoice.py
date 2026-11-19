# -*- coding: utf-8 -*-
# Copyright 2026 Revenax Digital Services
# Author: Mohamed A. Abdallah
# Website: https://www.revenax.com
"""Odoo-shell script: change line prices on a paid POS invoice (open session) and reprint A5.

    scripts/ops/run_odoo.sh scripts/ops/reprice_pos_invoice.py INVOICE=MJ-1651 SKU=GB-BTC-5G OLD=33100 NEW=33230 [PRINT=1] [COMMIT=1]

Every invoice line of SKU priced OLD becomes NEW; the POS order lines and totals, its
single payment and the payment entry move by the same difference; invoice and
payment are re-reconciled. PRINT=1 queues the A5 at the branch printer after commit.
"""
import os

cr = env.cr
inv = env['account.move'].search([('name', '=', os.environ['INVOICE'])])
sku, old, new = os.environ['SKU'], float(os.environ['OLD']), float(os.environ['NEW'])
order = inv.pos_order_ids
assert len(order) == 1 and order.session_id.state != 'closed'
pay = order.payment_ids
assert len(pay) == 1, pay
pmove = pay.account_move_id
ilines = inv.invoice_line_ids.filtered(lambda l: l.product_id.default_code == sku and abs(l.price_unit - old) < 0.01)
olines = order.lines.filtered(lambda l: l.product_id.default_code == sku and abs(l.price_unit - old) < 0.01)
assert ilines and len(ilines) == len(olines), (len(ilines), len(olines))
delta = (new - old) * sum(ilines.mapped('quantity'))
print(inv.name, inv.amount_total, '->', inv.amount_total + delta, f'({len(ilines)} lines, +{delta})')
pos_cls = next(c for c in type(inv).__mro__ if c.__module__.endswith('point_of_sale.models.account_move'))
(inv.line_ids | pmove.line_ids).remove_move_reconcile()
super(pos_cls, inv).button_draft()
ilines.write({'price_unit': new})
inv.action_post()
super(pos_cls, pmove).button_draft()
for l in pmove.line_ids:
    if l.debit:
        l.with_context(check_move_validity=False).debit = l.debit + delta
    else:
        l.with_context(check_move_validity=False).credit = l.credit + delta
pmove.action_post()
cr.execute("UPDATE pos_payment SET amount = amount + %s WHERE id = %s", (delta, pay.id))
for l in olines:
    cr.execute("""UPDATE pos_order_line SET price_unit = %(n)s, price_subtotal = %(n)s * qty,
                  price_subtotal_incl = %(n)s * qty WHERE id = %(id)s""", {'n': new, 'id': l.id})
cr.execute("UPDATE pos_order SET amount_total = amount_total + %(d)s, amount_paid = amount_paid + %(d)s WHERE id = %(o)s",
           {'d': delta, 'o': order.id})
env.invalidate_all()
ar = inv.line_ids.filtered(lambda l: l.account_id.account_type == 'asset_receivable').account_id
(inv.line_ids | pmove.line_ids).filtered(lambda l: l.account_id == ar and not l.reconciled).reconcile()
env.invalidate_all()
print('invoice', inv.amount_total, inv.payment_state, '| order', order.amount_total, order.amount_paid,
      '| payment', pay.payment_method_id.name, pay.amount, '| entry', [(l.account_id.code, l.debit, l.credit) for l in pmove.line_ids])
if os.environ.get('COMMIT') == '1':
    cr.commit(); print('COMMITTED')
    if os.environ.get('PRINT') == '1':
        print('print', env['pos.session'].jewellery_print_a5(order.session_id.id, order.id, 'a5'))
        cr.commit()
else:
    cr.rollback(); print('DRY RUN (add COMMIT=1)')

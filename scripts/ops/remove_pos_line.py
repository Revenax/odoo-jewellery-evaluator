# -*- coding: utf-8 -*-
# Copyright 2026 Revenax Digital Services
# Author: Mohamed A. Abdallah
# Website: https://www.revenax.com
"""Odoo-shell script: take a piece rung up by mistake off an invoiced POS order (open session).

    scripts/ops/run_odoo.sh scripts/ops/remove_pos_line.py INVOICE=MJ-1617 SKU=GDF8-0003 [CANCEL=MJ-1618] [COMMIT=1]

The order's line for SKU is deleted, its (single) payment and the payment's journal
entry are reduced by the line amount, the delivery move for the piece is removed and
its quant restored, and the invoice (which must no longer carry the piece) is
re-reconciled with the reduced payment. CANCEL= cancels an extra invoice that was
paid from the same payment entry. Session close later uses the corrected payment.
Only for an order whose session is still OPEN (a closed session has posted totals).
"""
import os

cr = env.cr
inv = env['account.move'].search([('name', '=', os.environ['INVOICE'])])
sku = os.environ['SKU']
order = inv.pos_order_ids
assert len(order) == 1 and order.session_id.state != 'closed', order.session_id.state
line = order.lines.filtered(lambda l: l.product_id.default_code == sku)
assert len(line) == 1 and line.qty == 1, line
assert sku not in inv.invoice_line_ids.product_id.mapped('default_code'), 'invoice still carries the piece'
amount = line.price_subtotal_incl
product = line.product_id
pickings = order.picking_ids
pay = order.payment_ids
assert len(pay) == 1, pay
pmove = pay.account_move_id
print('order', order.name, order.amount_total, 'line', sku, amount, 'payment', pay.payment_method_id.name, pay.amount, pmove.name)

# 1. unreconcile everything paid from the payment entry, cancel the extra invoice
ar = pmove.line_ids.filtered(lambda l: l.account_id.account_type == 'asset_receivable' and l.credit)
paid_invoices = (ar.matched_debit_ids.debit_move_id).move_id
(ar | ar.matched_debit_ids.debit_move_id).remove_move_reconcile()
if os.environ.get('CANCEL'):
    extra = env['account.move'].search([('name', '=', os.environ['CANCEL'])])
    assert extra in paid_invoices and not extra.pos_order_ids
    extra.button_draft(); extra.button_cancel()
    print('cancelled', extra.name, extra.state)

# 2. reduce the payment entry (both legs) and the pos.payment
pos_cls = next(c for c in type(pmove).__mro__ if c.__module__.endswith('point_of_sale.models.account_move'))
super(pos_cls, pmove).button_draft()
for l in pmove.line_ids:
    if l.debit:
        l.with_context(check_move_validity=False).debit = l.debit - amount
    else:
        l.with_context(check_move_validity=False).credit = l.credit - amount
pmove.action_post()
cr.execute("UPDATE pos_payment SET amount = amount - %s WHERE id = %s", (amount, pay.id))

# 3. delete the order line, fix order totals
cr.execute("DELETE FROM pos_order_line WHERE id = %s", (line.id,))
cr.execute("""UPDATE pos_order SET amount_total = amount_total - %(a)s, amount_paid = amount_paid - %(a)s
              WHERE id = %(o)s""", {'a': amount, 'o': order.id})

# 4. undo the piece's delivery from this order and restore its quant
for m in pickings.move_ids.filtered(lambda m: m.product_id == product and m.state == 'done'):
    for ml in m.move_line_ids:
        env['stock.quant']._update_available_quantity(ml.product_id, ml.location_id, ml.quantity)
        env['stock.quant']._update_available_quantity(ml.product_id, ml.location_dest_id, -ml.quantity)
    cr.execute("DELETE FROM stock_move_line WHERE move_id = %s", (m.id,))
    cr.execute("DELETE FROM stock_move WHERE id = %s", (m.id,))
    print('removed delivery move', m.reference)

# 5. re-reconcile the invoice with the reduced payment
env.invalidate_all()
inv_ar = inv.line_ids.filtered(lambda l: l.account_id.account_type == 'asset_receivable').account_id
(inv.line_ids | pmove.line_ids).filtered(lambda l: l.account_id == inv_ar and not l.reconciled).reconcile()
env.invalidate_all()
order = env['pos.order'].browse(order.id)
print('order now', order.amount_total, order.amount_paid, [(l.product_id.default_code, l.price_subtotal_incl) for l in order.lines],
      [(p.payment_method_id.name, p.amount) for p in order.payment_ids])
print('payment entry', pmove.name, pmove.state, [(l.account_id.code, l.debit, l.credit) for l in pmove.line_ids])
print(inv.name, inv.amount_total, inv.payment_state)
print(sku, 'on hand', [(q.location_id.complete_name, q.quantity) for q in env['stock.quant'].search([('product_id.default_code', '=', sku), ('location_id.usage', '=', 'internal')])])
print('session pos.payments total', sum(order.session_id.order_ids.payment_ids.mapped('amount')))
if os.environ.get('COMMIT') == '1':
    cr.commit(); print('COMMITTED')
else:
    cr.rollback(); print('DRY RUN (add COMMIT=1)')

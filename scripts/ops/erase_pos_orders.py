# -*- coding: utf-8 -*-
# Copyright 2026 Revenax Digital Services
# Author: Mohamed A. Abdallah
# Website: https://www.revenax.com
"""Odoo-shell script: HARD DELETE POS orders entered by mistake (tests), in an OPEN session.

    scripts/ops/run_odoo.sh scripts/ops/erase_pos_orders.py REFS=262-2-000001,262-2-000002 [COMMIT=1]

REFS are receipt numbers (pos_reference, unique; order names repeat across registers).
Removes each order with its lines, payments, payment entries, invoice and delivery,
and puts the stock back where the delivery took it from. Refuses an order in a
closed session (its totals are already posted in the session closing entry).
Afterwards: mark the pieces unsold in the ops app (neon.js) if they were synced as sold.
"""
import os

cr = env.cr
refs = os.environ['REFS'].split(',')
orders = env['pos.order'].search([('pos_reference', 'in', refs)])
assert len(orders) == len(refs), ('not found', set(refs) - set(orders.mapped('pos_reference')))
assert all(o.session_id.state != 'closed' for o in orders), 'closed session'
pos_cls = next(c for c in type(env['account.move']).__mro__ if c.__module__.endswith('point_of_sale.models.account_move'))
skus = []
for o in orders:
    inv = o.account_move
    pay_moves = o.payment_ids.account_move_id
    moves = inv | pay_moves
    print(o.pos_reference, o.name, o.amount_total, 'inv', inv.name, 'payment entries', pay_moves.mapped('name'))
    # 1. accounting: unreconcile, reset, delete
    moves.line_ids.remove_move_reconcile()
    for m in moves.filtered(lambda m: m.state == 'posted'):
        super(pos_cls, m).button_draft()
    if moves:
        cr.execute("UPDATE pos_order SET account_move = NULL WHERE id = %s", (o.id,))
        cr.execute("UPDATE pos_payment SET account_move_id = NULL WHERE pos_order_id = %s", (o.id,))
        moves.with_context(force_delete=True).unlink()
    # 2. stock: put back what the delivery took, then delete it
    for p in o.picking_ids:
        for m in p.move_ids.filtered(lambda m: m.state == 'done'):
            for ml in m.move_line_ids:
                if ml.product_id.is_storable:
                    env['stock.quant']._update_available_quantity(ml.product_id, ml.location_id, ml.quantity)
                    env['stock.quant']._update_available_quantity(ml.product_id, ml.location_dest_id, -ml.quantity)
        cr.execute("DELETE FROM stock_move_line WHERE picking_id = %s", (p.id,))
        cr.execute("DELETE FROM stock_move WHERE picking_id = %s", (p.id,))
        cr.execute("DELETE FROM stock_picking WHERE id = %s", (p.id,))
    skus += o.lines.product_id.mapped('default_code')
    # 3. the order itself
    cr.execute("DELETE FROM pos_payment WHERE pos_order_id = %s", (o.id,))
    cr.execute("DELETE FROM pos_order_line WHERE order_id = %s", (o.id,))
    cr.execute("DELETE FROM pos_order WHERE id = %s", (o.id,))
env.invalidate_all()
for sku in sorted(set(skus)):
    q = env['stock.quant'].search([('product_id.default_code', '=', sku), ('location_id.usage', '=', 'internal'), ('quantity', '!=', 0)])
    print(sku, 'on hand', [(x.location_id.complete_name, x.quantity) for x in q])
print('left', env['pos.order'].search_count([('pos_reference', 'in', refs)]), 'orders')
if os.environ.get('COMMIT') == '1':
    cr.commit(); print('COMMITTED')
else:
    cr.rollback(); print('DRY RUN (add COMMIT=1)')

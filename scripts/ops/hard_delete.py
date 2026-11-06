# -*- coding: utf-8 -*-
# Copyright 2026 Revenax Digital Services
# Author: Mohamed A. Abdallah
#
# Odoo-shell script: HARD DELETE pieces (product + stock history + stock-count lines).
# Run via scripts/ops/run_odoo.sh with SKUS=A,B[,C] and COMMIT=1 to apply.
# Refuses any piece that has a POS line, invoice/bill line or purchase line
# (a sold piece must have its sale erased first, a different procedure).
# Afterwards also delete it from the ops app + S3: node scripts/ops/neon.js delete <SKUS...>
import os
COMMIT = os.environ.get('COMMIT') == '1'
SKUS = [s.strip() for s in os.environ['SKUS'].split(',') if s.strip()]
cr = env.cr
touched = env['jewellery.stock.count']
for SKU in SKUS:
    T = env['product.template'].with_context(active_test=False).search([('default_code', '=', SKU)])
    assert len(T) == 1, f'{SKU}: found {len(T)} templates'
    P = T.product_variant_ids
    docs = (env['pos.order.line'].search_count([('product_id', 'in', P.ids)])
            + env['account.move.line'].search_count([('product_id', 'in', P.ids)])
            + env['purchase.order.line'].search_count([('product_id', 'in', P.ids)]))
    assert not docs, f'{SKU}: has sales/purchase documents, refusing'
    quants = env['stock.quant'].search([('product_id', 'in', P.ids), ('location_id.usage', '=', 'internal')])
    lines = env['jewellery.stock.count.line'].search([('product_id', 'in', P.ids)])
    print(SKU, T.jewellery_type, [(q.location_id.complete_name, q.quantity) for q in quants],
          'count lines', [(l.count_id.name, l.status) for l in lines])
    touched |= lines.mapped('count_id')
    cr.execute("DELETE FROM stock_move_line WHERE product_id IN %s", (tuple(P.ids),))
    cr.execute("DELETE FROM stock_move WHERE product_id IN %s", (tuple(P.ids),))
    cr.execute("DELETE FROM stock_quant WHERE product_id IN %s", (tuple(P.ids),))
    env.invalidate_all()
    T.available_in_pos = False
    lines.unlink()
    T.unlink()
# Owner rule: a mini count left with no lines is deleted.
empty = touched.exists().filtered(lambda c: not c.line_ids and c.state != 'done')
takes = empty.mapped('take_id')
if empty:
    print('deleting empty counts', empty.mapped('name'))
    cr.execute("DELETE FROM jewellery_stock_count WHERE id IN %s", (tuple(empty.ids),))
    env.invalidate_all()
for c in touched.exists():
    print(' ', c.name, 'found', c.found_count, 'missing', c.missing_count, 'total', c.expected_count)
for t in takes:
    t._check_done()
    print(' ', t.name, t.state, t.mini_done, '/', t.mini_total, 'found', t.found_count, 'missing', t.missing_count, 'total', t.expected_count)
if COMMIT:
    cr.commit(); print('COMMITTED')
else:
    cr.rollback(); print('DRY RUN (add COMMIT=1)')

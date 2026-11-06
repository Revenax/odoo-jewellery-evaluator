# -*- coding: utf-8 -*-
# Copyright 2026 Revenax Digital Services
# Author: Mohamed A. Abdallah
#
# Odoo-shell script: move pieces to another location (internal move, no accounting effect).
#   scripts/ops/run_odoo.sh scripts/ops/move_pieces.py SKUS=DS-0059,DS-0060 TO=SM [DROP_COUNT=1] [COMMIT=1]
# TO = warehouse code (its Stock location). DROP_COUNT=1 also removes their lines
# from in-progress stock counts (the piece is no longer where that count looks).
# Afterwards: node scripts/ops/neon.js warehouse <TO> <SKUS...>
import os
COMMIT = os.environ.get('COMMIT') == '1'
SKUS = [s.strip() for s in os.environ['SKUS'].split(',') if s.strip()]
dest = env['stock.warehouse'].search([('code', '=', os.environ['TO'])]).lot_stock_id
assert dest, 'unknown warehouse'
for sku in SKUS:
    p = env['product.product'].search([('default_code', '=', sku)])
    assert len(p) == 1, sku
    qs = env['stock.quant'].search([('product_id', '=', p.id), ('location_id.usage', '=', 'internal'), ('quantity', '>', 0)])
    before = [(q.location_id.complete_name, q.quantity) for q in qs]
    for q in qs.filtered(lambda q: q.location_id != dest):
        q.move_quants(location_dest_id=dest, message='Moved by ops script')
    if os.environ.get('DROP_COUNT') == '1':
        env['jewellery.stock.count.line'].search([('product_id', '=', p.id), ('count_id.state', '=', 'in_progress')]).unlink()
    after = [(q.location_id.complete_name, q.quantity) for q in env['stock.quant'].search(
        [('product_id', '=', p.id), ('location_id.usage', '=', 'internal'), ('quantity', '!=', 0)])]
    print(sku, before, '->', after)
if COMMIT:
    env.cr.commit(); print('COMMITTED')
else:
    env.cr.rollback(); print('DRY RUN (add COMMIT=1)')

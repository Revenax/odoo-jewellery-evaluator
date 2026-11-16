# -*- coding: utf-8 -*-
# Copyright 2026 Revenax Digital Services
# Author: Mohamed A. Abdallah
# Website: https://www.revenax.com
"""Owners' warehouse (OW): one stock location per owner (2026-11-16).

OW/Stock (the warehouse's main stock location, 26 pieces) is renamed
OW/Anas; OW/Omar, OW/Ahmed and OW/Mohamed are created beside it. Idempotent.
Run with scripts/ops/run_odoo.sh; rolls back unless COMMIT=1.
"""
import os

COMMIT = os.environ.get('COMMIT') == '1'
Loc = env['stock.location'].sudo()
wh = env['stock.warehouse'].sudo().search([('code', '=', 'OW')])
assert len(wh) == 1, 'warehouse OW not found'
main = wh.lot_stock_id
if main.name == 'Stock':
    main.name = 'Anas'
    print('RENAMED', main.id, '-> ', main.complete_name)
for owner in ('Omar', 'Ahmed', 'Mohamed'):
    loc = Loc.with_context(active_test=False).search([('location_id', '=', wh.view_location_id.id), ('name', '=', owner)])
    if not loc:
        loc = Loc.create({'name': owner, 'location_id': wh.view_location_id.id, 'usage': 'internal',
                          'company_id': wh.company_id.id})
        print('CREATED', loc.id, loc.complete_name)
    elif not loc.active:
        loc.active = True
        print('UNARCHIVED', loc.id, loc.complete_name)
for loc in Loc.search([('warehouse_id', '=', wh.id), ('usage', '=', 'internal')], order='complete_name'):
    pieces = sum(env['stock.quant'].sudo().search([('location_id', '=', loc.id), ('quantity', '>', 0)]).mapped('quantity'))
    print('LOCATION', loc.id, loc.complete_name, 'on hand', pieces)
if COMMIT:
    env.cr.commit()
    print('COMMITTED')
else:
    env.cr.rollback()
    print('ROLLED BACK (dry run)')

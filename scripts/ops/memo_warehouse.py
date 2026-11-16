# -*- coding: utf-8 -*-
# Copyright 2026 Revenax Digital Services
# Author: Mohamed A. Abdallah
# Website: https://www.revenax.com
"""Warehouse "On Memo" (OM, برانية), 2026-11-16: pieces handed to other
traders on approval, still Marjaan's stock until they come back or are paid.
Odoo creates OM/Stock with it. Idempotent; rolls back unless COMMIT=1.
The web shop never lists a piece held here (jewellery_website).
"""
import os

COMMIT = os.environ.get('COMMIT') == '1'
WH = env['stock.warehouse'].sudo()
wh = WH.with_context(active_test=False).search([('code', '=', 'OM')])
if not wh:
    wh = WH.create({'name': 'On Memo', 'code': 'OM', 'company_id': env.company.id,
                    'partner_id': env.company.partner_id.id})
    print('CREATED', wh.id, wh.name, wh.code)
print('WAREHOUSE', wh.id, wh.name, wh.code, 'stock location', wh.lot_stock_id.complete_name)
if COMMIT:
    env.cr.commit()
    print('COMMITTED')
else:
    env.cr.rollback()
    print('ROLLED BACK (dry run)')

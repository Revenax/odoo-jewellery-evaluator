# -*- coding: utf-8 -*-
# Copyright 2026 Revenax Digital Services
# Author: Mohamed A. Abdallah
# Website: https://www.revenax.com
"""Odoo-shell script: move pieces off a posted (paid) customer invoice onto their own invoice.

    scripts/ops/run_odoo.sh scripts/ops/split_invoice.py INVOICE=MJ-1617 SKUS=GDF8-0003 [COMMIT=1]

The payment is unreconciled, the lines are removed from the original (reset to
draft, edit, repost), a new invoice with the same customer, date, prices and
reference is posted for them, and the original payment is reconciled against both,
so both read paid. Stock is NOT touched: the pieces already left stock with the
original sale (POS delivery or invoice deduction), so the new invoice is flagged as
already deducted. The POS order, if any, keeps all its lines; works while its session
is still open (the close only uses the POS payment amounts).
"""
import os

inv = env['account.move'].search([('name', '=', os.environ['INVOICE'])])
skus = os.environ['SKUS'].split(',')
assert len(inv) == 1 and inv.move_type == 'out_invoice' and inv.state == 'posted', inv
moving = inv.invoice_line_ids.filtered(lambda l: l.product_id.default_code in skus)
assert len(moving) == len(skus), 'not all SKUs on the invoice'
vals = [{'product_id': l.product_id.id, 'name': l.name, 'quantity': l.quantity,
         'price_unit': l.price_unit, 'discount': l.discount, 'tax_ids': [(6, 0, l.tax_ids.ids)]}
        for l in moving]
receivable = inv.line_ids.filtered(lambda l: l.account_id.account_type == 'asset_receivable')
counterparts = receivable.matched_credit_ids.credit_move_id
print('before', inv.name, inv.amount_total, inv.payment_state, 'paid by', counterparts.move_id.mapped('name'))
receivable.remove_move_reconcile()
# point_of_sale refuses button_draft while the order's session is open. Its only
# purpose is the session close, which reconciles the POS payment side (pos.payment
# amounts), never the invoice amounts; the invoice side stays fully reconciled
# here against the same payment entry, so skip just that one check.
pos_cls = next(c for c in type(inv).__mro__ if c.__module__.endswith('point_of_sale.models.account_move'))
super(pos_cls, inv).button_draft()
assert inv.state == 'draft', inv.state
inv.write({'invoice_line_ids': [(2, l.id) for l in moving]})
inv.action_post()
new = env['account.move'].create({
    'move_type': 'out_invoice', 'partner_id': inv.partner_id.id, 'invoice_date': inv.invoice_date,
    'date': inv.date, 'ref': inv.ref, 'invoice_origin': inv.invoice_origin, 'journal_id': inv.journal_id.id,
    'currency_id': inv.currency_id.id, 'invoice_user_id': inv.invoice_user_id.id,
    'invoice_line_ids': [(0, 0, v) for v in vals],
})
if 'jewellery_stock_deducted' in new._fields:
    new.jewellery_stock_deducted = True  # the pieces already left stock with the original sale
new.action_post()
lines = (inv | new).line_ids.filtered(lambda l: l.account_id.account_type == 'asset_receivable') | counterparts
lines.reconcile()
env.invalidate_all()
for m in (inv, new):
    print(m.name, m.amount_total, m.payment_state, [(l.product_id.default_code, l.price_subtotal) for l in m.invoice_line_ids],
          'cogs', round(sum(m.line_ids.filtered(lambda l: l.display_type == 'cogs' and l.debit and l.account_id.code.startswith('4')).mapped('debit')), 2))
for sku in skus:
    p = env['product.product'].search([('default_code', '=', sku)])
    print(sku, 'on hand', [(q.location_id.complete_name, q.quantity) for q in env['stock.quant'].search([('product_id', '=', p.id), ('location_id.usage', '=', 'internal')])])
if os.environ.get('COMMIT') == '1':
    env.cr.commit(); print('COMMITTED')
else:
    env.cr.rollback(); print('DRY RUN (add COMMIT=1)')

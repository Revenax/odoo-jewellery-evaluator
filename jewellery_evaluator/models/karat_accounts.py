# -*- coding: utf-8 -*-
# Copyright 2026 Revenax Digital Services
# Author: Mohamed A. Abdallah
# Website: https://www.revenax.com
"""Book gold by karat, and split every gold/silver sale into metal and making fee.

Accounts come from ``utils.jewellery_account_codes``: a gold piece's stock,
sales and cost of goods sold sit on its karat's accounts (24K, 21K, 18K)
whatever its category, and silver on the silver accounts. Purchases (buy-backs,
supplier bills) land on the karat's inventory, sales on its metal sales
account, and the cost of goods sold on its karat's cost account.

On the invoice, what the customer paid above the piece's metal value (its cost
of goods sold on the day of sale) is moved from the metal sales account to the
making fee account of its kind (gold jewellery, gold bullion, silver). Those
two lines are added with Odoo's own cost-of-goods-sold lines, so they never
show on the printed invoice, are removed when the invoice is reset to draft,
and are rebuilt when it is posted again.

Pieces without karat accounts (diamonds, center stones, a gold piece with no
karat) keep their category's accounts.
"""

from collections import defaultdict

from odoo import models

from ..utils import jewellery_account_codes, making_fee_split


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    def _jewellery_account(self, code):
        return self.env['account.account'].sudo().search(
            [('code', '=', code), ('company_ids', 'in', self.env.company.id)], limit=1)

    def _get_product_accounts(self):
        accounts = super()._get_product_accounts()
        codes = jewellery_account_codes(self.jewellery_type, self.gold_purity)
        if not codes:
            return accounts
        for key, code in (('income', codes['income']), ('expense', codes['expense']),
                          ('stock_valuation', codes['stock'])):
            account = self._jewellery_account(code)
            if account:
                accounts[key] = account
        if accounts.get('stock_valuation'):
            accounts['stock_variation'] = accounts['stock_valuation'].account_stock_variation_id
        return accounts


class AccountMove(models.Model):
    _inherit = 'account.move'

    def _stock_account_prepare_realtime_out_lines_vals(self):
        vals_list = super()._stock_account_prepare_realtime_out_lines_vals()
        # Cost of goods sold per invoice line: the expense side of its COGS pair.
        cost: defaultdict = defaultdict(float)
        for vals in vals_list:
            line = self.env['account.move.line'].browse(vals['cogs_origin_id'])
            accounts = line.product_id.product_tmpl_id.get_product_accounts(
                fiscal_pos=line.move_id.fiscal_position_id)
            if vals['account_id'] != accounts['stock_valuation'].id:
                cost[line] += vals['amount_currency']
        Template = self.env['product.template']
        for line, metal in cost.items():
            tmpl = line.product_id.product_tmpl_id
            codes = jewellery_account_codes(tmpl.jewellery_type, tmpl.gold_purity)
            fee_account = codes and Template._jewellery_account(codes['making_fee'])
            if not fee_account:
                continue
            _metal, fee = making_fee_split(-line.amount_currency, metal)
            if line.move_id.currency_id.is_zero(fee):
                continue
            common = {
                'name': ('Making fee: ' + (line.name or ''))[:64],
                'move_id': line.move_id.id,
                'partner_id': line.move_id.commercial_partner_id.id,
                'product_id': line.product_id.id,
                'product_uom_id': line.product_uom_id.id,
                'quantity': line.quantity,
                'analytic_distribution': line.analytic_distribution,
                'display_type': 'cogs',
                'tax_ids': [],
                'cogs_origin_id': line.id,
            }
            vals_list.append({**common, 'account_id': line.account_id.id, 'amount_currency': fee})
            vals_list.append({**common, 'account_id': fee_account.id, 'amount_currency': -fee})
        return vals_list

# -*- coding: utf-8 -*-
# Copyright 2026 Revenax Digital Services
# Author: Mohamed A. Abdallah
# Website: https://www.revenax.com
"""Carry each jewellery piece at today's metal (and stone) value.

A piece's cost (``standard_price``) is its metal at today's price plus its
stones (``utils.inventory_cost_egp``). It is re-marked:

* once a night for every piece in stock, after which the stock valuation is
  closed, so the balance sheet shows stock at that day's price and the
  change lands in the revaluation account;
* right before a piece is sold (POS picking, customer invoice post), so the
  sale posts cost of goods sold at the price of the day of sale.

The same nightly run sets today's USD/SAR/AED rates from the price feed.

Only matters for categories with real-time (perpetual) valuation; on periodic
categories a changed cost has no accounting effect. Re-marking never blocks a
sale: a failure is logged and the sale goes ahead at the previous cost.
"""

import logging

from odoo import api, fields, models

from ..utils import inventory_cost_egp, pegged_currency_rates

_logger = logging.getLogger(__name__)


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    def _jewellery_cost_context(self):
        """The day's prices shared by every piece in one re-mark run."""
        try:
            base_21k = self.env['gold.price.service'].get_current_gold_price()
        except Exception:
            base_21k = 0.0
        usd_rate = self._diamond_pricing_config()[0]
        return {'base_21k': base_21k, 'usd_rate': usd_rate}

    def _jewellery_inventory_cost(self, prices):
        self.ensure_one()
        jtype = self.jewellery_type
        metal = self.silver_cost_price if jtype == 'silver' else self.gold_cost_price
        return inventory_cost_egp(
            jtype,
            metal_cost_egp=metal,
            base_gold_price_21k=prices['base_21k'],
            gold_purity=self.gold_purity,
            gold_weight_g=self.jewellery_weight_g,
            stones_cost_usd=sum(s.total_price_usd for s in self.stone_ids if s.total_price_usd > 0),
            usd_rate=prices['usd_rate'],
        )

    def _jewellery_mark_cost(self):
        """Set ``standard_price`` of these pieces to today's cost.

        Returns the number of pieces whose cost changed. Pieces whose cost is
        unknown (no gold price, no weight) keep their previous cost.
        """
        pieces = self.filtered(lambda t: t.jewellery_type and t.is_storable)
        if not pieces:
            return 0
        prices = self._jewellery_cost_context()
        changed = 0
        for tmpl in pieces:
            cost = tmpl._jewellery_inventory_cost(prices)
            if cost is None:
                continue
            for product in tmpl.product_variant_ids:
                if abs(product.standard_price - cost) >= 0.01:
                    product.standard_price = cost
                    changed += 1
        return changed

    def _jewellery_mark_cost_safely(self):
        """Re-mark before a sale without ever blocking the sale."""
        try:
            with self.env.cr.savepoint():
                self.sudo()._jewellery_mark_cost()
        except Exception:
            _logger.exception('[costing] could not re-mark cost of %s before sale', self.ids)

    @api.model
    def _update_currency_rates(self):
        """Today's USD, SAR and AED rates from the price feed's USD/EGP quote.

        One rate per currency per day (an existing one for today is updated).
        Skipped when the feed has no quote, so the last good rate stays.
        """
        usd_egp = float(self.env['ir.config_parameter'].sudo().get_param(
            'jewellery_evaluator.feed_usd_egp') or 0)
        try:
            rates = pegged_currency_rates(usd_egp)
        except ValueError:
            _logger.warning('[costing] no USD/EGP from the price feed; currency rates unchanged')
            return
        today = fields.Date.context_today(self)
        Rate = self.env['res.currency.rate'].sudo()
        for company in self.env['res.company'].search([]):
            for code, rate in rates.items():
                currency = self.env['res.currency'].with_context(active_test=False).search(
                    [('name', '=', code)], limit=1)
                if not currency or currency == company.currency_id:
                    continue
                existing = Rate.search([('currency_id', '=', currency.id), ('name', '=', today),
                                        ('company_id', '=', company.id)], limit=1)
                if existing:
                    existing.rate = rate
                else:
                    Rate.create({'currency_id': currency.id, 'name': today,
                                 'company_id': company.id, 'rate': rate})

    @api.model
    def cron_mark_inventory_cost(self):
        """Nightly: today's currency rates, re-mark every piece in stock, then
        close the stock valuation."""
        self._update_currency_rates()
        self.env.cr.execute("""
            SELECT DISTINCT pp.product_tmpl_id
              FROM stock_quant q
              JOIN stock_location l ON l.id = q.location_id
              JOIN product_product pp ON pp.id = q.product_id
             WHERE l.usage = 'internal' AND q.quantity > 0
        """)
        tmpl_ids = [row[0] for row in self.env.cr.fetchall()]
        changed = 0
        for start in range(0, len(tmpl_ids), 200):
            batch = self.browse(tmpl_ids[start:start + 200])
            changed += batch._jewellery_mark_cost()
            self.env.cr.commit()
        _logger.info('[costing] re-marked %s of %s pieces in stock', changed, len(tmpl_ids))
        for company in self.env['res.company'].search([]):
            try:
                company.with_context(closing_cron=True).action_close_stock_valuation(auto_post=True)
            except Exception:
                _logger.exception('[costing] stock valuation closing failed for %s', company.name)
        return changed


class PosOrder(models.Model):
    _inherit = 'pos.order'

    def _create_order_picking(self):
        self.lines.product_id.product_tmpl_id._jewellery_mark_cost_safely()
        return super()._create_order_picking()


class AccountMove(models.Model):
    _inherit = 'account.move'

    def _post(self, soft=True):
        sales = self.filtered(lambda m: m.move_type in ('out_invoice', 'out_refund'))
        if sales:
            sales.invoice_line_ids.product_id.product_tmpl_id._jewellery_mark_cost_safely()
        return super()._post(soft=soft)

# -*- coding: utf-8 -*-
# Copyright 2026 Revenax Digital Services
# Author: Mohamed A. Abdallah
# Website: https://www.revenax.com
"""Gold karats and silver as currencies, rated from the evaluator's prices.

G24 / G21 / G18 / S99 (data/metal_currencies.xml) are one gram each. Odoo
stores a rate as units of the currency per 1 unit of company currency, so the
rate is grams per EGP = 1 / price per gram. The gold cron calls this with the
accepted 21K base each run, the silver cron with silver 999: one rate per
currency per company per day, today's row updated in place, written only when
the price moved. Never raises: pricing must not fail over a rate.
"""
import logging

from odoo import api, fields, models

from ..utils import metal_currency_rates

_logger = logging.getLogger(__name__)


class ResCurrency(models.Model):
    _inherit = 'res.currency'

    @api.model
    def _jewellery_sync_metal_rates(self, base_21k_egp=None, silver_999_egp=None):
        rates = metal_currency_rates(base_21k_egp, silver_999_egp)
        if not rates:
            return 0
        written = 0
        try:
            with self.env.cr.savepoint():
                written = self._jewellery_write_rates(rates)
        except Exception:
            _logger.exception('[metal-currency] could not update rates %s', rates)
        return written

    @api.model
    def _jewellery_write_rates(self, rates):
        today = fields.Date.context_today(self)
        Rate = self.env['res.currency.rate'].sudo()
        currencies = self.sudo().with_context(active_test=False).search([('name', 'in', list(rates))])
        written = 0
        for company in self.env['res.company'].sudo().search([]):
            for currency in currencies:
                rate = rates[currency.name]
                existing = Rate.search([('currency_id', '=', currency.id), ('name', '=', today),
                                        ('company_id', '=', company.id)], limit=1)
                if existing:
                    # 1e-9 relative: a price unchanged to the piastre is no write.
                    if abs(existing.rate - rate) > rate * 1e-9:
                        existing.rate = rate
                        written += 1
                else:
                    Rate.create({'currency_id': currency.id, 'name': today,
                                 'company_id': company.id, 'rate': rate})
                    written += 1
        return written

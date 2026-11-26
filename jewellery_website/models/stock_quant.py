# -*- coding: utf-8 -*-
# Copyright 2026 Revenax Digital Services
# Author: Mohamed A. Abdallah
# Website: https://www.revenax.com
"""A sold piece leaves the website at once, not at the next catalogue run.

Every stock change (POS sale, invoice deduction, delivery, web-order reservation,
transfer, count) writes stock.quant. The touched pieces are collected for the
transaction and the catalogue sync runs for just those right before commit, so a
piece is unpublished in the same transaction that sold it. A failure there is
logged and never blocks the sale; the 15-minute cron is the backstop.
"""
import logging

from odoo import api, models

_logger = logging.getLogger(__name__)

_KEY = 'jewellery_website.touched_templates'


class StockQuant(models.Model):
    _inherit = 'stock.quant'

    @api.model_create_multi
    def create(self, vals_list):
        quants = super().create(vals_list)
        quants._jewellery_queue_website_sync()
        return quants

    def write(self, vals):
        res = super().write(vals)
        if {'quantity', 'reserved_quantity', 'location_id', 'inventory_quantity_set'} & set(vals):
            self._jewellery_queue_website_sync()
        return res

    def _jewellery_queue_website_sync(self):
        tmpl_ids = set(self.sudo().mapped('product_id.product_tmpl_id').ids)
        if not tmpl_ids:
            return
        data = self.env.cr.precommit.data
        pending = data.get(_KEY)
        if pending is None:
            pending = data[_KEY] = set()
            env = self.env

            def flush():
                ids = data.pop(_KEY, set())
                if not ids:
                    return
                try:
                    with env.cr.savepoint():
                        env['product.template'].sudo().cron_sync_website_catalog(template_ids=ids)
                except Exception:  # noqa: BLE001 - the 15-minute cron retries
                    _logger.exception('[website-catalog] immediate sync failed for %s', sorted(ids))

            self.env.cr.precommit.add(flush)
        pending.update(tmpl_ids)

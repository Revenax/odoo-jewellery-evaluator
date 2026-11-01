# -*- coding: utf-8 -*-
# Copyright 2026 Revenax Digital Services
# Author: Mohamed A. Abdallah
# Website: https://www.revenax.com
"""Today's prices for the banner above the POS product grid.

Reads the values the pricing itself uses (the gold cron's 21K price, the
silver 999 price, the shop's USD/EGP), so the banner can never disagree with
what the till charges. Buy prices are the feed's bid side. Read-only.
"""

import requests
from odoo import api, models

from ..utils import gold_price_for_purity, price_board


class PosSessionPriceBoard(models.Model):
    _inherit = 'pos.session'

    @api.model
    def get_jewellery_price_board(self):
        icp = self.env['ir.config_parameter'].sudo()

        def num(key):
            try:
                return float(icp.get_param(key) or 0)
            except (TypeError, ValueError):
                return 0.0

        base_21k = num('jewellery_evaluator.fallback_price')
        usd = num('jewellery_evaluator.diamond_exchange_rate_usd') or num('jewellery_evaluator.feed_usd_egp')
        sell = {
            'gold_24k': gold_price_for_purity(base_21k, '24K'),
            'gold_21k': gold_price_for_purity(base_21k, '21K'),
            'gold_18k': gold_price_for_purity(base_21k, '18K'),
            'silver_999': num('jewellery_evaluator.silver_fallback_price'),
            'usd_egp': usd,
        }
        snapshot = None
        url = self.env['gold.price.service']._price_feed_url()
        if url:
            try:
                snapshot = requests.get(url, timeout=3).json()
            except (requests.exceptions.RequestException, ValueError):
                snapshot = None
        return price_board(snapshot, sell)

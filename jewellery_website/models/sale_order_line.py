# -*- coding: utf-8 -*-
# Copyright 2026 Revenax Digital Services
# Author: Mohamed A. Abdallah
# Website: https://www.revenax.com
from odoo import models


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    def _compute_name_short(self):
        """Cart and checkout show the website title, not the bare SKU."""
        super()._compute_name_short()
        for line in self:
            title = line.product_id.product_tmpl_id.website_title
            if title:
                line.name_short = title

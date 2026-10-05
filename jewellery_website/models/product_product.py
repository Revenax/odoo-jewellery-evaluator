# -*- coding: utf-8 -*-
# Copyright 2026 Revenax Digital Services
# Author: Mohamed A. Abdallah
# Website: https://www.revenax.com
from odoo import models


class ProductProduct(models.Model):
    _inherit = 'product.product'

    def get_product_multiline_description_sale(self):
        """Website order lines read "[SKU] 18K Gold Ring · 4.45 g", not "[SKU] SKU"."""
        description = super().get_product_multiline_description_sale()
        title = self.product_tmpl_id.website_title
        if not title or title == self.name:
            return description
        # First line is "[SKU] name"; the name IS the SKU, so rebuild that line
        # rather than string-replace (which would hit the SKU inside the brackets).
        _first, sep, rest = description.partition('\n')
        head = f'[{self.default_code}] {title}' if self.default_code else title
        return head + sep + rest

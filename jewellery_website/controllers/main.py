# -*- coding: utf-8 -*-
# Copyright 2026 Revenax Digital Services
# Author: Mohamed A. Abdallah
# Website: https://www.revenax.com
from odoo.addons.website_sale.controllers.main import WebsiteSale


class JewelleryWebsiteSale(WebsiteSale):

    def order_lines_2_google_api(self, order_lines):
        """Purchase analytics name each piece by its title and SKU, not the till
        name (products are named by SKU, so stock items read "DRL8-0149")."""
        items = super().order_lines_2_google_api(order_lines)
        lines = order_lines.filtered(lambda line: not line.is_delivery)
        for item, line in zip(items, lines, strict=True):
            product = line.product_id
            item['item_id'] = product.default_code or item['item_id']
            item['item_name'] = product.website_title or item['item_name']
            item['item_category'] = product.categ_id.complete_name or item['item_category']
        return items

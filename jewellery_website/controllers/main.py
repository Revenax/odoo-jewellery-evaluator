# -*- coding: utf-8 -*-
# Copyright 2026 Revenax Digital Services
# Author: Mohamed A. Abdallah
# Website: https://www.revenax.com
from odoo.addons.website_sale.controllers.main import WebsiteSale
from odoo.addons.website_sale.controllers.variant import WebsiteSaleVariantController
from odoo.http import request, route

from ..website_utils import website_price_display


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


class JewelleryVariantController(WebsiteSaleVariantController):

    @route()
    def get_combination_info_website(self, *args, **kwargs):
        """The product page re-renders its price in JS from this payload. Odoo
        sets currency_precision here (after the model computes the info), so
        whole EGP prices printed "514,700.00"; match the server-rendered
        "514,700 EGP" instead."""
        info = super().get_combination_info_website(*args, **kwargs)
        currency = request.website.currency_id
        info['currency_precision'] = max(
            website_price_display(info.get(key) or 0, currency.decimal_places, currency.name, currency.symbol)[0]
            for key in ('price', 'list_price')
        )
        return info

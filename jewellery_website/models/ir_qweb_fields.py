# -*- coding: utf-8 -*-
# Copyright 2026 Revenax Digital Services
# Author: Mohamed A. Abdallah
# Website: https://www.revenax.com
from odoo import api, models
from odoo.http import request

from ..website_utils import website_price_display

NBSP = '\N{NO-BREAK SPACE}'
# Website routes that print accounting documents keep the accounting format.
_DOCUMENT_PATHS = ('/my', '/report')


def _is_shop_page():
    return bool(
        request and getattr(request, 'is_frontend', False)
        and not request.httprequest.path.startswith(_DOCUMENT_PATHS)
    )


class IrQwebFieldMonetary(models.AbstractModel):
    _inherit = 'ir.qweb.field.monetary'

    @api.model
    def value_to_html(self, value, options):
        """Shop prices read "37,500 EGP", not "37,500.00 LE". Website pages
        only: invoices, receipts and the backend keep the currency's own
        symbol and decimals."""
        currency = options.get('display_currency')
        if not (currency and isinstance(value, (int, float)) and _is_shop_page()):
            return super().value_to_html(value, options)
        places, label = website_price_display(value, currency.decimal_places, currency.name, currency.symbol)
        html = super().value_to_html(value, {**options, 'decimal_places': places})
        if currency.symbol and label != currency.symbol:
            if currency.position == 'after':
                html = html.replace(NBSP + currency.symbol, NBSP + label)
            else:
                html = html.replace(currency.symbol + NBSP, label + NBSP)
        return html

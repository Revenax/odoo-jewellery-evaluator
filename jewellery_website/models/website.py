# -*- coding: utf-8 -*-
# Copyright 2026 Revenax Digital Services
# Author: Mohamed A. Abdallah
# Website: https://www.revenax.com
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

from ..website_utils import WEBSITE_CURRENCY_LABEL


class Website(models.Model):
    _inherit = 'website'

    meta_pixel_id = fields.Char(
        string='Meta Pixel ID',
        help='Facebook/Instagram ads pixel. Loaded only after the visitor accepts '
             'optional cookies, like Google Analytics.',
    )

    @api.constrains('meta_pixel_id')
    def _check_meta_pixel_id(self):
        # It is printed into a <script>: only ever a plain number.
        for website in self:
            if website.meta_pixel_id and not website.meta_pixel_id.isdigit():
                raise ValidationError(_('The Meta Pixel ID is a number, e.g. 1234567890123456.'))

    def _shop_currency_label(self):
        """"EGP" on the storefront, the accounting symbol ("LE") elsewhere."""
        self.ensure_one()
        return WEBSITE_CURRENCY_LABEL.get(self.currency_id.name, self.currency_id.symbol)

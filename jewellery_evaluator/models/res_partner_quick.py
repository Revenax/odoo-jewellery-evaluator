# -*- coding: utf-8 -*-
# Copyright 2026 Revenax Digital Services
# Author: Mohamed A. Abdallah
# Website: https://www.revenax.com
"""Quick customer form for the register: Name, Phone, Email, with every other
field behind a "More details" switch (views/res_partner_quick_views.xml; the
register opens it instead of Odoo's full contact form, pos_quick_partner.js).
Phone numbers are saved in Egyptian local form (utils.local_eg_phone)."""

from odoo import api, fields, models

from ..utils import local_eg_phone


class ResPartner(models.Model):
    _inherit = 'res.partner'

    jewellery_more_details = fields.Boolean(
        'More details', compute='_compute_jewellery_more_details',
        inverse='_inverse_jewellery_more_details', store=False, readonly=False,
        help='Show the address and other details on the quick customer form.')

    @api.depends_context('uid')
    def _compute_jewellery_more_details(self):
        for partner in self:
            partner.jewellery_more_details = False

    def _inverse_jewellery_more_details(self):
        """A form-only switch: nothing is stored."""

    # Every Egyptian number is saved in local form (010..., 02...), however it
    # was typed (+20, 0020, spaces, Arabic digits). Foreign/invalid ones stay.
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('phone'):
                vals['phone'] = local_eg_phone(vals['phone'])
        return super().create(vals_list)

    def write(self, vals):
        if vals.get('phone'):
            vals = dict(vals, phone=local_eg_phone(vals['phone']))
        return super().write(vals)

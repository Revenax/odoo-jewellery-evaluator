# -*- coding: utf-8 -*-
# Copyright 2026 Revenax Digital Services
# Author: Mohamed A. Abdallah
# Website: https://www.revenax.com

from odoo import fields, models


class JewelleryInventoryCount(models.Model):
    _name = 'jewellery.inventory.count'
    _description = 'Jewellery Inventory Count'
    _order = 'count_date desc, id desc'

    name = fields.Char(
        string='Reference',
        required=True,
        default='New',
        help='Label for this stock-count entry.',
    )
    product_tmpl_id = fields.Many2one(
        comodel_name='product.template',
        string='Product',
        required=True,
        ondelete='cascade',
        index=True,
    )
    jewellery_type = fields.Selection(
        related='product_tmpl_id.jewellery_type',
        string='Jewellery Type',
        readonly=True,
        store=False,
    )
    counted_qty = fields.Float(
        string='Counted Qty',
        digits=(16, 2),
        help='Physical quantity counted on hand.',
    )
    count_date = fields.Date(
        string='Count Date',
        default=fields.Date.context_today,
    )
    note = fields.Text(string='Notes')

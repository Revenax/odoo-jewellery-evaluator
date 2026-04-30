# -*- coding: utf-8 -*-
# Copyright 2026 Revenax Digital Services
# Author: Mohamed A. Abdallah
# Website: https://www.revenax.com

from odoo import api, fields, models
from odoo.exceptions import ValidationError

from ..utils import get_stone_tier_price

# GIA colour scale (D = best, N = lower commercial grade)
STONE_COLOR_SELECTION = [
    ('D', 'D'), ('E', 'E'), ('F', 'F'),
    ('G', 'G'), ('H', 'H'), ('I', 'I'),
    ('J', 'J'), ('K', 'K'), ('L', 'L'),
    ('M', 'M'), ('N', 'N'),
]

STONE_SHAPE_SELECTION = [
    ('Round', 'Round'),
    ('Oval', 'Oval'),
    ('Marquise', 'Marquise'),
    ('Pear', 'Pear'),
    ('Heart', 'Heart'),
    ('Emerald', 'Emerald'),
    ('Princess', 'Princess'),
    ('Radiant', 'Radiant'),
]

# GIA clarity scale
STONE_CLARITY_SELECTION = [
    ('LC', 'LC'),
    ('VVS1', 'VVS1'), ('VVS2', 'VVS2'),
    ('VS1', 'VS1'),   ('VS2', 'VS2'),
    ('SI1', 'SI1'),   ('SI2', 'SI2'),
    ('P1', 'P1'),     ('P2', 'P2'),     ('P3', 'P3'),
]


class JewelleryStone(models.Model):
    _name = 'jewellery.stone'
    _description = 'Diamond / Gemstone'
    _order = 'product_tmpl_id, sequence, id'

    product_tmpl_id = fields.Many2one(
        comodel_name='product.template',
        string='Product',
        required=True,
        ondelete='cascade',
        index=True,
    )
    sequence = fields.Integer(default=10)

    carat = fields.Float(
        string='Carat',
        required=True,
        digits=(6, 3),
        help='Stone weight in carats (0.001 – 7.000). '
             'Stones at or above 0.260 ct require manual pricing.',
    )
    color = fields.Selection(
        selection=STONE_COLOR_SELECTION,
        string='Colour',
        help='GIA colour grade: D (colourless) → N (light colour).',
    )
    cut = fields.Char(string='Cut')
    shape = fields.Selection(
        selection=STONE_SHAPE_SELECTION,
        string='Shape',
    )
    clarity = fields.Selection(
        selection=STONE_CLARITY_SELECTION,
        string='Clarity',
        help='GIA clarity grade.',
    )

    unit_price_usd = fields.Float(
        string='Price (USD)',
        digits=(16, 2),
        compute='_compute_unit_price_usd',
        store=True,
        help='Per-carat tier price × carat weight (USD). Zero when manual pricing is required.',
    )
    requires_manual_pricing = fields.Boolean(
        string='Manual Pricing?',
        compute='_compute_unit_price_usd',
        store=True,
        help='True when the stone carat is ≥ 0.260 — price must be set manually.',
    )

    @api.constrains('carat')
    def _check_carat_range(self):
        for stone in self:
            if not (0.001 <= stone.carat <= 7.000):
                raise ValidationError(
                    f'Carat must be between 0.001 and 7.000 (got {stone.carat:.3f}).'
                )

    @api.depends('carat')
    def _compute_unit_price_usd(self):
        for stone in self:
            price, manual = get_stone_tier_price(self.env, stone.carat)
            stone.unit_price_usd = price or 0.0
            stone.requires_manual_pricing = manual

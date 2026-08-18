# -*- coding: utf-8 -*-
# Copyright 2026 Revenax Digital Services
# Author: Mohamed A. Abdallah
# Website: https://www.revenax.com

from odoo import api, fields, models
from odoo.exceptions import ValidationError

from ..utils import (
    CARAT_DECIMALS,
    CARAT_MAX,
    CARAT_MIN,
    format_diamond_note,
    get_stone_price_usd,
    total_carat_for,
)

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
        string='Carat / Stone',
        required=True,
        digits=(7, CARAT_DECIMALS),
        help='Carat weight of ONE stone (cps), 0.000001 – 9.999999. '
             'For several identical stones enter the per-stone weight here and '
             'the count in Qty; Total Carat is worked out for you.',
    )
    total_carat = fields.Float(
        string='Total Carat',
        digits=(12, CARAT_DECIMALS),
        compute='_compute_total_carat',
        store=True,
        help='Carat / Stone × Qty — the total carat weight of this line.',
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
    quantity = fields.Integer(
        string='Qty',
        default=1,
        required=True,
        help='Number of identical stones with this specification. '
             'Avoids manual duplication when multiple stones are identical.',
    )

    unit_price_usd = fields.Float(
        string='Unit Price (USD)',
        digits=(16, 2),
        compute='_compute_unit_price_usd',
        store=True,
        help='Per-carat tier price × carat weight (USD).',
    )
    total_price_usd = fields.Float(
        string='Total Price (USD)',
        digits=(16, 2),
        compute='_compute_unit_price_usd',
        store=True,
        help='Unit price × quantity (USD). Sum this across all stones to get total stones cost.',
    )

    invoice_display = fields.Char(
        string='Invoice Line',
        compute='_compute_invoice_display',
        help="How this stone reads on the invoice: '17 DR 0.29CT' — count, D for "
             "diamond, the shape letter, then the total carat for the line.",
    )

    @api.depends('carat', 'quantity', 'shape')
    def _compute_invoice_display(self):
        # Same formatter as product.invoice_diamond_note, so the per-stone row
        # on the invoice and the summary note can never drift apart.
        for stone in self:
            stone.invoice_display = format_diamond_note([{
                'carat': stone.carat,
                'quantity': stone.quantity,
                'shape': stone.shape,
            }])

    @api.depends('carat', 'quantity')
    def _compute_total_carat(self):
        for stone in self:
            stone.total_carat = total_carat_for(stone.carat, stone.quantity)

    @api.constrains('carat')
    def _check_carat_range(self):
        for stone in self:
            if not (CARAT_MIN <= stone.carat <= CARAT_MAX):
                raise ValidationError(
                    f'Carat / Stone must be between {CARAT_MIN:.6f} and '
                    f'{CARAT_MAX:.6f} (got {stone.carat:.6f}). Note this is the '
                    f'weight of ONE stone, not the total for the line.'
                )

    @api.constrains('quantity')
    def _check_quantity_positive(self):
        for stone in self:
            if stone.quantity < 1:
                raise ValidationError(
                    f'Quantity must be at least 1 (got {stone.quantity}).'
                )

    @api.depends('carat', 'quantity', 'shape', 'color', 'clarity')
    def _compute_unit_price_usd(self):
        # < 0.25 ct -> 5 carat tiers; >= 0.25 ct -> Rapaport grid (Round/Pear),
        # falling back to the tier price when the grid has no matching cell.
        # NB: the compute cannot @api.depends on the Rap config grid, so a grid
        # edit is propagated by the editor's save (which recomputes stones) and,
        # for prices, by the diamond cron.
        for stone in self:
            price = get_stone_price_usd(
                self.env, stone.shape, stone.carat, stone.color, stone.clarity
            )
            stone.unit_price_usd = price
            stone.total_price_usd = price * stone.quantity

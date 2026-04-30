# -*- coding: utf-8 -*-
# Copyright 2026 Revenax Digital Services
# Author: Mohamed A. Abdallah
# Website: https://www.revenax.com

from odoo import api, fields, models

# Same selections as product.template for display on invoice
GOLD_PURITY_SELECTION = [
    ('24K', '24K'),
    ('21K', '21K'),
    ('18K', '18K'),
    ('14K', '14K'),
    ('10K', '10K'),
]
GOLD_TYPE_SELECTION = [
    ('jewellery_local', 'Jewellery - Local'),
    ('jewellery_foreign', 'Jewellery - Foreign'),
    ('bars', 'Bars'),
]
JEWELLERY_TYPE_SELECTION = [
    ('gold_local', 'Gold - Local'),
    ('gold_foreign', 'Gold - Foreign'),
    ('gold_bars', 'Gold Bars'),
    ('diamond_jewellery', 'Diamond Jewellery'),
    ('silver', 'Silver'),
]
SILVER_PURITY_SELECTION = [
    ('999.0', '999.0'),
    ('999.9', '999.9'),
]


class AccountMoveLine(models.Model):
    _inherit = 'account.move.line'

    jewellery_type = fields.Selection(
        selection=JEWELLERY_TYPE_SELECTION,
        string='Jewellery Type',
        help='Jewellery type for this invoice line.',
    )
    jewellery_weight_g = fields.Float(
        string='Jewellery Weight (g)',
        digits=(16, 2),
        help='Jewellery weight in grams for this line.',
    )
    silver_purity = fields.Selection(
        selection=SILVER_PURITY_SELECTION,
        string='Silver Purity',
        help='Silver purity for this line.',
    )
    karat_display = fields.Char(
        string='Karat',
        compute='_compute_jewellery_display_fields',
        inverse='_inverse_karat_display',
        help='Unified karat display (gold purity, diamond karat, or silver purity).',
    )
    weight_display_g = fields.Float(
        string='Weight (g)',
        digits=(16, 2),
        compute='_compute_jewellery_display_fields',
        inverse='_inverse_weight_display_g',
        help='Unified weight display in grams.',
    )

    gold_purity = fields.Selection(
        selection=GOLD_PURITY_SELECTION,
        string='Gold Purity',
        help='Gold purity (Karat) for this invoice line.',
    )
    gold_weight_g = fields.Float(
        string='Gold Weight (g)',
        digits=(16, 2),
        help='Gold weight in grams for this line.',
    )
    gold_type = fields.Selection(
        selection=GOLD_TYPE_SELECTION,
        string='Gold Type',
        help='Gold type for this line.',
    )
    gold_price_per_gram = fields.Float(
        string='Gold Price per Gram',
        digits=(16, 4),
        help='Gold price per gram at sale time.',
    )
    making_fee = fields.Float(
        string='Making Fee',
        digits=(16, 2),
        default=0.0,
        help='Making fee for this line.',
    )

    @api.depends('gold_purity', 'silver_purity', 'jewellery_weight_g', 'gold_weight_g')
    def _compute_jewellery_display_fields(self):
        """Compute unified invoice-display fields for Karat and Weight."""
        for line in self:
            line.karat_display = (
                line.gold_purity
                or line.silver_purity
                or False
            )
            line.weight_display_g = (
                line.jewellery_weight_g
                or line.gold_weight_g
                or 0.0
            )

    def _inverse_karat_display(self):
        """
        Persist editable unified karat into the proper underlying field.

        Rules:
        - 24K/21K/18K -> gold_purity
        - 999.0/999.9 -> silver_purity
        """
        gold_allowed = {'24K', '21K', '18K'}
        silver_allowed = {'999.0', '999.9'}
        for line in self:
            value = (line.karat_display or '').strip()
            if not value:
                line.gold_purity = False
                line.silver_purity = False
                continue
            if value in gold_allowed:
                line.gold_purity = value
                line.silver_purity = False
            elif value in silver_allowed:
                line.gold_purity = False
                line.silver_purity = value
            else:
                line.gold_purity = False
                line.silver_purity = False

    def _inverse_weight_display_g(self):
        """Persist editable unified weight to both new and legacy weight fields."""
        for line in self:
            value = line.weight_display_g or 0.0
            line.jewellery_weight_g = value
            line.gold_weight_g = value

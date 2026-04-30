# -*- coding: utf-8 -*-
# Copyright 2026 Revenax Digital Services
# Author: Mohamed A. Abdallah
# Website: https://www.revenax.com

from odoo import api, fields, models
from odoo.exceptions import ValidationError


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    gold_api_endpoint = fields.Char(
        string='Gold API Endpoint',
        config_parameter='jewellery_evaluator.gold_api_endpoint',
        help='URL endpoint for fetching gold prices from the API',
    )

    gold_21k_regex_formula = fields.Char(
        string='Gold 21K Regex Formula',
        config_parameter='jewellery_evaluator.gold_21k_regex_formula',
        help='Regular expression applied to the API HTML response to extract the 21K gold '
             'price per gram. Use one capturing group for the price number (e.g. (\\d+(?:\\.\\d+)?)). '
             'If no group, the full match is used.',
    )

    fallback_price = fields.Float(
        string='Fallback Gold Price',
        config_parameter='jewellery_evaluator.fallback_price',
        digits=(16, 2),
        default=75.0,
        help='Fallback gold price per gram when API is unavailable. '
             'Automatically updated to the last fetched price whenever the API returns successfully.',
    )

    silver_fallback_price = fields.Float(
        string='Silver 999 Price (EGP/g)',
        config_parameter='jewellery_evaluator.silver_fallback_price',
        digits=(16, 4),
        default=0.0,
        help='Silver 999 price per gram. Set by Selenium script (scripts/selenium_automation.py).',
    )

    silver_markup_per_gram = fields.Float(
        string='Silver Markup per Gram (EGP/g)',
        config_parameter='jewellery_evaluator.silver_markup_per_gram',
        digits=(16, 4),
        default=0.0,
        help='Markup per gram for silver products.',
    )

    markup_jewellery_local = fields.Float(
        string='Markup per Gram - Jewellery (Local)',
        config_parameter='jewellery_evaluator.markup_jewellery_local',
        digits=(16, 4),
        default=0.0,
        help='Markup per gram for local jewellery',
    )

    markup_jewellery_foreign = fields.Float(
        string='Markup per Gram - Jewellery (Foreign)',
        config_parameter='jewellery_evaluator.markup_jewellery_foreign',
        digits=(16, 4),
        default=0.0,
        help='Markup per gram for foreign jewellery',
    )

    # Deprecated: kept so views or cache that still reference them do not raise KeyError.
    # Bar pricing uses the weight-tier fields below; these are not shown in the config view.
    markup_bars = fields.Float(
        string='Markup per Gram - Bars (deprecated)',
        config_parameter='jewellery_evaluator.markup_bars',
        digits=(16, 4),
        default=0.0,
    )
    markup_ingots = fields.Float(
        string='Markup per Gram - Ingots (deprecated)',
        config_parameter='jewellery_evaluator.markup_ingots',
        digits=(16, 4),
        default=0.0,
    )
    markup_coins = fields.Float(
        string='Markup per Gram - Coins (deprecated)',
        config_parameter='jewellery_evaluator.markup_coins',
        digits=(16, 4),
        default=0.0,
    )

    # Bars: weight-tiered markup (EGP per gram). Weights 1, 2.5, 5, 10, 20, 31, 50, 100, 250, 500, 1000g+.
    markup_bars_1g = fields.Float(
        string='Bars 1g (EGP/g)',
        config_parameter='jewellery_evaluator.markup_bars_1g',
        digits=(16, 4),
        default=200.0,
        help='Markup per gram for bars up to 1g',
    )
    markup_bars_2_5g = fields.Float(
        string='Bars 2.5g (EGP/g)',
        config_parameter='jewellery_evaluator.markup_bars_2_5g',
        digits=(16, 4),
        default=200.0,
        help='Markup per gram for 2.5g tier',
    )
    markup_bars_5g = fields.Float(
        string='Bars 5g (EGP/g)',
        config_parameter='jewellery_evaluator.markup_bars_5g',
        digits=(16, 4),
        default=125.0,
        help='Markup per gram for 5g tier',
    )
    markup_bars_10g = fields.Float(
        string='Bars 10g (EGP/g)',
        config_parameter='jewellery_evaluator.markup_bars_10g',
        digits=(16, 4),
        default=120.0,
        help='Markup per gram for 10g tier',
    )
    markup_bars_20g = fields.Float(
        string='Bars 20g (EGP/g)',
        config_parameter='jewellery_evaluator.markup_bars_20g',
        digits=(16, 4),
        default=120.0,
        help='Markup per gram for 20g tier',
    )
    markup_bars_31g = fields.Float(
        string='Bars 31g (EGP/g)',
        config_parameter='jewellery_evaluator.markup_bars_31g',
        digits=(16, 4),
        default=115.0,
        help='Markup per gram for 31g tier',
    )
    markup_bars_50g = fields.Float(
        string='Bars 50g (EGP/g)',
        config_parameter='jewellery_evaluator.markup_bars_50g',
        digits=(16, 4),
        default=100.0,
        help='Markup per gram for 50g tier',
    )
    markup_bars_100g = fields.Float(
        string='Bars 100g (EGP/g)',
        config_parameter='jewellery_evaluator.markup_bars_100g',
        digits=(16, 4),
        default=100.0,
        help='Markup per gram for 100g tier',
    )
    markup_bars_250g = fields.Float(
        string='Bars 250g (EGP/g)',
        config_parameter='jewellery_evaluator.markup_bars_250g',
        digits=(16, 4),
        default=80.0,
        help='Markup per gram for 250g tier',
    )
    markup_bars_500g = fields.Float(
        string='Bars 500g (EGP/g)',
        config_parameter='jewellery_evaluator.markup_bars_500g',
        digits=(16, 4),
        default=80.0,
        help='Markup per gram for 500g tier',
    )
    markup_bars_1000g = fields.Float(
        string='Bars 1000g+ (EGP/g)',
        config_parameter='jewellery_evaluator.markup_bars_1000g',
        digits=(16, 4),
        default=80.0,
        help='Markup per gram for bars 1000g and above',
    )

    # ── Diamond Jewellery Pricing ───────────────────────────────────────────────

    diamond_exchange_rate_usd = fields.Float(
        string='EGP → USD Exchange Rate',
        config_parameter='jewellery_evaluator.diamond_exchange_rate_usd',
        digits=(16, 4),
        default=50.0,
        help='How many EGP equal 1 USD. Used to convert gold cost and sale price for diamond jewellery.',
    )
    diamond_fee_per_gram_usd = fields.Float(
        string='Making Fee per Gram (USD)',
        config_parameter='jewellery_evaluator.diamond_fee_per_gram_usd',
        digits=(16, 4),
        default=17.0,
        help='Fixed USD fee added per gram of gold on diamond jewellery products.',
    )
    diamond_ticket_multiplier = fields.Float(
        string='Ticket Price Multiplier',
        config_parameter='jewellery_evaluator.diamond_ticket_multiplier',
        digits=(16, 4),
        default=2.8,
        help='Multiply (gold cost + stones cost) by this to get the ticket price in USD.',
    )
    diamond_ticket_discount = fields.Float(
        string='Ticket Discount (0–1)',
        config_parameter='jewellery_evaluator.diamond_ticket_discount',
        digits=(16, 4),
        default=0.20,
        help='Fraction to discount off the ticket price. E.g. 0.20 = 20%% off. Sale = Ticket × (1 − discount).',
    )
    diamond_stone_tier_1_usd = fields.Float(
        string='Stone Tier 1 Price — 0.001–0.089 ct (USD)',
        config_parameter='jewellery_evaluator.diamond_stone_tier_1_usd',
        digits=(16, 2),
        default=800.0,
    )
    diamond_stone_tier_2_usd = fields.Float(
        string='Stone Tier 2 Price — 0.090–0.109 ct (USD)',
        config_parameter='jewellery_evaluator.diamond_stone_tier_2_usd',
        digits=(16, 2),
        default=950.0,
    )
    diamond_stone_tier_3_usd = fields.Float(
        string='Stone Tier 3 Price — 0.110–0.149 ct (USD)',
        config_parameter='jewellery_evaluator.diamond_stone_tier_3_usd',
        digits=(16, 2),
        default=1100.0,
    )
    diamond_stone_tier_4_usd = fields.Float(
        string='Stone Tier 4 Price — 0.150–0.199 ct (USD)',
        config_parameter='jewellery_evaluator.diamond_stone_tier_4_usd',
        digits=(16, 2),
        default=1250.0,
    )
    diamond_stone_tier_5_usd = fields.Float(
        string='Stone Tier 5 Price — 0.200–0.259 ct (USD)',
        config_parameter='jewellery_evaluator.diamond_stone_tier_5_usd',
        digits=(16, 2),
        default=1350.0,
    )

    @api.constrains('diamond_ticket_discount')
    def _check_diamond_ticket_discount(self):
        for record in self:
            if not (0.0 <= record.diamond_ticket_discount <= 1.0):
                raise ValidationError(
                    'Ticket Discount must be between 0 and 1 (e.g. 0.20 for 20%% off).'
                )

    pos_config_id = fields.Many2one(
        comodel_name="pos.config",
        string="Point of Sale",
        help="Select the Point of Sale to configure. Used for Require Customer and Invoicing below.",
    )
    require_customer = fields.Selection(
        selection=[
            ("no", "Optional"),
            ("payment", "Required before paying"),
            ("order", "Required before starting the order"),
        ],
        string="Require Customer",
        default="no",
        help="Require customer for orders in this point of sale.",
    )
    pos_to_invoice_by_default = fields.Boolean(
        string="Default to Invoice",
        default=False,
        help="Default behaviour for new orders: to invoice.",
    )

    @api.onchange("pos_config_id")
    def _onchange_pos_config_id(self):
        if self.pos_config_id:
            self.require_customer = self.pos_config_id.require_customer
            self.pos_to_invoice_by_default = self.pos_config_id.default_to_invoice

    def get_values(self):
        res = super().get_values()
        pos_config = self.env["pos.config"].search(
            [("company_id", "=", self.env.company.id)], limit=1
        )
        if pos_config:
            res["pos_config_id"] = pos_config.id
            res["require_customer"] = pos_config.require_customer
            res["pos_to_invoice_by_default"] = pos_config.default_to_invoice
        return res

    def set_values(self):
        super().set_values()
        if self.pos_config_id:
            self.pos_config_id.write({
                "require_customer": self.require_customer,
                "default_to_invoice": self.pos_to_invoice_by_default,
            })
        # Trigger silver product price recalculation when silver settings change
        self.env['silver.price.service'].update_all_silver_product_prices()

    def get_markup_for_type(self, gold_type, weight_g=None):
        """
        Get markup per gram for a specific gold type.

        :param gold_type: Gold type (jewellery_local, jewellery_foreign, bars)
        :param weight_g: Required when gold_type is 'bars'; used for tier lookup
        :return: float - Markup per gram
        """
        if gold_type == 'jewellery_local':
            return self.markup_jewellery_local
        if gold_type == 'jewellery_foreign':
            return self.markup_jewellery_foreign
        if gold_type == 'bars':
            if weight_g is None or weight_g <= 0:
                return 0.0
            from ..utils import get_markup_per_gram
            return get_markup_per_gram(self.env, 'bars', weight_g=weight_g)
        return 0.0

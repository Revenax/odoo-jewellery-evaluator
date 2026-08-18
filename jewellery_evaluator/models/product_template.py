# -*- coding: utf-8 -*-
# Copyright 2026 Revenax Digital Services
# Author: Mohamed A. Abdallah
# Website: https://www.revenax.com

import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

from ..utils import (
    _get_diamond_config_float,
    compute_diamond_jewellery_price,
    compute_diamond_weight_g,
    compute_gold_product_price,
    compute_silver_product_price,
    compute_sku_prefix,
    compute_weight_reading_g,
    format_diamond_note,
    format_weight_g,
    get_markup_per_gram,
    get_min_markup_per_gram,
    get_silver_markup_per_gram,
    get_silver_min_markup_per_gram,
    get_ticket_weight_g,
    is_serial_sku,
    jewellery_line_description,
)

_logger = logging.getLogger(__name__)


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    GOLD_PURITY_SELECTION = [
        ('24K', '24K'),
        ('21K', '21K'),
        ('18K', '18K'),
    ]

    JEWELLERY_TYPE_SELECTION = [
        ('gold_local', 'Gold - Local'),
        ('gold_foreign', 'Gold - Foreign'),
        ('gold_bars', 'Gold Bars'),
        ('diamond_jewellery', 'Diamond Jewellery'),
        ('center_stone', 'Center Stone'),
        ('silver', 'Silver'),
    ]

    GOLD_TYPE_SELECTION = [
        ('jewellery_local', 'Jewellery - Local'),
        ('jewellery_foreign', 'Jewellery - Foreign'),
        ('bars', 'Bars'),
    ]

    SILVER_PURITY_SELECTION = [
        ('999.0', '999.0'),
        ('999.9', '999.9'),
    ]

    JEWELLERY_TYPE_TO_GOLD_TYPE = {
        'gold_local': 'jewellery_local',
        'gold_foreign': 'jewellery_foreign',
        'gold_bars': 'bars',
    }
    GOLD_TYPE_TO_JEWELLERY_TYPE = {
        value: key for key, value in JEWELLERY_TYPE_TO_GOLD_TYPE.items()
    }

    VALID_GOLD_PURITIES = {item[0] for item in GOLD_PURITY_SELECTION}
    VALID_GOLD_TYPES = {item[0] for item in GOLD_TYPE_SELECTION}
    VALID_JEWELLERY_TYPES = {item[0] for item in JEWELLERY_TYPE_SELECTION}
    VALID_SILVER_PURITY = {item[0] for item in SILVER_PURITY_SELECTION}
    MAX_GOLD_WEIGHT_G = 100000
    GOLD_PRICE_UPDATE_FIELDS = {
        'jewellery_type',
        'jewellery_weight_g',
        'gold_weight_g',
        'gold_purity',
        'gold_type',
    }
    SILVER_PRICE_UPDATE_FIELDS = {
        'jewellery_type', 'jewellery_weight_g', 'silver_purity',
    }
    DIAMOND_PRICE_UPDATE_FIELDS = {
        'jewellery_type', 'jewellery_weight_g', 'gold_purity', 'stone_ids',
    }

    jewellery_type = fields.Selection(
        selection=JEWELLERY_TYPE_SELECTION,
        string='Jewellery Type',
        help='Select the jewellery category to apply pricing rules.',
    )

    jewellery_weight_g = fields.Float(
        string='Jewellery Weight (grams)',
        digits=(16, 2),
        help='Total jewellery weight in grams.',
    )

    # Gold-specific fields
    gold_weight_g = fields.Float(
        string='Gold Weight (grams)',
        digits=(16, 2),
        help='Legacy gold weight field. Automatically synced from Jewellery Weight for gold products.',
    )

    gold_purity = fields.Selection(
        selection=GOLD_PURITY_SELECTION,
        string='Jewellery Karat (Gold)',
        help='Purity level of the gold product',
    )

    gold_type = fields.Selection(
        selection=GOLD_TYPE_SELECTION,
        string='Gold Type (Internal)',
        help='Internal gold type used by existing markup configuration.',
    )

    silver_purity = fields.Selection(
        selection=SILVER_PURITY_SELECTION,
        string='Jewellery Karat (Silver)',
        help='Purity level for silver jewellery.',
    )

    def _register_hook(self):
        super()._register_hook()
        # One-time cleanup: convert deprecated ingots/coins to bars so stored values
        # match the reduced selection (avoids ValueError when opening old records).
        if self._name != 'product.template':
            return
        cr = self.env.cr
        cr.execute(
            "SELECT 1 FROM product_template WHERE gold_type IN ('ingots','coins') LIMIT 1"
        )
        if cr.fetchone():
            cr.execute(
                "UPDATE product_template SET gold_type = 'bars' "
                "WHERE gold_type IN ('ingots','coins')"
            )
            cr.execute(
                "UPDATE pos_order_line SET gold_type = 'bars' "
                "WHERE gold_type IN ('ingots','coins')"
            )
            cr.execute(
                "UPDATE account_move_line SET gold_type = 'bars' "
                "WHERE gold_type IN ('ingots','coins')"
            )
            _logger.info(
                'jewellery_evaluator: migrated gold_type ingots/coins to bars (runtime cleanup)'
            )
        cr.execute(
            "UPDATE product_template SET jewellery_type = 'gold_bars' "
            "WHERE jewellery_type IS NULL AND gold_type = 'bars'"
        )
        cr.execute(
            "UPDATE product_template SET jewellery_type = 'gold_local' "
            "WHERE jewellery_type IS NULL AND gold_type = 'jewellery_local'"
        )
        cr.execute(
            "UPDATE product_template SET jewellery_type = 'gold_foreign' "
            "WHERE jewellery_type IS NULL AND gold_type = 'jewellery_foreign'"
        )
        cr.execute(
            "UPDATE product_template SET jewellery_weight_g = gold_weight_g "
            "WHERE (jewellery_weight_g IS NULL OR jewellery_weight_g = 0) "
            "AND gold_weight_g > 0"
        )

    making_fee = fields.Float(
        string='Making Fee',
        digits=(16, 2),
        default=0.0,
        help='Default making fee for this gold product. Can be overridden on the order line.',
    )

    gold_cost_price = fields.Float(
        string='Gold Cost Price',
        digits=(16, 2),
        compute='_compute_gold_prices',
        store=True,
        help='Computed cost price: weight × base_price × purity_factor',
    )

    gold_min_sale_price = fields.Float(
        string='Gold Minimum Sale Price',
        digits=(16, 2),
        compute='_compute_gold_prices',
        store=True,
        help='Minimum allowed sale price (POS floor): cost + (minimum making '
             'fee × weight). When no minimum making fee is set, falls back to '
             'cost + 70% of the making fee.',
    )

    silver_cost_price = fields.Float(
        string='Silver Cost Price',
        digits=(16, 2),
        compute='_compute_silver_prices',
        store=True,
        readonly=True,
        help='Cost price: silver 999 price per gram × weight.',
    )

    silver_min_sale_price = fields.Float(
        string='Silver Minimum Sale Price',
        digits=(16, 2),
        compute='_compute_silver_prices',
        store=True,
        readonly=True,
        help='Minimum allowed sale price for silver (POS floor): cost + '
             '(minimum making fee × weight). Falls back to cost + 70% of the '
             'making fee when no minimum is set.',
    )

    jewellery_description = fields.Char(
        string='Printed Description',
        compute='_compute_jewellery_description',
        help='Customer-facing line description built from the product category '
             '("Gold / Coin" -> "Gold Coin"). Empty for non-jewellery products, '
             'where documents fall back to the normal line name.',
    )

    @api.depends('categ_id', 'categ_id.complete_name')
    def _compute_jewellery_description(self):
        for record in self:
            record.jewellery_description = jewellery_line_description(
                record.categ_id.complete_name or record.categ_id.name
            ) or False

    is_gold_product = fields.Boolean(
        string='Is Gold Product',
        compute='_compute_is_gold_product',
        store=True,
        help='Automatically set to True for gold jewellery types.',
    )

    is_diamond_jewellery_product = fields.Boolean(
        string='Is Diamond Jewellery',
        compute='_compute_is_diamond_jewellery_product',
        store=True,
        help='Automatically set to True for diamond jewellery type.',
    )

    is_silver_product = fields.Boolean(
        string='Is Silver Product',
        compute='_compute_is_silver_product',
        store=True,
        help='Automatically set to True for silver jewellery type.',
    )

    # Template-level mirror of product.product.is_unique_jewellery_piece. The POS
    # loads product.template AND product.product; hiding a sold unique piece only
    # at the variant level leaves an orphaned template that the (Enterprise) POS
    # renders and crashes on when clicked (reads product_template_attribute_value_ids
    # on the missing variant). Filtering the template too keeps them consistent.
    is_unique_jewellery_piece = fields.Boolean(
        string='Unique Jewellery Piece',
        compute='_compute_is_unique_jewellery_piece_tmpl',
        store=True,
        index=True,
        help='A single physical piece with a serial SKU (PREFIX-NNNN). On-hand '
             'is 0 or 1; the POS hides it when sold. Fungible weight/scrap SKUs '
             'are not unique pieces.',
    )

    # ── Diamond Jewellery ──────────────────────────────────────────────────────

    stone_ids = fields.One2many(
        comodel_name='jewellery.stone',
        inverse_name='product_tmpl_id',
        string='Stones',
    )

    diamond_total_gold_cost_usd = fields.Float(
        string='Gold Cost (USD)',
        digits=(16, 2),
        compute='_compute_diamond_jewellery_prices',
        store=True,
        readonly=True,
    )
    diamond_total_stones_cost_usd = fields.Float(
        string='Stones Cost (USD)',
        digits=(16, 2),
        compute='_compute_diamond_jewellery_prices',
        store=True,
        readonly=True,
    )
    diamond_ticket_price_usd = fields.Float(
        string='Ticket Price (USD)',
        digits=(16, 2),
        compute='_compute_diamond_jewellery_prices',
        store=True,
        readonly=True,
    )
    diamond_sale_price_usd = fields.Float(
        string='Sale Price (USD)',
        digits=(16, 2),
        compute='_compute_diamond_jewellery_prices',
        store=True,
        readonly=True,
    )
    diamond_sale_price_egp = fields.Float(
        string='Sale Price (EGP)',
        digits=(16, 2),
        compute='_compute_diamond_jewellery_prices',
        store=True,
        readonly=True,
    )

    diamond_min_sale_price = fields.Float(
        string='Diamond Minimum Sale Price',
        digits=(16, 2),
        compute='_compute_diamond_jewellery_prices',
        store=True,
        readonly=True,
        help='Minimum allowed sale price (POS floor) for diamond jewellery: a '
             'configurable share of the sale price (Diamond Min Sale %, system '
             'parameter jewellery_evaluator.diamond_min_sale_pct, default 0.9). '
             'When 0, the POS falls back to an 80%-of-price floor (like '
             'gold/silver), so the floor is never fully removed.',
    )

    # ── Weight breakdown (per piece) ───────────────────────────────────────────

    diamond_weight_g = fields.Float(
        string='Diamond Weight (g)',
        digits=(16, 3),
        compute='_compute_jewellery_weights',
        store=True,
        readonly=True,
        help='Total stone weight: sum of (carat × qty) × 0.2 across all stones.',
    )
    net_gold_weight_g = fields.Float(
        string='Net Gold Weight (g)',
        digits=(16, 3),
        compute='_compute_jewellery_weights',
        store=True,
        readonly=True,
        help='Net gold weight = Jewellery Weight (gold metal weight, grams).',
    )
    gross_jewellery_weight_g = fields.Float(
        string='Gross Jewellery Weight (g)',
        digits=(16, 3),
        compute='_compute_jewellery_weights',
        store=True,
        readonly=True,
        help='Gross piece weight = gold weight + diamond weight (grams).',
    )
    weight_reading_g = fields.Float(
        string='Weight Reading (g)',
        digits=(16, 3),
        compute='_compute_jewellery_weights',
        store=True,
        readonly=True,
        help='Scale reading of the finished piece = gross weight + ticket weight.',
    )
    sku_prefix = fields.Char(
        string='SKU Prefix',
        compute='_compute_sku_prefix',
        store=True,
        index=True,
        help='Internal reference up to the first "-". Groupable/filterable.',
    )

    # ── Gold-invoice display (diamond pieces only) ─────────────────────────────
    # The custom gold invoice (report/report_invoice_gold.xml) reads these off
    # the line's product. Empty for non-diamond pieces (the report then prints
    # the plain weight and no note). See utils.format_weight_g / format_diamond_note.
    invoice_weight_display = fields.Char(
        string='Invoice Weight (gross)',
        compute='_compute_invoice_display',
        store=True,
        readonly=True,
        help="Diamond pieces: total piece weight = gold + stones summed "
             "(e.g. '3.47'). Empty otherwise (report shows the plain weight).",
    )
    invoice_diamond_note = fields.Char(
        string='Invoice Diamond Note',
        compute='_compute_invoice_display',
        store=True,
        readonly=True,
        help="Auto diamond-detail note for the invoice (e.g. '17 DR 0.29CT' — "
             "17 diamonds, Round, 0.29 ct in total). "
             "Empty for non-diamond pieces.",
    )

    @api.depends(
        'jewellery_type', 'gross_jewellery_weight_g',
        'stone_ids.carat', 'stone_ids.quantity', 'stone_ids.shape',
    )
    def _compute_invoice_display(self):
        for record in self:
            if record.jewellery_type in ('diamond_jewellery', 'center_stone') and record.stone_ids:
                # Total piece weight = gold + stones, summed into one number.
                record.invoice_weight_display = format_weight_g(
                    record.gross_jewellery_weight_g
                )
                record.invoice_diamond_note = format_diamond_note(
                    [{'carat': s.carat, 'quantity': s.quantity, 'shape': s.shape}
                     for s in record.stone_ids]
                )
            else:
                record.invoice_weight_display = False
                record.invoice_diamond_note = False

    @api.depends('jewellery_type')
    def _compute_is_gold_product(self):
        """Mark product as gold product based on jewellery type."""
        for record in self:
            record.is_gold_product = bool(
                record.jewellery_type in self.JEWELLERY_TYPE_TO_GOLD_TYPE
            )

    @api.depends('jewellery_type')
    def _compute_is_diamond_jewellery_product(self):
        # Center Stone is a loose diamond (no gold): it reuses the whole diamond
        # path — pricing, POS floor, POS data, gift/details — differing only in
        # that its gold weight is 0 (see _compute_diamond_jewellery_prices).
        for record in self:
            record.is_diamond_jewellery_product = record.jewellery_type in (
                'diamond_jewellery', 'center_stone'
            )

    @api.depends('jewellery_type')
    def _compute_is_silver_product(self):
        """Mark product as silver product based on jewellery type."""
        for record in self:
            record.is_silver_product = bool(record.jewellery_type == 'silver')

    @api.depends('jewellery_type', 'product_variant_ids.default_code')
    def _compute_is_unique_jewellery_piece_tmpl(self):
        for template in self:
            code = template.product_variant_ids[:1].default_code
            template.is_unique_jewellery_piece = bool(
                template.jewellery_type
            ) and is_serial_sku(code)

    @api.model
    def _load_pos_data_domain(self, data, config):
        domain = super()._load_pos_data_domain(data, config)
        # Hide already-sold unique pieces (serial SKU, stock-tracked, on-hand < 1)
        # from the register at the TEMPLATE level too — filtering only the variant
        # (product.product) leaves an orphaned template that the POS renders and
        # crashes on when clicked. Show when not-unique, not stock-tracked, or
        # still on-hand.
        return list(domain) + [
            '|', '|',
            ('is_unique_jewellery_piece', '=', False),
            ('is_storable', '=', False),
            ('qty_available', '>', 0),
        ]

    @api.depends('jewellery_weight_g', 'stone_ids.carat', 'stone_ids.quantity')
    def _compute_jewellery_weights(self):
        """Per-piece weight breakdown (net gold, diamond, gross, weight reading).

        weight_reading_g also depends on the ticket_weight_g config parameter,
        which @api.depends cannot track; changing that setting recomputes it via
        _recompute_weight_reading_from_config().
        """
        ticket_weight = get_ticket_weight_g(self.env)
        for record in self:
            diamond_g = compute_diamond_weight_g(
                [(s.carat, s.quantity) for s in record.stone_ids]
            )
            net_gold = record.jewellery_weight_g or 0.0
            gross = net_gold + diamond_g
            record.diamond_weight_g = diamond_g
            record.net_gold_weight_g = net_gold
            record.gross_jewellery_weight_g = gross
            record.weight_reading_g = compute_weight_reading_g(gross, ticket_weight)

    @api.depends('default_code')
    def _compute_sku_prefix(self):
        for record in self:
            record.sku_prefix = compute_sku_prefix(record.default_code)

    def _recompute_weight_reading_from_config(self):
        """Refresh stored weight_reading_g after the ticket_weight_g setting changes.

        weight_reading_g = gross_jewellery_weight_g + ticket_weight_g. Since
        gross is already stored and config-independent, and the ticket is uniform,
        a single SQL UPDATE is far cheaper than recomputing the ORM per record.
        """
        ticket = get_ticket_weight_g(self.env)
        self.env.cr.execute(
            "UPDATE product_template SET weight_reading_g = "
            "ROUND(COALESCE(gross_jewellery_weight_g, 0.0)::numeric + %s::numeric, 3)",
            (ticket,),
        )
        self.env['product.template'].invalidate_model(['weight_reading_g'])

    @api.depends('jewellery_type', 'jewellery_weight_g', 'silver_purity')
    def _compute_silver_prices(self):
        """Compute silver cost price and minimum sale price (like gold)."""
        silver_price_service = self.env['silver.price.service']
        try:
            base_silver_999 = silver_price_service.get_current_silver_price_999()
        except Exception as e:
            _logger.warning(
                'Silver price service failed in _compute_silver_prices: %s',
                str(e),
                exc_info=True,
            )
            base_silver_999 = 0.0

        for record in self:
            if not record.is_silver_product:
                record.silver_cost_price = 0.0
                record.silver_min_sale_price = 0.0
                continue
            if not record.jewellery_weight_g or record.jewellery_weight_g <= 0:
                record.silver_cost_price = 0.0
                record.silver_min_sale_price = 0.0
                continue
            if not record.silver_purity:
                record.silver_cost_price = 0.0
                record.silver_min_sale_price = 0.0
                continue
            markup_per_gram = get_silver_markup_per_gram(self.env)
            min_markup_per_gram = get_silver_min_markup_per_gram(self.env)
            if markup_per_gram < 0:
                record.silver_cost_price = 0.0
                record.silver_min_sale_price = 0.0
                continue
            if base_silver_999 <= 0:
                record.silver_cost_price = 0.0
                record.silver_min_sale_price = 0.0
                continue
            try:
                cost_price, _sale_price, min_sale_price = compute_silver_product_price(
                    base_silver_999_per_gram=base_silver_999,
                    weight_g=record.jewellery_weight_g,
                    markup_per_gram=markup_per_gram,
                    min_markup_per_gram=min_markup_per_gram,
                )
                record.silver_cost_price = cost_price
                record.silver_min_sale_price = min_sale_price
            except ValueError:
                record.silver_cost_price = 0.0
                record.silver_min_sale_price = 0.0

    @api.depends(
        'jewellery_type', 'gold_purity', 'jewellery_weight_g',
        'stone_ids.unit_price_usd', 'stone_ids.total_price_usd',
    )
    def _compute_diamond_jewellery_prices(self):
        """Compute all pricing outputs for diamond jewellery products."""
        gold_service = self.env['gold.price.service']
        try:
            base_gold_21k_egp = gold_service.get_current_gold_price()
        except Exception:
            base_gold_21k_egp = 0.0

        exchange_rate, fee_per_gram, multiplier, discount, min_pct = self._diamond_pricing_config()

        zero = {
            'diamond_total_gold_cost_usd': 0.0,
            'diamond_total_stones_cost_usd': 0.0,
            'diamond_ticket_price_usd': 0.0,
            'diamond_sale_price_usd': 0.0,
            'diamond_sale_price_egp': 0.0,
            'diamond_min_sale_price': 0.0,
        }

        for record in self:
            if not record.is_diamond_jewellery_product:
                for k, v in zero.items():
                    setattr(record, k, v)
                continue

            # Center Stone is a loose diamond: no gold weight/purity required, and
            # the gold base price is irrelevant (its gold cost is 0). Everything
            # else (stones -> ticket -> sale -> floor) is the same diamond math.
            is_cs = record.jewellery_type == 'center_stone'
            if not is_cs and (
                not record.gold_purity
                or not record.jewellery_weight_g
                or record.jewellery_weight_g <= 0
            ):
                for k, v in zero.items():
                    setattr(record, k, v)
                continue

            if exchange_rate <= 0 or (not is_cs and base_gold_21k_egp <= 0):
                for k, v in zero.items():
                    setattr(record, k, v)
                continue

            valid_stone_prices = [
                s.total_price_usd
                for s in record.stone_ids
                if s.total_price_usd > 0
            ]

            try:
                result = compute_diamond_jewellery_price(
                    base_gold_price_21k_egp=base_gold_21k_egp,
                    gold_purity=record.gold_purity or '21K',
                    weight_g=0.0 if is_cs else record.jewellery_weight_g,
                    stone_prices_usd=valid_stone_prices,
                    exchange_rate_usd=exchange_rate,
                    fee_per_gram_usd=fee_per_gram,
                    ticket_multiplier=multiplier,
                    ticket_discount=discount,
                    min_sale_pct=min_pct,
                )
            except (ValueError, Exception) as e:
                _logger.warning(
                    'Diamond jewellery price computation failed for %s: %s',
                    record.display_name, e,
                )
                for k, v in zero.items():
                    setattr(record, k, v)
                continue

            record.diamond_total_gold_cost_usd = result['total_gold_cost_usd']
            record.diamond_total_stones_cost_usd = result['total_stones_cost_usd']
            record.diamond_ticket_price_usd = result['ticket_price_usd']
            record.diamond_sale_price_usd = result['sale_price_usd']
            record.diamond_sale_price_egp = result['sale_price_egp']
            record.diamond_min_sale_price = result['min_sale_price_egp']

    def _map_jewellery_type_to_gold_type(self, jewellery_type):
        return self.JEWELLERY_TYPE_TO_GOLD_TYPE.get(jewellery_type)

    def _normalize_jewellery_vals(self, vals):
        normalized = dict(vals)

        if not normalized.get('jewellery_type'):
            legacy_gold_type = normalized.get('gold_type')
            if legacy_gold_type in self.GOLD_TYPE_TO_JEWELLERY_TYPE:
                normalized['jewellery_type'] = self.GOLD_TYPE_TO_JEWELLERY_TYPE[legacy_gold_type]

        if 'jewellery_weight_g' not in normalized and 'gold_weight_g' in normalized:
            normalized['jewellery_weight_g'] = normalized.get('gold_weight_g')

        jewellery_type = normalized.get('jewellery_type')
        if jewellery_type in self.JEWELLERY_TYPE_TO_GOLD_TYPE:
            normalized['gold_type'] = self._map_jewellery_type_to_gold_type(
                jewellery_type)
            if 'jewellery_weight_g' in normalized:
                normalized['gold_weight_g'] = normalized.get(
                    'jewellery_weight_g') or 0.0
        elif 'jewellery_type' in normalized:
            normalized['gold_type'] = False
            normalized['gold_weight_g'] = 0.0

        return normalized

    @api.depends('jewellery_type', 'jewellery_weight_g', 'gold_purity', 'gold_type')
    def _compute_gold_prices(self):
        """Compute gold cost price and minimum sale price"""
        gold_price_service = self.env['gold.price.service']
        try:
            base_gold_price = gold_price_service.get_current_gold_price()
        except Exception as e:
            _logger.warning(
                'Gold price service failed in _compute_gold_prices: %s',
                str(e),
                exc_info=True,
            )
            base_gold_price = 0.0

        for record in self:
            if not record.is_gold_product:
                record.gold_cost_price = 0.0
                record.gold_min_sale_price = 0.0
                continue
            if not record.jewellery_weight_g or record.jewellery_weight_g <= 0:
                record.gold_cost_price = 0.0
                record.gold_min_sale_price = 0.0
                continue
            if not record.gold_purity:
                record.gold_cost_price = 0.0
                record.gold_min_sale_price = 0.0
                continue

            # Get markup per gram from settings (bars use weight-tier lookup)
            internal_gold_type = record._map_jewellery_type_to_gold_type(
                record.jewellery_type)
            if not internal_gold_type:
                record.gold_cost_price = 0.0
                record.gold_min_sale_price = 0.0
                continue

            weight_for_markup = record.jewellery_weight_g if internal_gold_type == 'bars' else None
            markup_per_gram = get_markup_per_gram(
                self.env, internal_gold_type, weight_g=weight_for_markup
            )
            min_markup_per_gram = get_min_markup_per_gram(
                self.env, internal_gold_type)

            if markup_per_gram <= 0:
                # Skip if markup not configured for this type
                record.gold_cost_price = 0.0
                record.gold_min_sale_price = 0.0
                continue

            # Use pure helper function to compute prices
            try:
                cost_price, sale_price, min_sale_price = compute_gold_product_price(
                    base_gold_price_21k=base_gold_price,
                    purity=record.gold_purity,
                    weight_g=record.jewellery_weight_g or 0,
                    markup_per_gram=markup_per_gram,
                    min_markup_per_gram=min_markup_per_gram,
                )
                record.gold_cost_price = cost_price
                record.gold_min_sale_price = min_sale_price
            except ValueError:
                # Invalid purity or other error
                record.gold_cost_price = 0.0
                record.gold_min_sale_price = 0.0

    def _get_gold_price_update_vals(self, base_gold_price):
        """
        Prepare standard and list price updates for gold products.

        Args:
            base_gold_price: Base 21K gold price per gram

        Returns:
            dict: Fields to update, or empty dict if not applicable
        """
        self.ensure_one()

        if not self.is_gold_product:
            return {}
        if not self.jewellery_weight_g or self.jewellery_weight_g <= 0:
            return {}
        if not self.gold_purity:
            return {}

        internal_gold_type = self._map_jewellery_type_to_gold_type(
            self.jewellery_type)
        if not internal_gold_type:
            return {}

        weight_for_markup = self.jewellery_weight_g if internal_gold_type == 'bars' else None
        markup_per_gram = get_markup_per_gram(
            self.env, internal_gold_type, weight_g=weight_for_markup
        )
        if markup_per_gram <= 0:
            return {}

        try:
            cost_price, sale_price, _min_sale_price = compute_gold_product_price(
                base_gold_price_21k=base_gold_price,
                purity=self.gold_purity,
                weight_g=self.jewellery_weight_g or 0,
                markup_per_gram=markup_per_gram,
            )
        except ValueError:
            return {}

        return {
            'list_price': sale_price,
        }

    def _get_silver_price_update_vals(self, base_silver_999):
        """
        Prepare list price, cost price, and min sale price update for silver products.

        :param base_silver_999: Silver 999 price per gram (EGP)
        :return: dict with list_price, silver_cost_price, silver_min_sale_price or empty
        """
        self.ensure_one()
        if not self.is_silver_product or not self.jewellery_weight_g or self.jewellery_weight_g <= 0:
            return {}
        if not self.silver_purity:
            return {}
        markup_per_gram = get_silver_markup_per_gram(self.env)
        if markup_per_gram < 0:
            return {}
        if base_silver_999 <= 0:
            return {}
        try:
            cost_price, sale_price, min_sale_price = compute_silver_product_price(
                base_silver_999_per_gram=base_silver_999,
                weight_g=self.jewellery_weight_g,
                markup_per_gram=markup_per_gram,
            )
            return {
                'list_price': sale_price,
                'silver_cost_price': cost_price,
                'silver_min_sale_price': min_sale_price,
            }
        except ValueError:
            return {}

    def _diamond_pricing_config(self):
        """Return (exchange_rate, fee_per_gram, multiplier, discount, min_pct) from ICP."""
        env = self.env
        return (
            _get_diamond_config_float(env, 'diamond_exchange_rate_usd', 50.0),
            _get_diamond_config_float(env, 'diamond_fee_per_gram_usd', 17.0),
            _get_diamond_config_float(env, 'diamond_ticket_multiplier', 2.8),
            _get_diamond_config_float(env, 'diamond_ticket_discount', 0.20),
            _get_diamond_config_float(env, 'diamond_min_sale_pct', 0.9),
        )

    def _get_diamond_price_update_vals(self, base_gold_21k_egp):
        """
        Prepare list_price update for diamond jewellery products.

        :param base_gold_21k_egp: Current 21K gold price per gram in EGP.
        :return: dict with list_price (rounded EGP sale price), or empty.
        """
        self.ensure_one()
        if not self.is_diamond_jewellery_product:
            return {}
        is_cs = self.jewellery_type == 'center_stone'
        if not is_cs and (
            not self.gold_purity
            or not self.jewellery_weight_g
            or self.jewellery_weight_g <= 0
        ):
            return {}
        if not is_cs and base_gold_21k_egp <= 0:
            return {}

        exchange_rate, fee_per_gram, multiplier, discount, min_pct = self._diamond_pricing_config()
        if exchange_rate <= 0:
            return {}

        valid_stone_prices = [
            s.total_price_usd for s in self.stone_ids if s.total_price_usd > 0
        ]
        try:
            result = compute_diamond_jewellery_price(
                base_gold_price_21k_egp=base_gold_21k_egp,
                gold_purity=self.gold_purity or '21K',
                weight_g=0.0 if is_cs else self.jewellery_weight_g,
                stone_prices_usd=valid_stone_prices,
                exchange_rate_usd=exchange_rate,
                fee_per_gram_usd=fee_per_gram,
                ticket_multiplier=multiplier,
                ticket_discount=discount,
                min_sale_pct=min_pct,
            )
        except (ValueError, Exception) as e:
            _logger.warning(
                'Diamond price update failed for %s: %s',
                self.display_name, e,
            )
            return {}

        return {
            'list_price': result['sale_price_egp'],
            'diamond_min_sale_price': result['min_sale_price_egp'],
        }

    @api.onchange('jewellery_type', 'jewellery_weight_g')
    def _onchange_sync_gold_legacy_fields(self):
        for record in self:
            if record.jewellery_type in self.JEWELLERY_TYPE_TO_GOLD_TYPE:
                record.gold_type = record._map_jewellery_type_to_gold_type(
                    record.jewellery_type)
                record.gold_weight_g = record.jewellery_weight_g or 0.0
            elif record.jewellery_type:
                record.gold_type = False
                record.gold_weight_g = 0.0

    @api.onchange('jewellery_type', 'jewellery_weight_g', 'gold_purity')
    def _onchange_jewellery_evaluator_fields(self):
        """Update prices immediately in the UI when gold fields change."""
        try:
            gold_price_service = self.env['gold.price.service']
            base_gold_price = gold_price_service.get_current_gold_price()
            for record in self:
                if not record.is_gold_product:
                    continue
                update_vals = record._get_gold_price_update_vals(
                    base_gold_price)
                if update_vals:
                    record.update(update_vals)
        except Exception as e:
            raise ValidationError(
                _('Gold price could not be updated. Please try again or check '
                  'gold price settings. Details: %s') % str(e)
            ) from e

    @api.onchange('jewellery_type', 'jewellery_weight_g', 'gold_purity', 'stone_ids')
    def _onchange_diamond_jewellery_fields(self):
        """Refresh diamond computed fields and sync list_price in the UI."""
        try:
            gold_price_service = self.env['gold.price.service']
            base_gold_21k_egp = gold_price_service.get_current_gold_price()
            for record in self:
                if not record.is_diamond_jewellery_product:
                    continue
                record._compute_diamond_jewellery_prices()
                update_vals = record._get_diamond_price_update_vals(base_gold_21k_egp)
                if update_vals:
                    record.update(update_vals)
        except Exception as e:
            raise ValidationError(
                _('Diamond price could not be updated. Please check gold price '
                  'and diamond jewellery settings. Details: %s') % str(e)
            ) from e

    @api.onchange('jewellery_type', 'jewellery_weight_g', 'silver_purity')
    def _onchange_silver_pricing_fields(self):
        """Update prices when silver fields change in the form."""
        try:
            silver_service = self.env['silver.price.service']
            base_silver = silver_service.get_current_silver_price_999()
            for record in self:
                if not record.is_silver_product:
                    # Clear silver fields when switching away from silver type
                    record.silver_cost_price = 0.0
                    record.silver_min_sale_price = 0.0
                    continue
                update_vals = record._get_silver_price_update_vals(base_silver)
                if update_vals:
                    record.update(update_vals)
        except Exception as e:
            raise ValidationError(
                _('Silver price could not be updated. Check silver 999 price and markup in Settings. Details: %s')
                % str(e)
            ) from e

    # Jewellery materials that get mirrored into the POS category tree.
    POS_CATEGORY_MATERIALS = ('Gold', 'Diamond', 'Silver')

    def _matching_pos_category(self):
        """Find-or-create the pos.category mirroring this product's
        product.category (Material / Shape), so the POS register groups products
        the same way the catalog does. Returns the leaf (shape) pos.category, or
        an empty recordset for non-jewellery / uncategorised products."""
        self.ensure_one()
        categ = self.categ_id
        parent = categ.parent_id  # empty recordset (falsy) when there's no parent
        if not parent or parent.name not in self.POS_CATEGORY_MATERIALS:
            return self.env['pos.category']
        PC = self.env['pos.category'].sudo()
        material = PC.search(
            [('name', '=', parent.name), ('parent_id', '=', False)], limit=1
        ) or PC.create({'name': parent.name})
        shape = PC.search(
            [('name', '=', categ.name), ('parent_id', '=', material.id)], limit=1
        ) or PC.create({'name': categ.name, 'parent_id': material.id})
        return shape

    def _sync_pos_category(self):
        """Set pos_categ_ids to the single POS category matching the product's
        Material/Shape. Self-guarded — a POS-category hiccup must never block a
        product create/edit/sync (POS grouping is cosmetic)."""
        for record in self:
            try:
                pos_categ = record._matching_pos_category()
                if pos_categ and record.pos_categ_ids.ids != pos_categ.ids:
                    record.write({'pos_categ_ids': [(6, 0, pos_categ.ids)]})
            except Exception:
                _logger.warning(
                    'POS category sync failed for %s', record.display_name,
                    exc_info=True,
                )

    @api.model_create_multi
    def create(self, vals_list):
        normalized_vals_list = [
            self._normalize_jewellery_vals(vals) for vals in vals_list]
        records = super().create(normalized_vals_list)
        records._sync_pos_category()
        try:
            if not self.env.context.get('skip_gold_price_update'):
                if any(
                    self.GOLD_PRICE_UPDATE_FIELDS & vals.keys()
                    for vals in normalized_vals_list
                ):
                    gold_price_service = self.env['gold.price.service']
                    base_gold_price = gold_price_service.get_current_gold_price()
                    for record in records:
                        if not record.is_gold_product:
                            continue
                        update_vals = record._get_gold_price_update_vals(
                            base_gold_price
                        )
                        if update_vals:
                            record.with_context(
                                skip_gold_price_update=True
                            ).write(update_vals)

            if not self.env.context.get('skip_silver_price_update'):
                silver_records = records.filtered(
                    lambda r: r.jewellery_type == 'silver')
                if silver_records:
                    silver_service = self.env['silver.price.service']
                    base_silver = silver_service.get_current_silver_price_999()
                    for record in silver_records:
                        update_vals = record._get_silver_price_update_vals(
                            base_silver
                        )
                        if update_vals:
                            record.with_context(
                                skip_silver_price_update=True
                            ).write(update_vals)

            if not self.env.context.get('skip_diamond_price_update'):
                if any(
                    self.DIAMOND_PRICE_UPDATE_FIELDS & vals.keys()
                    for vals in normalized_vals_list
                ):
                    gold_price_service = self.env['gold.price.service']
                    base_gold_21k_egp = gold_price_service.get_current_gold_price()
                    for record in records:
                        if not record.is_diamond_jewellery_product:
                            continue
                        update_vals = record._get_diamond_price_update_vals(
                            base_gold_21k_egp
                        )
                        if update_vals:
                            record.with_context(
                                skip_diamond_price_update=True
                            ).write(update_vals)
        except Exception as e:
            raise ValidationError(
                _('Product price update failed. Please check gold/silver/diamond '
                  'jewellery settings or try again. Details: %s') % str(e)
            ) from e
        return records

    def write(self, vals):
        normalized_vals = self._normalize_jewellery_vals(vals)
        res = super().write(normalized_vals)
        try:
            if not self.env.context.get('skip_gold_price_update'):
                if self.GOLD_PRICE_UPDATE_FIELDS & set(normalized_vals.keys()):
                    gold_price_service = self.env['gold.price.service']
                    base_gold_price = (
                        gold_price_service.get_current_gold_price()
                    )
                    for record in self:
                        if not record.is_gold_product:
                            continue
                        update_vals = record._get_gold_price_update_vals(
                            base_gold_price
                        )
                        if update_vals:
                            record.with_context(
                                skip_gold_price_update=True
                            ).write(update_vals)

            if not self.env.context.get('skip_silver_price_update'):
                silver_records = self.filtered(
                    lambda r: r.jewellery_type == 'silver')
                if silver_records and (
                    self.SILVER_PRICE_UPDATE_FIELDS & set(
                        normalized_vals.keys())
                ):
                    silver_service = self.env['silver.price.service']
                    base_silver = silver_service.get_current_silver_price_999()
                    for record in silver_records:
                        update_vals = record._get_silver_price_update_vals(
                            base_silver
                        )
                        if update_vals:
                            record.with_context(
                                skip_silver_price_update=True
                            ).write(update_vals)

            if not self.env.context.get('skip_diamond_price_update'):
                if self.DIAMOND_PRICE_UPDATE_FIELDS & set(normalized_vals.keys()):
                    gold_price_service = self.env['gold.price.service']
                    base_gold_21k_egp = (
                        gold_price_service.get_current_gold_price()
                    )
                    for record in self:
                        if not record.is_diamond_jewellery_product:
                            continue
                        update_vals = record._get_diamond_price_update_vals(
                            base_gold_21k_egp
                        )
                        if update_vals:
                            record.with_context(
                                skip_diamond_price_update=True
                            ).write(update_vals)
        except Exception as e:
            raise ValidationError(
                _('Product price update failed. Please check gold/silver/diamond '
                  'jewellery settings or try again. Details: %s') % str(e)
            ) from e
        if 'categ_id' in normalized_vals:
            self._sync_pos_category()
        return res

    @api.constrains('jewellery_type', 'jewellery_weight_g', 'gold_purity', 'silver_purity', 'gold_type')
    def _check_gold_required_fields(self):
        """Ensure required fields are set for each jewellery type."""
        for record in self:
            if record.jewellery_type and record.jewellery_type not in self.VALID_JEWELLERY_TYPES:
                raise ValidationError(
                    f'Invalid jewellery type: {record.jewellery_type}.'
                )

            if record.is_gold_product:
                if not record.jewellery_weight_g or record.jewellery_weight_g <= 0:
                    raise ValidationError(
                        'Jewellery Weight (grams) is required and must be greater than 0 for gold products.'
                    )
                if record.jewellery_weight_g > self.MAX_GOLD_WEIGHT_G:
                    raise ValidationError(
                        'Jewellery Weight (grams) cannot exceed 100,000 grams (100 kg). '
                        'Please verify the weight value.'
                    )
                if not record.gold_purity:
                    raise ValidationError(
                        'Jewellery Karat is required for gold products.'
                    )
                if record.gold_purity not in self.VALID_GOLD_PURITIES:
                    raise ValidationError(
                        f'Invalid gold purity: {record.gold_purity}. '
                        f'Must be one of: {", ".join(sorted(self.VALID_GOLD_PURITIES))}'
                    )
                expected_gold_type = record._map_jewellery_type_to_gold_type(
                    record.jewellery_type)
                if not record.gold_type or record.gold_type != expected_gold_type:
                    raise ValidationError(
                        'Internal Gold Type is not synchronized with Jewellery Type.'
                    )
                if record.gold_type not in self.VALID_GOLD_TYPES:
                    raise ValidationError(
                        f'Invalid gold type: {record.gold_type}. '
                        f'Must be one of: {", ".join(sorted(self.VALID_GOLD_TYPES))}'
                    )

            if record.is_silver_product and not record.silver_purity:
                raise ValidationError(
                    'Jewellery Karat is required for silver products.'
                )
            if record.silver_purity and record.silver_purity not in self.VALID_SILVER_PURITY:
                raise ValidationError(
                    f'Invalid silver purity: {record.silver_purity}. '
                    f'Must be one of: {", ".join(sorted(self.VALID_SILVER_PURITY))}'
                )

    def _price_update_threshold(self):
        """Minimum EGP change in a product's sale price before the cron rewrites
        it.

        Sale/min prices round to the nearest 50 EGP, so a tiny gold/silver move
        usually produces no change at all — yet the cron used to rewrite every
        product every run (bumping write_date, re-running the write override, and
        churning ~650 rows). This gate makes a flat/rounding-stable run a no-op.

        Tunable via system parameter ``jewellery_evaluator.price_update_threshold_egp``
        (default 10). Applies ONLY to the cron batch updates — a user create/edit
        always reprices regardless.
        """
        return float(self.env['ir.config_parameter'].sudo().get_param(
            'jewellery_evaluator.price_update_threshold_egp', 10.0) or 10.0)

    def init_jewellery_stock(self, warehouse_code=None, qty=1.0):
        """Set on-hand to exactly ``qty`` (default 1) at the given warehouse's
        stock location, for a brand-new jewellery piece.

        Called ONCE by the operations sync when an entirely new product is first
        written to Odoo — the only inventory write the sync is allowed to make.
        Uses an inventory adjustment with SET (not add) semantics and is
        idempotent, so a stray re-call can never inflate stock. Sync edits and
        re-syncs must never touch inventory.
        """
        self.ensure_one()
        # Jewellery pieces must be storable goods to carry on-hand stock. In
        # Odoo 19 "storable" is the ``is_storable`` flag on a ``consu`` good
        # (no more ``type='product'``); without it stock.quant refuses to exist.
        # Written via the ORM dict (not ``self.is_storable = True``) on purpose:
        # a brand-new product is never storable yet, and the dict write keeps
        # mypy from trying to infer the inherited field's type.
        self.write({'is_storable': True})
        Warehouse = self.env['stock.warehouse']
        warehouse = (
            Warehouse.search([('code', '=', warehouse_code)], limit=1)
            if warehouse_code else Warehouse.browse()
        )
        if not warehouse:
            warehouse = Warehouse.search([], limit=1)
        location = warehouse.lot_stock_id
        product = self.product_variant_id
        if not (location and product):
            return False
        Quant = self.env['stock.quant'].with_context(inventory_mode=True)
        quant = Quant.search([
            ('product_id', '=', product.id),
            ('location_id', '=', location.id),
        ], limit=1) or Quant.create({
            'product_id': product.id,
            'location_id': location.id,
        })
        quant.inventory_quantity = qty
        quant.action_apply_inventory()
        return True

    def init_jewellery_from_customer(self, warehouse_code=None, price_unit=None,
                                     partner=None):
        """Bring a brand-new "Bought from Customer" piece on-hand via a real
        Purchase Order receipt (qty 1) from a generic buy-back vendor, fulfilled
        at the selected warehouse — instead of a direct inventory adjustment.

        The whole flow runs in this single server-side call == one transaction,
        so any failure rolls the entire PO + receipt back (no orphan PO, no
        half-receipt). It is idempotent: at most one PO per piece, keyed on the
        SKU (``origin``); a re-call after a successful receipt is a no-op and can
        never duplicate the PO or inflate stock. "Reliable at any cost."
        """
        self.ensure_one()
        self.write({'is_storable': True})
        product = self.product_variant_id
        if not product:
            return False

        # Warehouse -> its incoming picking type. Setting picking_type_id on the
        # PO is the only lever needed: the receipt destination follows from the
        # type's default_location_dest_id (that warehouse's stock location).
        Warehouse = self.env['stock.warehouse']
        warehouse = (
            Warehouse.search([('code', '=', warehouse_code)], limit=1)
            if warehouse_code else Warehouse.browse()
        )
        if not warehouse:
            warehouse = Warehouse.search([], limit=1)
        picking_type = warehouse.in_type_id or self.env['stock.picking.type'].search(
            [('code', '=', 'incoming'), ('warehouse_id', '=', warehouse.id)], limit=1)
        if not (warehouse and picking_type):
            return False

        # Vendor: the fixed module data partner (or an explicit override for
        # future per-customer use). env.ref avoids a runtime find-or-create race.
        if partner is None:
            partner = self.env.ref(
                'jewellery_evaluator.partner_bought_from_customer')
        if not partner.property_stock_supplier:
            partner = partner.with_company(self.env.company)
            partner.property_stock_supplier = self.env.ref(
                'stock.stock_location_suppliers')

        origin = self.default_code or f'JEWEL-{self.id}'
        price = price_unit if (price_unit and price_unit > 0) \
            else self._bought_from_customer_price_unit()

        # Idempotency: at most one non-cancelled PO per piece, keyed on the SKU.
        PO = self.env['purchase.order']
        po = PO.search([
            ('origin', '=', origin),
            ('order_line.product_id', '=', product.id),
            ('state', '!=', 'cancel'),
        ], limit=1)
        if not po:
            po = PO.create({
                'partner_id': partner.id,
                'picking_type_id': picking_type.id,
                'origin': origin,
                'order_line': [(0, 0, {
                    'product_id': product.id,
                    'product_qty': 1.0,
                    'price_unit': price,
                    'name': self.display_name,
                })],
            })

        # Confirm: the sync user is a Purchase Manager, so this auto-approves
        # (despite two-step validation) and creates the incoming picking.
        if po.state in ('draft', 'sent'):
            po.button_confirm()
        if po.state == 'to approve':
            raise UserError(_(
                "Bought-from-customer PO %s is stuck awaiting approval; the "
                "Odoo sync user must be in the Purchase Manager group.") % po.name)

        picking = po.picking_ids.filtered(lambda p: p.state != 'cancel')[:1]
        if not picking:
            return False
        if picking.state == 'done':
            # Already received on a prior call -> no stock change, but still
            # settle the Vault in case a previous run stocked without paying
            # (idempotent: skips when the bill is already paid).
            self._settle_buyback_to_vault(po, warehouse, price)
            return True

        if picking.state == 'draft':
            picking.action_confirm()
        picking.action_assign()
        for move in picking.move_ids.filtered(
                lambda m: m.state not in ('done', 'cancel')):
            move.quantity = move.product_uom_qty or 1.0
            move.picked = True
            # serial-tracked goods need a lot before the receipt can validate.
            if move.product_id.tracking == 'serial':
                line = move.move_line_ids[:1] or self.env['stock.move.line'].create({
                    'move_id': move.id,
                    'picking_id': picking.id,
                    'product_id': move.product_id.id,
                    'product_uom_id': move.product_uom.id,
                    'location_id': move.location_id.id,
                    'location_dest_id': move.location_dest_id.id,
                })
                if not line.lot_id and not line.lot_name:
                    line.lot_name = origin
                line.quantity = 1.0
                line.picked = True

        # Full-qty receipt -> no backorder; skip_backorder + the not-to-backorder
        # context guarantee button_validate never pops a wizard. Trust the
        # picking state, not the return value (it may return a report action).
        picking.with_context(
            skip_backorder=True,
            picking_ids_not_to_backorder=picking.ids,
        ).button_validate()
        if picking.state != 'done':
            picking.move_ids._action_done()
        if picking.state == 'done':
            self._settle_buyback_to_vault(po, warehouse, price)
            # NOTE: deliberately NOT notified here. The ops app owns this
            # event — it emits `buyback-recorded` when the piece is
            # registered, which is what calls this method. Notifying from
            # both sides would report one buy-back twice.
        return picking.state == 'done'

    def _settle_buyback_to_vault(self, po, warehouse, amount):
        """Pay the buy-back cash out of the branch Vault so the POS shift count
        reflects it: post the PO's vendor bill and settle it from the Vault
        (cash) journal — net effect ``Cr Vault`` (cash leaves the drawer), which
        the POS session override then folds into the shift's expected cash.

        Idempotent: one bill + one payment per PO, skips when the bill is
        already paid, so re-syncs never duplicate. Best-effort and isolated in a
        savepoint — a payment hiccup logs loudly and is retried on the next
        sync, but never rolls back or blocks the (already reliable) stock
        receipt. A branch with no Vault journal is logged and skipped, not
        failed.
        """
        if not amount or amount <= 0:
            return
        warehouse = warehouse or self.env['stock.warehouse'].search([], limit=1)
        vault = (warehouse._vault_journal() if warehouse
                 else self.env['account.journal'])
        if not vault:
            _logger.warning(
                "Buy-back %s: no Vault (cash) journal for warehouse %s; cash-out "
                "not recorded. Set a Vault journal so the POS count reflects it.",
                po.name, warehouse.code if warehouse else '?')
            return
        try:
            with self.env.cr.savepoint():
                bill = po.invoice_ids.filtered(
                    lambda m: m.move_type == 'in_invoice' and m.state != 'cancel')[:1]
                if not bill:
                    po.action_create_invoice()
                    bill = po.invoice_ids.filtered(
                        lambda m: m.move_type == 'in_invoice' and m.state != 'cancel')[:1]
                if not bill:
                    return
                if bill.state == 'draft':
                    if not bill.invoice_date:
                        bill.invoice_date = fields.Date.context_today(bill)
                    bill.action_post()
                if bill.payment_state in ('paid', 'in_payment', 'reversed'):
                    return  # already settled
                self.env['account.payment.register'].with_context(
                    active_model='account.move', active_ids=bill.ids,
                ).create({'journal_id': vault.id}).action_create_payments()
        except Exception as e:
            _logger.error(
                "Buy-back %s: could not pay %s out of Vault %s (%s). Stock is "
                "fine; cash-out NOT recorded — will retry on re-sync.",
                po.name, amount, vault.name, e)

    def _bought_from_customer_price_unit(self):
        """Fallback PO-line price when the operator entered no buy-back amount:
        product cost, then computed gold cost, then list price, else 0."""
        self.ensure_one()
        return (self.standard_price or self.gold_cost_price
                or self.list_price or 0.0)

    def update_gold_prices(self, base_gold_price):
        """
        Update product prices based on new gold price.
        Called by cron job for batch updates.
        Skips products missing required data, and products whose sale price moved
        less than :meth:`_price_update_threshold`.

        :param base_gold_price: Current base gold price per gram
        :return: tuple(updated_count, skipped_count)
        """
        if not self:
            return (0, 0)

        threshold = self._price_update_threshold()

        # Filter only gold products with all required data
        gold_products = self.filtered(
            lambda p: p.is_gold_product
            and p.gold_purity
            and p.jewellery_weight_g
            and p.jewellery_weight_g > 0
        )

        updated = 0
        skipped = len(self) - len(gold_products)

        for product in gold_products:
            internal_gold_type = product._map_jewellery_type_to_gold_type(
                product.jewellery_type)
            if not internal_gold_type:
                skipped += 1
                continue
            weight_for_markup = product.jewellery_weight_g if internal_gold_type == 'bars' else None
            markup_per_gram = get_markup_per_gram(
                self.env, internal_gold_type, weight_g=weight_for_markup
            )
            min_markup_per_gram = get_min_markup_per_gram(
                self.env, internal_gold_type)

            # Skip if markup not configured for this type
            if markup_per_gram <= 0:
                skipped += 1
                continue

            # Use pure helper function to compute prices
            try:
                cost_price, sale_price, min_sale_price = compute_gold_product_price(
                    base_gold_price_21k=base_gold_price,
                    purity=product.gold_purity,
                    weight_g=product.jewellery_weight_g,
                    markup_per_gram=markup_per_gram,
                    min_markup_per_gram=min_markup_per_gram,
                )
            except ValueError:
                # Invalid purity or other error - skip this product
                skipped += 1
                continue

            # Write whenever ANY computed value moved. The sale price is rounded
            # to 50 (so it only changes in 50s), but cost and the minimum sale
            # price are exact and shift with every gold-price tick — so a real
            # gold move now refreshes the WHOLE inventory, not just the pieces
            # whose rounded sale happened to cross a 50. A flat run (gold
            # unchanged) leaves all three identical and writes nothing.
            if (abs(sale_price - (product.list_price or 0.0)) < threshold
                    and abs(cost_price - (product.gold_cost_price or 0.0)) < 0.005
                    and abs(min_sale_price - (product.gold_min_sale_price or 0.0)) < 0.005):
                skipped += 1
                continue

            product.write({
                'list_price': sale_price,
                'gold_cost_price': cost_price,
                'gold_min_sale_price': min_sale_price,
            })
            updated += 1

        return (updated, skipped)

    def update_diamond_jewellery_prices(self, base_gold_21k_egp):
        """
        Refresh diamond jewellery sale price on the product record so the displayed
        list_price stays in sync when the gold base price changes.
        Called by the gold cron after it updates gold products.

        :param base_gold_21k_egp: Current 21K gold price per gram in EGP.
        :return: tuple(updated_count, skipped_count)
        """
        if not self:
            return (0, 0)

        threshold = self._price_update_threshold()
        diamond_products = self.filtered(
            lambda p: p.is_diamond_jewellery_product
            and p.gold_purity
            and p.jewellery_weight_g
            and p.jewellery_weight_g > 0
        )
        if not diamond_products:
            return (0, len(self))

        updated = 0
        skipped = len(self) - len(diamond_products)
        exchange_rate, fee_per_gram, multiplier, discount, min_pct = self._diamond_pricing_config()

        for product in diamond_products:
            valid_stone_prices = [
                s.total_price_usd
                for s in product.stone_ids
                if s.total_price_usd > 0
            ]
            try:
                result = compute_diamond_jewellery_price(
                    base_gold_price_21k_egp=base_gold_21k_egp,
                    gold_purity=product.gold_purity,
                    weight_g=product.jewellery_weight_g,
                    stone_prices_usd=valid_stone_prices,
                    exchange_rate_usd=exchange_rate,
                    fee_per_gram_usd=fee_per_gram,
                    ticket_multiplier=multiplier,
                    ticket_discount=discount,
                    min_sale_pct=min_pct,
                )
            except (ValueError, Exception) as e:
                _logger.warning(
                    'Diamond jewellery cron price update failed for %s: %s',
                    product.display_name, e,
                )
                skipped += 1
                continue

            # Write whenever the displayed price OR the (exact) gold cost moved,
            # so a gold-price change refreshes diamond pieces too — not only the
            # ones whose rounded EGP sale crossed a 50.
            if (abs(result['sale_price_egp'] - (product.list_price or 0.0)) < threshold
                    and abs(result['total_gold_cost_usd']
                            - (product.diamond_total_gold_cost_usd or 0.0)) < 0.005):
                skipped += 1
                continue

            product.write({
                'list_price': result['sale_price_egp'],
                'diamond_total_gold_cost_usd':   result['total_gold_cost_usd'],
                'diamond_total_stones_cost_usd':  result['total_stones_cost_usd'],
                'diamond_ticket_price_usd':       result['ticket_price_usd'],
                'diamond_sale_price_usd':         result['sale_price_usd'],
                'diamond_sale_price_egp':         result['sale_price_egp'],
                'diamond_min_sale_price':         result['min_sale_price_egp'],
            })
            updated += 1

        return (updated, skipped)

    def update_silver_prices(self, base_silver_999):
        """
        Update list price and silver cost/min for silver products.
        Called by cron (silver.price.service).

        :param base_silver_999: Silver 999 price per gram (EGP)
        :return: tuple(updated_count, skipped_count)
        """
        if not self:
            return (0, 0)
        threshold = self._price_update_threshold()
        silver_products = self.filtered(
            lambda p: p.is_silver_product
            and p.silver_purity
            and p.jewellery_weight_g
            and p.jewellery_weight_g > 0
        )
        if not silver_products:
            return (0, len(self))
        updated = 0
        skipped = len(self) - len(silver_products)
        markup_per_gram = get_silver_markup_per_gram(self.env)
        min_markup_per_gram = get_silver_min_markup_per_gram(self.env)
        for product in silver_products:
            try:
                cost_price, sale_price, min_sale_price = compute_silver_product_price(
                    base_silver_999_per_gram=base_silver_999,
                    weight_g=product.jewellery_weight_g,
                    markup_per_gram=markup_per_gram,
                    min_markup_per_gram=min_markup_per_gram,
                )
            except ValueError:
                skipped += 1
                continue
            # Write whenever any computed value moved (cost and the minimum are
            # exact, so a real silver-price move refreshes the whole inventory).
            if (abs(sale_price - (product.list_price or 0.0)) < threshold
                    and abs(cost_price - (product.silver_cost_price or 0.0)) < 0.005
                    and abs(min_sale_price - (product.silver_min_sale_price or 0.0)) < 0.005):
                skipped += 1
                continue
            product.write({
                'list_price': sale_price,
                'silver_cost_price': cost_price,
                'silver_min_sale_price': min_sale_price,
            })
            updated += 1
        return (updated, skipped)

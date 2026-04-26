# -*- coding: utf-8 -*-
# Copyright 2026 Revenax Digital Services
# Author: Mohamed A. Abdallah
# Website: https://www.revenax.com

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

from ..utils import get_markup_per_gram

# Same selections as product.template for gold fields on order line
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


class PosOrder(models.Model):
    _inherit = 'pos.order'

    require_customer = fields.Selection(
        related="session_id.config_id.require_customer",
    )

    @api.constrains("partner_id", "session_id")
    def _check_partner(self):
        for rec in self:
            if rec.require_customer != "no" and not rec.partner_id:
                raise ValidationError(
                    _("Customer is required for this order and is missing.")
                )

    def _enrich_order_line_vals_with_gold(self, line_vals):
        """
        Add jewellery and gold-specific fields to a single order line vals dict.
        Used when building order from UI.
        """
        product_id = line_vals.get('product_id')
        if not product_id:
            return
        product = self.env['product.product'].browse(product_id)
        if not product.exists():
            return

        line_vals['jewellery_type'] = getattr(product, 'jewellery_type', False)
        line_vals['jewellery_weight_g'] = getattr(product, 'jewellery_weight_g', 0.0) or 0.0
        line_vals['diamond_karat'] = getattr(product, 'diamond_karat', False)
        line_vals['silver_purity'] = getattr(product, 'silver_purity', False)

        if not getattr(product, 'is_gold_product', False):
            return
        line_vals['gold_purity'] = product.gold_purity
        line_vals['gold_weight_g'] = product.jewellery_weight_g or 0.0
        line_vals['gold_type'] = product.gold_type
        line_vals['making_fee'] = getattr(product, 'making_fee', 0.0) or 0.0
        try:
            gold_price_service = self.env['gold.price.service']
            line_vals['gold_price_per_gram'] = (
                gold_price_service.get_current_gold_price()
            )
        except Exception as e:
            raise ValidationError(
                _('Could not fetch gold price for order line. '
                  'Please check gold price settings. Details: %s') % str(e)
            ) from e

    @api.model
    def _order_fields(self, ui_order):
        """
        Override to validate gold product prices before order creation and to
        populate gold-specific fields on each order line from product and price
        service.
        """
        order_fields = super()._order_fields(ui_order)

        # Validate each line for gold products
        lines_data = ui_order.get('lines', [])
        for line_data in lines_data:
            if len(line_data) < 3 or not isinstance(line_data[2], dict):
                continue
            line_vals = line_data[2]
            product_id = line_vals.get('product_id')
            price_unit = line_vals.get('price_unit', 0)
            discount = line_vals.get('discount', 0)

            if product_id:
                product = self.env['product.product'].browse(product_id)
                if not product.exists():
                    continue
                if getattr(product, 'is_gold_product', False):
                    # Enforce minimum sale price; if none set, assume 20% max discount
                    effective_min = product.gold_min_sale_price or (price_unit * 0.8)
                    if effective_min > 0:
                        final_price = price_unit * (1 - discount / 100.0)
                        if final_price < effective_min:
                            raise ValidationError(
                                _(
                                    'Cannot sell %(name)s below minimum price of %(min).2f. '
                                    'Current price: %(price).2f'
                                )
                                % {
                                    'name': product.name,
                                    'min': effective_min,
                                    'price': final_price,
                                }
                            )

                    # Check if discount exceeds 50% of markup
                    # Markup total = markup per gram × weight (from settings)
                    has_weight = product.jewellery_weight_g and product.jewellery_weight_g > 0
                    if product.gold_type and has_weight:
                        weight_for_markup = (
                            product.jewellery_weight_g if product.gold_type == 'bars' else None
                        )
                        markup_per_gram = get_markup_per_gram(
                            self.env,
                            product.gold_type,
                            weight_g=weight_for_markup,
                        )

                        if markup_per_gram > 0 and product.list_price > 0:
                            markup_total = markup_per_gram * product.jewellery_weight_g
                            max_discount_percent = (
                                markup_total * 0.5 / product.list_price
                            ) * 100
                            if discount > max_discount_percent:
                                raise ValidationError(
                                    f'Discount for {product.name} cannot exceed '
                                    f'{max_discount_percent:.2f}% (50% of markup). '
                                    f'Current discount: {discount:.2f}%'
                                )
                elif getattr(product, 'is_silver_product', False):
                    effective_min = product.silver_min_sale_price or (price_unit * 0.8)
                    if effective_min > 0:
                        final_price = price_unit * (1 - discount / 100.0)
                        if final_price < effective_min:
                            raise ValidationError(
                                _(
                                    'Cannot sell %(name)s below minimum price of %(min).2f. '
                                    'Current price: %(price).2f'
                                )
                                % {
                                    'name': product.name,
                                    'min': effective_min,
                                    'price': final_price,
                                }
                            )

        # Validate storable product quantities do not exceed available stock
        self._check_storable_product_stock(ui_order, lines_data)

        # Populate gold fields on each order line from product and price service
        for line_cmd in order_fields.get('lines') or []:
            if len(line_cmd) >= 3 and isinstance(line_cmd[2], dict):
                self._enrich_order_line_vals_with_gold(line_cmd[2])

        return order_fields

    @api.model
    def _check_storable_product_stock(self, ui_order, lines_data):
        """
        Raise ValidationError if any storable product line requests more than
        available stock at the POS location. Consumables and services are ignored.
        """
        if not lines_data:
            return
        session_id = ui_order.get('pos_session_id')
        if not session_id:
            return
        session = self.env['pos.session'].browse(session_id)
        if not session.exists():
            return
        picking_type = session.config_id.picking_type_id
        if not picking_type:
            return
        location = picking_type.default_location_src_id
        if not location:
            return

        # Aggregate requested quantity per product (positive qty only; refunds excluded)
        product_qty: dict[int, float] = {}
        for line_data in lines_data:
            if len(line_data) < 3 or not isinstance(line_data[2], dict):
                continue
            line_vals = line_data[2]
            product_id = line_vals.get('product_id')
            qty = line_vals.get('qty', 0)
            try:
                qty = float(qty)
            except (TypeError, ValueError):
                qty = 0
            if product_id and qty > 0:
                product_qty[product_id] = product_qty.get(product_id, 0) + qty

        if not product_qty:
            return

        products = self.env['product.product'].browse(product_qty.keys())
        storable = products.filtered(lambda p: p.type == 'product')
        if not storable:
            return

        StockQuant = self.env['stock.quant']
        for product in storable:
            requested = product_qty.get(product.id, 0)
            if requested <= 0:
                continue
            quants = StockQuant.search([
                ('product_id', '=', product.id),
                ('location_id', '=', location.id),
            ])
            available = sum(
                (q.quantity - getattr(q, 'reserved_quantity', 0)) for q in quants
            )
            if requested > available:
                raise ValidationError(
                    _(
                        'Not enough stock for "%(name)s". Requested: %(requested)s, '
                        'available: %(available)s.'
                    )
                    % {
                        'name': product.display_name,
                        'requested': requested,
                        'available': available,
                    }
                )

    @api.model
    def _get_invoice_lines_values(self, line_values, pos_order_line, move_type):
        """
        Pass gold-specific fields from POS order line to invoice line so the
        invoice report can display them.
        """
        result = super()._get_invoice_lines_values(
            line_values, pos_order_line, move_type
        )
        jewellery_fields = [
            'jewellery_type', 'jewellery_weight_g', 'diamond_karat', 'silver_purity',
        ]
        for fname in jewellery_fields:
            if hasattr(pos_order_line, fname):
                result[fname] = pos_order_line[fname]

        product = pos_order_line.product_id
        if not product or not getattr(product, 'is_gold_product', False):
            return result
        gold_fields = [
            'gold_purity', 'gold_weight_g', 'gold_type',
            'gold_price_per_gram', 'making_fee',
        ]
        for fname in gold_fields:
            if hasattr(pos_order_line, fname):
                result[fname] = pos_order_line[fname]
        return result

    def _process_saved_order(self, draft):
        """Require invoice for every order when finalizing (not draft)."""
        if not draft and not self.to_invoice:
            raise UserError(
                _(
                    "An invoice must be set for every order. "
                    "Please enable invoicing for this order before paying."
                )
            )
        return super()._process_saved_order(draft)


class PosOrderLine(models.Model):
    _inherit = 'pos.order.line'

    jewellery_type = fields.Selection(
        selection=JEWELLERY_TYPE_SELECTION,
        string='Jewellery Type',
        help='Jewellery type at order time (copied from product).',
    )
    jewellery_weight_g = fields.Float(
        string='Jewellery Weight (g)',
        digits=(16, 2),
        help='Jewellery weight in grams at order time (copied from product).',
    )
    diamond_karat = fields.Char(
        string='Diamond Karat',
        help='Diamond karat/grade at order time (copied from product).',
    )
    silver_purity = fields.Selection(
        selection=SILVER_PURITY_SELECTION,
        string='Silver Purity',
        help='Silver purity at order time (copied from product).',
    )
    gold_purity = fields.Selection(
        selection=GOLD_PURITY_SELECTION,
        string='Gold Purity',
        help='Gold purity at order time (copied from product).',
    )
    gold_weight_g = fields.Float(
        string='Gold Weight (g)',
        digits=(16, 2),
        help='Gold weight in grams at order time (copied from product).',
    )
    gold_type = fields.Selection(
        selection=GOLD_TYPE_SELECTION,
        string='Gold Type',
        help='Gold type at order time (copied from product).',
    )
    gold_price_per_gram = fields.Float(
        string='Gold Price per Gram',
        digits=(16, 4),
        help='Gold price per gram at sale time (from price service).',
    )
    making_fee = fields.Float(
        string='Making Fee',
        digits=(16, 2),
        default=0.0,
        help='Making fee for this line (from product or overridden).',
    )

    @api.constrains('price_unit', 'discount')
    def _check_gold_minimum_price(self):
        """
        Constraint to ensure gold and silver products are not sold below minimum price.
        When no minimum sale price is set, assume 20% max discount (min = price_unit * 0.8).
        """
        for line in self:
            if line.product_id.is_gold_product:
                effective_min = (
                    line.product_id.gold_min_sale_price or (line.price_unit * 0.8)
                )
            elif line.product_id.is_silver_product:
                effective_min = (
                    line.product_id.silver_min_sale_price or (line.price_unit * 0.8)
                )
            else:
                continue
            if effective_min <= 0:
                continue
            final_price = line.price_unit * (1 - line.discount / 100.0)
            if final_price < effective_min:
                raise ValidationError(
                    _(
                        'Cannot sell %(name)s below minimum price of %(min).2f. '
                        'Current price: %(price).2f'
                    )
                    % {
                        'name': line.product_id.name,
                        'min': effective_min,
                        'price': final_price,
                    }
                )

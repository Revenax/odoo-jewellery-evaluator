# -*- coding: utf-8 -*-
# Copyright 2026 Revenax Digital Services
# Author: Mohamed A. Abdallah
# Website: https://www.revenax.com
"""Acquisition Order (AO): buying jewellery and stones from a vendor.

A jewellery-specific purchase document. Unlike a purchase order it never
receives stock: every piece gets its on-hand 1 when it is registered in the
operations app (the inventory invariant), and the AO only links those pieces.
What the AO records is the deal itself, by category / karat / origin and weight,
with the making fee per gram, plus the loose stones bought, and (later phases)
the payments and returns that settle the vendor's balance.

Totals are computed by ``utils.acquisition_totals`` (tested).
"""

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from ..utils import acquisition_totals
from .jewellery_stone import STONE_CLARITY_SELECTION, STONE_COLOR_SELECTION, STONE_SHAPE_SELECTION

KARAT_SELECTION = [('24K', '24K'), ('21K', '21K'), ('18K', '18K')]
ORIGIN_SELECTION = [('local', 'Local'), ('foreign', 'Foreign')]


class JewelleryAcquisitionOrder(models.Model):
    _name = 'jewellery.acquisition.order'
    _description = 'Acquisition Order'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date_order desc, id desc'

    name = fields.Char(string='Reference', required=True, copy=False, readonly=True, default='New', index=True)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('confirmed', 'Confirmed'),
        ('done', 'Done'),
        ('cancel', 'Cancelled'),
    ], default='draft', required=True, tracking=True, copy=False)
    partner_id = fields.Many2one('res.partner', string='Vendor', required=True, tracking=True, index=True)
    employee_id = fields.Many2one(
        'hr.employee', string='Employee', tracking=True,
        default=lambda self: self.env.user.employee_id)
    user_id = fields.Many2one('res.users', string='User', default=lambda self: self.env.user, tracking=True)
    date_order = fields.Datetime(string='Date', required=True, default=fields.Datetime.now, tracking=True)
    warehouse_id = fields.Many2one('stock.warehouse', string='Branch', tracking=True,
                                   help='Where the pieces will be registered.')
    vendor_ref = fields.Char(string='Vendor reference', tracking=True)
    note = fields.Html(string='Notes')
    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company)
    currency_id = fields.Many2one(related='company_id.currency_id')
    usd_currency_id = fields.Many2one('res.currency', default=lambda self: self.env.ref('base.USD'))

    gold_price_21k = fields.Monetary(
        string='Gold price 21K / g', currency_field='currency_id', tracking=True,
        default=lambda self: self._default_gold_price(),
        help='Used for the metal value. Suggested from the live price; any positive value is accepted.')
    usd_rate = fields.Float(
        string='USD rate', digits=(12, 4), tracking=True,
        default=lambda self: self._default_usd_rate(),
        help='EGP per USD for the stones. Suggested from the live rate.')

    line_ids = fields.One2many('jewellery.acquisition.line', 'order_id', string='Jewellery', copy=True)
    stone_ids = fields.One2many('jewellery.acquisition.stone', 'order_id', string='Stones', copy=True)
    product_ids = fields.One2many('product.template', 'acquisition_order_id', string='SKUs')

    # Totals (utils.acquisition_totals)
    total_pieces = fields.Integer(compute='_compute_totals', store=True)
    grams_24k = fields.Float(string='24K grams', digits=(12, 3), compute='_compute_totals', store=True)
    grams_21k = fields.Float(string='21K grams', digits=(12, 3), compute='_compute_totals', store=True)
    grams_18k = fields.Float(string='18K grams', digits=(12, 3), compute='_compute_totals', store=True)
    grams_21k_eq = fields.Float(string='21K equivalent (g)', digits=(12, 3), compute='_compute_totals', store=True)
    making_fee_total = fields.Monetary(string='Making fee', compute='_compute_totals', store=True)
    metal_value = fields.Monetary(compute='_compute_totals', store=True)
    stone_count = fields.Integer(compute='_compute_totals', store=True)
    stone_carats = fields.Float(string='Carats', digits=(12, 3), compute='_compute_totals', store=True)
    stones_usd = fields.Monetary(string='Stones (USD)', currency_field='usd_currency_id',
                                 compute='_compute_totals', store=True)
    stones_egp = fields.Monetary(string='Stones (EGP)', compute='_compute_totals', store=True)
    total_egp = fields.Monetary(string='Total', compute='_compute_totals', store=True)

    # SKUs registered against the order
    registered_count = fields.Integer(string='Registered', compute='_compute_registered')
    unregistered_count = fields.Integer(string='Not registered yet', compute='_compute_registered')
    registered_grams = fields.Float(string='Registered grams', digits=(12, 3), compute='_compute_registered')
    unregistered_grams = fields.Float(string='Grams not registered yet', digits=(12, 3),
                                      compute='_compute_registered')

    # ------------------------------------------------------------------ defaults
    @api.model
    def _default_gold_price(self):
        try:
            return float(self.env['ir.config_parameter'].sudo().get_param('jewellery_evaluator.fallback_price') or 0)
        except (TypeError, ValueError):
            return 0.0

    @api.model
    def _default_usd_rate(self):
        icp = self.env['ir.config_parameter'].sudo()
        for key in ('jewellery_evaluator.feed_usd_egp', 'jewellery_evaluator.diamond_exchange_rate_usd'):
            try:
                value = float(icp.get_param(key) or 0)
            except (TypeError, ValueError):
                value = 0.0
            if value > 0:
                return value
        return 0.0

    # ------------------------------------------------------------------ computes
    @api.depends('line_ids.karat', 'line_ids.qty', 'line_ids.grams', 'line_ids.fee_per_gram',
                 'stone_ids.qty', 'stone_ids.carats', 'stone_ids.price_per_carat_usd',
                 'gold_price_21k', 'usd_rate')
    def _compute_totals(self):
        for order in self:
            t = acquisition_totals(
                [{'karat': line.karat, 'qty': line.qty, 'grams': line.grams, 'fee_per_gram': line.fee_per_gram}
                 for line in order.line_ids],
                [{'qty': s.qty, 'carats': s.carats, 'price_per_carat_usd': s.price_per_carat_usd}
                 for s in order.stone_ids],
                order.gold_price_21k, order.usd_rate)
            order.update({
                'total_pieces': t['pieces'],
                'grams_24k': t['grams']['24K'],
                'grams_21k': t['grams']['21K'],
                'grams_18k': t['grams']['18K'],
                'grams_21k_eq': t['grams_21k_eq'],
                'making_fee_total': t['making_fee'],
                'metal_value': t['metal_value'],
                'stone_count': t['stone_count'],
                'stone_carats': t['carats'],
                'stones_usd': t['stones_usd'],
                'stones_egp': t['stones_egp'],
                'total_egp': t['total_egp'],
            })

    @api.depends('product_ids', 'total_pieces', 'line_ids.grams')
    def _compute_registered(self):
        for order in self:
            products = order.product_ids
            grams = sum(products.mapped('gross_jewellery_weight_g') or [0.0])
            order.registered_count = len(products)
            order.registered_grams = round(grams, 3)
            order.unregistered_count = max(order.total_pieces - len(products), 0)
            order.unregistered_grams = round(max(sum(order.line_ids.mapped('grams')) - grams, 0.0), 3)

    # ------------------------------------------------------------------ lifecycle
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('jewellery.acquisition.order') or 'New'
        return super().create(vals_list)

    def action_confirm(self):
        for order in self:
            if order.state != 'draft':
                continue
            if not order.line_ids and not order.stone_ids:
                raise UserError(_('Add at least one jewellery or stone line before confirming %s.', order.name))
            if order.line_ids and order.gold_price_21k <= 0:
                raise UserError(_('Set a positive gold price on %s.', order.name))
            if order.stone_ids and order.usd_rate <= 0:
                raise UserError(_('Set a positive USD rate on %s.', order.name))
        self.filtered(lambda o: o.state == 'draft').write({'state': 'confirmed'})

    def action_done(self):
        self.filtered(lambda o: o.state == 'confirmed').write({'state': 'done'})

    def action_cancel(self):
        for order in self:
            if order.product_ids:
                raise UserError(_('%s already has registered pieces; it cannot be cancelled.', order.name))
        self.write({'state': 'cancel'})

    def action_draft(self):
        self.filtered(lambda o: o.state in ('confirmed', 'cancel')).write({'state': 'draft'})

    def unlink(self):
        if any(o.state not in ('draft', 'cancel') for o in self):
            raise UserError(_('Only draft or cancelled acquisition orders can be deleted.'))
        if self.mapped('product_ids'):
            raise UserError(_('An acquisition order with registered pieces cannot be deleted.'))
        return super().unlink()


class JewelleryAcquisitionLine(models.Model):
    _name = 'jewellery.acquisition.line'
    _description = 'Acquisition Order jewellery line'
    _order = 'order_id, sequence, id'

    order_id = fields.Many2one('jewellery.acquisition.order', required=True, ondelete='cascade', index=True)
    sequence = fields.Integer(default=10)
    categ_id = fields.Many2one(
        'product.category', string='Category', required=True,
        domain="['|', '|', ('complete_name', '=like', 'Gold / %'), ('complete_name', '=like', 'Diamond / %'),"
               " ('complete_name', '=like', 'Silver / %')]")
    karat = fields.Selection(KARAT_SELECTION, required=True, default='18K')
    origin = fields.Selection(ORIGIN_SELECTION, required=True, default='local')
    qty = fields.Integer(string='Qty', required=True, default=1)
    grams = fields.Float(digits=(12, 3), required=True)
    fee_per_gram = fields.Monetary(string='Making fee / g', currency_field='currency_id')
    fee_total = fields.Monetary(string='Making fee', currency_field='currency_id',
                                compute='_compute_fee_total', store=True)
    currency_id = fields.Many2one(related='order_id.currency_id')
    registered_count = fields.Integer(string='Registered', compute='_compute_registered')

    @api.depends('grams', 'fee_per_gram')
    def _compute_fee_total(self):
        for line in self:
            line.fee_total = round(line.grams * line.fee_per_gram, 2)

    def _compute_registered(self):
        for line in self:
            line.registered_count = len(line.order_id.product_ids.filtered(
                lambda p, line=line: p.categ_id == line.categ_id and p.gold_purity == line.karat))

    @api.constrains('qty', 'grams', 'fee_per_gram')
    def _check_positive(self):
        for line in self:
            if line.qty < 0 or line.grams < 0 or line.fee_per_gram < 0:
                raise UserError(_('Quantity, grams and making fee cannot be negative.'))


class JewelleryAcquisitionStone(models.Model):
    _name = 'jewellery.acquisition.stone'
    _description = 'Acquisition Order stone line'
    _order = 'order_id, sequence, id'

    order_id = fields.Many2one('jewellery.acquisition.order', required=True, ondelete='cascade', index=True)
    sequence = fields.Integer(default=10)
    shape = fields.Selection(STONE_SHAPE_SELECTION, required=True, default='Round')
    color = fields.Selection(STONE_COLOR_SELECTION)
    clarity = fields.Selection(STONE_CLARITY_SELECTION)
    qty = fields.Integer(string='Stones', required=True, default=1)
    carats = fields.Float(string='Total carats', digits=(12, 3), required=True)
    price_per_carat_usd = fields.Monetary(string='USD / ct', currency_field='usd_currency_id')
    total_usd = fields.Monetary(string='Total USD', currency_field='usd_currency_id',
                                compute='_compute_total', store=True)
    usd_currency_id = fields.Many2one(related='order_id.usd_currency_id')
    note = fields.Char()

    @api.depends('carats', 'price_per_carat_usd')
    def _compute_total(self):
        for stone in self:
            stone.total_usd = round(stone.carats * stone.price_per_carat_usd, 2)

    @api.constrains('qty', 'carats', 'price_per_carat_usd')
    def _check_positive(self):
        for stone in self:
            if stone.qty < 0 or stone.carats < 0 or stone.price_per_carat_usd < 0:
                raise UserError(_('Stones, carats and price cannot be negative.'))


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    acquisition_order_id = fields.Many2one(
        'jewellery.acquisition.order', string='Acquisition Order', index=True, copy=False,
        help='The AO this piece was bought on (set when it is registered).')

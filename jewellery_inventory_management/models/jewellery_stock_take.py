# -*- coding: utf-8 -*-
# Copyright 2026 Revenax Digital Services
# Author: Mohamed A. Abdallah
# Website: https://www.revenax.com

from odoo import api, fields, models
from odoo.exceptions import UserError


class JewelleryStockTake(models.Model):
    """A full stock count of a warehouse (or one of its locations).

    Starting it creates one mini count (``jewellery.stock.count``) per SKU
    prefix that has pieces on hand in the scope. Staff scan inside each mini
    count, several at once on different prefixes; a piece scanned in the
    wrong mini is filed into its own prefix's mini. Each mini is approved
    with an admin badge on its own; the full count is done when every mini is.
    """

    _name = 'jewellery.stock.take'
    _description = 'Full Stock Count'
    _order = 'create_date desc, id desc'

    name = fields.Char(default='New', required=True, copy=False, readonly=True)
    warehouse_id = fields.Many2one(
        'stock.warehouse', string='Warehouse', required=True,
        default=lambda self: self.env['stock.warehouse'].search(
            [('company_id', '=', self.env.company.id)], limit=1))
    location_id = fields.Many2one(
        'stock.location', string='Location',
        domain="[('usage', '=', 'internal'), ('warehouse_id', '=', warehouse_id)]",
        help='Count only this location. Leave empty to count the whole warehouse.')
    state = fields.Selection(
        [('draft', 'Draft'), ('in_progress', 'In Progress'), ('done', 'Done')],
        default='draft', required=True, copy=False)
    user_id = fields.Many2one('res.users', string='Started By', default=lambda self: self.env.user)
    start_date = fields.Datetime(readonly=True, copy=False)
    end_date = fields.Datetime(readonly=True, copy=False)
    note = fields.Text()

    count_ids = fields.One2many('jewellery.stock.count', 'take_id', string='Mini Counts', copy=False)

    mini_total = fields.Integer(compute='_compute_stats', string='Mini Counts')
    mini_done = fields.Integer(compute='_compute_stats', string='Approved')
    expected_count = fields.Integer(compute='_compute_stats', string='Expected')
    found_count = fields.Integer(compute='_compute_stats', string='Found')
    missing_count = fields.Integer(compute='_compute_stats', string='Missing')
    unexpected_count = fields.Integer(compute='_compute_stats', string='Unexpected')
    progress = fields.Float(compute='_compute_stats', digits=(5, 1))
    missing_net_gold_g = fields.Float(compute='_compute_stats', digits=(16, 3), string='Missing net gold (g)')

    @api.depends('count_ids.state', 'count_ids.line_ids.status')
    def _compute_stats(self):
        for take in self:
            counts = take.count_ids
            take.mini_total = len(counts)
            take.mini_done = len(counts.filtered(lambda c: c.state == 'done'))
            take.expected_count = sum(counts.mapped('expected_count'))
            take.found_count = sum(counts.mapped('found_count'))
            take.missing_count = sum(counts.mapped('missing_count'))
            take.unexpected_count = sum(counts.mapped('unexpected_count'))
            take.progress = round(100.0 * take.found_count / take.expected_count, 1) if take.expected_count else 0.0
            take.missing_net_gold_g = sum(counts.mapped('missing_net_gold_g'))

    @api.onchange('warehouse_id')
    def _onchange_warehouse_id(self):
        self.location_id = False

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('jewellery.stock.take') or 'New'
        return super().create(vals_list)

    def _scope_locations(self):
        self.ensure_one()
        if self.location_id:
            return self.location_id
        return self.env['stock.location'].search([
            ('usage', '=', 'internal'), ('id', 'child_of', self.warehouse_id.view_location_id.id)])

    def _prefixes_in_scope(self):
        """SKU prefixes with pieces on hand in the scope, with how many."""
        self.ensure_one()
        locations = self._scope_locations()
        if not locations:
            return []
        self.env.cr.execute("""
            SELECT upper(split_part(pp.default_code, '-', 1)) AS prefix, count(DISTINCT pp.id)
              FROM stock_quant q
              JOIN product_product pp ON pp.id = q.product_id
             WHERE q.quantity > 0 AND q.location_id IN %s AND pp.default_code LIKE '%%-%%'
             GROUP BY 1 ORDER BY 1
        """, (tuple(locations.ids),))
        return self.env.cr.fetchall()

    def action_start(self):
        self.ensure_one()
        if self.state != 'draft':
            raise UserError('This count has already started.')
        prefixes = self._prefixes_in_scope()
        if not prefixes:
            raise UserError('No pieces on hand here to count.')
        Count = self.env['jewellery.stock.count']
        for prefix, _n in prefixes:
            mini = Count.create({
                'take_id': self.id,
                'sku_prefix': prefix,
                'warehouse_id': self.warehouse_id.id,
                'location_id': self.location_id.id or False,
            })
            mini.action_start()
        self.write({'state': 'in_progress', 'start_date': fields.Datetime.now()})
        return True

    def _check_done(self):
        """Close the full count once every mini count is approved."""
        for take in self.filtered(lambda t: t.state == 'in_progress'):
            if take.count_ids and all(c.state == 'done' for c in take.count_ids):
                take.write({'state': 'done', 'end_date': fields.Datetime.now()})

    def action_reset_to_draft(self):
        self.ensure_one()
        if self.count_ids.filtered(lambda c: c.state == 'done'):
            raise UserError('Some mini counts are already approved and have changed stock; this count cannot be reset.')
        self.count_ids.unlink()
        self.write({'state': 'draft', 'start_date': False, 'end_date': False})

# -*- coding: utf-8 -*-
# Copyright 2026 Revenax Digital Services
# Author: Mohamed A. Abdallah
# Website: https://www.revenax.com

from odoo import api, fields, models
from odoo.exceptions import UserError


class JewelleryStockCount(models.Model):
    """A physical stock-count *operation*: pick a SKU prefix and a scope
    (a single location, or a whole warehouse), generate the set of pieces that
    should be on hand, then scan each one with a barcode scanner. What never
    gets scanned is 'missing'; a scan that wasn't expected is 'unexpected'."""

    _name = 'jewellery.stock.count'
    _description = 'Jewellery Stock Count Operation'
    _order = 'create_date desc, id desc'

    name = fields.Char(default='New', required=True, copy=False, readonly=True)
    sku_prefix = fields.Char(
        string='SKU Prefix', required=True,
        help='Count every in-stock piece whose internal reference starts with '
             'this prefix, e.g. "GBF8".')
    warehouse_id = fields.Many2one(
        'stock.warehouse', string='Warehouse',
        help='Count all internal locations of this warehouse. Ignored when a '
             'specific location is set below.')
    location_id = fields.Many2one(
        'stock.location', string='Location',
        domain="[('usage', '=', 'internal')]",
        help='Count only this location. Leave empty to count the whole '
             'warehouse above.')
    state = fields.Selection(
        [('draft', 'Draft'), ('in_progress', 'In Progress'), ('done', 'Done')],
        default='draft', required=True, copy=False)
    user_id = fields.Many2one(
        'res.users', string='Counted By', default=lambda self: self.env.user)
    start_date = fields.Datetime(readonly=True, copy=False)
    end_date = fields.Datetime(readonly=True, copy=False)
    note = fields.Text()

    line_ids = fields.One2many(
        'jewellery.stock.count.line', 'count_id', string='Lines', copy=False)

    expected_count = fields.Integer(compute='_compute_stats')
    found_count = fields.Integer(compute='_compute_stats')
    missing_count = fields.Integer(compute='_compute_stats')
    unexpected_count = fields.Integer(compute='_compute_stats')
    progress = fields.Float(compute='_compute_stats', digits=(5, 1))

    # Weights accounted for (found) vs not yet found (missing), in grams.
    found_net_gold_g = fields.Float(compute='_compute_weights', digits=(16, 3))
    missing_net_gold_g = fields.Float(compute='_compute_weights', digits=(16, 3))
    found_stones_g = fields.Float(compute='_compute_weights', digits=(16, 3))
    missing_stones_g = fields.Float(compute='_compute_weights', digits=(16, 3))
    found_jewellery_g = fields.Float(compute='_compute_weights', digits=(16, 3))
    missing_jewellery_g = fields.Float(compute='_compute_weights', digits=(16, 3))
    found_reading_g = fields.Float(compute='_compute_weights', digits=(16, 3))
    missing_reading_g = fields.Float(compute='_compute_weights', digits=(16, 3))

    @api.depends('line_ids.status')
    def _compute_stats(self):
        for count in self:
            stats = count._stats_dict()
            count.found_count = stats['found']
            count.missing_count = stats['missing']
            count.unexpected_count = stats['unexpected']
            count.expected_count = stats['expected']
            count.progress = stats['progress']

    @api.depends('line_ids.status', 'line_ids.net_gold_weight_g',
                 'line_ids.stones_weight_g', 'line_ids.jewellery_weight_g',
                 'line_ids.weight_reading_g')
    def _compute_weights(self):
        for count in self:
            found = count.line_ids.filtered(lambda line: line.status == 'found')
            missing = count.line_ids.filtered(lambda line: line.status == 'to_find')
            count.found_net_gold_g = sum(found.mapped('net_gold_weight_g'))
            count.missing_net_gold_g = sum(missing.mapped('net_gold_weight_g'))
            count.found_stones_g = sum(found.mapped('stones_weight_g'))
            count.missing_stones_g = sum(missing.mapped('stones_weight_g'))
            count.found_jewellery_g = sum(found.mapped('jewellery_weight_g'))
            count.missing_jewellery_g = sum(missing.mapped('jewellery_weight_g'))
            count.found_reading_g = sum(found.mapped('weight_reading_g'))
            count.missing_reading_g = sum(missing.mapped('weight_reading_g'))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'jewellery.stock.count') or 'New'
        return super().create(vals_list)

    # --- scope / expected set ------------------------------------------------

    def _scope_locations(self):
        """Internal locations this count covers: the specific location if set,
        otherwise every internal location under the chosen warehouse."""
        self.ensure_one()
        if self.location_id:
            return self.location_id
        if self.warehouse_id:
            return self.env['stock.location'].search([
                ('usage', '=', 'internal'),
                ('id', 'child_of', self.warehouse_id.view_location_id.id),
            ])
        return self.env['stock.location']

    def _prefix(self):
        return (self.sku_prefix or '').strip().upper()

    @staticmethod
    def _code_prefix(code):
        return (code or '').strip().split('-')[0].upper()

    def _expected_products(self, locations):
        """product.product with our prefix and positive on-hand in the scope."""
        quants = self.env['stock.quant'].sudo().search([
            ('location_id', 'in', locations.ids), ('quantity', '>', 0),
        ])
        prefix = self._prefix()
        return quants.product_id.filtered(
            lambda p: self._code_prefix(p.default_code) == prefix)

    # --- actions -------------------------------------------------------------

    def action_start(self):
        self.ensure_one()
        if not self._prefix():
            raise UserError('Please set a SKU prefix to count.')
        locations = self._scope_locations()
        if not locations:
            raise UserError('Please choose a warehouse or a location to count.')
        self.line_ids.unlink()
        products = self._expected_products(locations)
        self.write({
            'state': 'in_progress',
            'start_date': fields.Datetime.now(),
            'line_ids': [
                (0, 0, {'product_id': p.id, 'status': 'to_find'})
                for p in products
            ],
        })
        return self.action_open_scanner()

    def action_open_scanner(self):
        self.ensure_one()
        if self.state == 'draft':
            return self.action_start()
        return {
            'type': 'ir.actions.client',
            'tag': 'jewellery_stock_count_scanner',
            'name': self.name,
            'params': {'count_id': self.id},
            'context': {'active_id': self.id, 'count_id': self.id},
        }

    def action_finish(self):
        self.ensure_one()
        self.write({'state': 'done', 'end_date': fields.Datetime.now()})
        return True

    def action_reset_to_draft(self):
        self.ensure_one()
        self.line_ids.unlink()
        self.write({'state': 'draft', 'start_date': False, 'end_date': False})

    # --- scanning ------------------------------------------------------------

    def process_scan(self, barcode):
        """Resolve one scanned barcode against the expected set. Returns the
        result dict the scan screen renders."""
        self.ensure_one()
        code = (barcode or '').strip()
        if not code:
            return self._scan_result('empty', '', 'Empty scan')

        product = self.env['product.product'].search(
            ['|', ('barcode', '=', code), ('default_code', '=', code)], limit=1)
        if not product:
            return self._scan_result('unknown', code, 'Unknown barcode')

        sku = product.default_code or product.display_name
        line = self.line_ids.filtered(lambda line: line.product_id == product)[:1]
        if line and line.status == 'found':
            return self._scan_result('already', sku, 'Already counted')
        if line and line.status == 'to_find':
            line.write({'status': 'found', 'scanned_at': fields.Datetime.now()})
            return self._scan_result('found', sku, 'Counted')

        reason = self._unexpected_reason(product)
        self.env['jewellery.stock.count.line'].create({
            'count_id': self.id,
            'product_id': product.id,
            'status': 'unexpected',
            'reason': reason,
            'scanned_at': fields.Datetime.now(),
        })
        return self._scan_result('unexpected', sku, reason)

    def _unexpected_reason(self, product):
        if self._code_prefix(product.default_code) != self._prefix():
            return 'wrong prefix'
        on_hand = sum(self.env['stock.quant'].sudo().search([
            ('product_id', '=', product.id),
            ('location_id', 'in', self._scope_locations().ids),
        ]).mapped('quantity'))
        if on_hand <= 0:
            return 'sold / no stock here'
        return 'not in this count'

    # --- payloads for the OWL scan screen ------------------------------------

    @staticmethod
    def _wsum(lines):
        return {
            'net_gold': round(sum(lines.mapped('net_gold_weight_g')), 3),
            'stones': round(sum(lines.mapped('stones_weight_g')), 3),
            'jewellery': round(sum(lines.mapped('jewellery_weight_g')), 3),
            'readings': round(sum(lines.mapped('weight_reading_g')), 3),
        }

    def _stats_dict(self):
        self.ensure_one()
        found_lines = self.line_ids.filtered(lambda line: line.status == 'found')
        to_find_lines = self.line_ids.filtered(lambda line: line.status == 'to_find')
        found = len(found_lines)
        to_find = len(to_find_lines)
        unexpected = len(
            self.line_ids.filtered(lambda line: line.status == 'unexpected'))
        expected = found + to_find
        return {
            'expected': expected,
            'found': found,
            'missing': to_find,
            'unexpected': unexpected,
            'progress': round(100.0 * found / expected, 1) if expected else 0.0,
            'weights': {
                'found': self._wsum(found_lines),
                'missing': self._wsum(to_find_lines),
            },
        }

    def _lines_payload(self):
        self.ensure_one()
        out = []
        for line in self.line_ids:
            scanned = fields.Datetime.to_string(line.scanned_at) if line.scanned_at else ''
            out.append({
                'id': line.id,
                'sku': line.default_code or '',
                'status': line.status,
                'reason': line.reason or '',
                'scanned_at': scanned[11:19] if scanned else '',
            })
        return out

    def _scan_result(self, result, sku, message):
        self.ensure_one()
        return {
            'result': result,
            'sku': sku,
            'message': message,
            'stats': self._stats_dict(),
            'lines': self._lines_payload(),
        }

    def get_scan_state(self):
        """Full state for the scan screen on load."""
        self.ensure_one()
        scope = self.location_id.display_name or (
            self.warehouse_id.display_name if self.warehouse_id else '')
        return {
            'id': self.id,
            'name': self.name,
            'sku_prefix': self.sku_prefix or '',
            'scope': scope,
            'state': self.state,
            'stats': self._stats_dict(),
            'lines': self._lines_payload(),
        }


class JewelleryStockCountLine(models.Model):
    _name = 'jewellery.stock.count.line'
    _description = 'Jewellery Stock Count Line'
    _order = 'status, default_code'

    count_id = fields.Many2one(
        'jewellery.stock.count', required=True, ondelete='cascade', index=True)
    product_id = fields.Many2one(
        'product.product', required=True, ondelete='cascade', index=True)
    default_code = fields.Char(
        related='product_id.default_code', string='SKU', store=True)
    status = fields.Selection(
        [('to_find', 'To find'), ('found', 'Found'),
         ('unexpected', 'Unexpected')],
        default='to_find', required=True, index=True)
    reason = fields.Char(string='Note')
    scanned_at = fields.Datetime()

    # Per-piece weights, pulled from the product template (see the Weight
    # Inventory report). Stored so they aggregate per count without re-reading
    # the product each time.
    net_gold_weight_g = fields.Float(
        related='product_id.product_tmpl_id.net_gold_weight_g',
        string='Net Gold (g)', store=True, digits=(16, 3))
    stones_weight_g = fields.Float(
        related='product_id.product_tmpl_id.diamond_weight_g',
        string='Stones (g)', store=True, digits=(16, 3))
    jewellery_weight_g = fields.Float(
        related='product_id.product_tmpl_id.gross_jewellery_weight_g',
        string='Jewellery (g)', store=True, digits=(16, 3))
    weight_reading_g = fields.Float(
        related='product_id.product_tmpl_id.weight_reading_g',
        string='Reading (g)', store=True, digits=(16, 3))

# -*- coding: utf-8 -*-
# Copyright 2026 Revenax Digital Services
# Author: Mohamed A. Abdallah
# Website: https://www.revenax.com

import logging

from odoo import api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# Lost pieces are expensed here (scripts/accounting/configure_accounting.py).
INVENTORY_LOSS_ACCOUNT_CODE = '400071'

RESOLUTIONS = [
    ('lost', 'Lost'),
    ('sold_no_invoice', 'Sold without invoice'),
    ('other_location', 'In another location'),
    ('keep', 'Leave in stock'),
    # For an unexpected scan of a piece Odoo has in another location.
    ('transfer_here', 'Transfer to this location'),
]
MISSING_RESOLUTIONS = ('lost', 'sold_no_invoice', 'other_location', 'keep')


class JewelleryStockCount(models.Model):
    """A physical stock-count *operation*: pick a SKU prefix and a scope
    (a single location, or a whole warehouse), generate the set of pieces that
    should be on hand, then scan each one with a barcode scanner. What never
    gets scanned is 'missing'; a scan that wasn't expected is 'unexpected'.

    Every missing piece must be resolved (lost, sold without invoice, in
    another location, or left in stock) before the count can close, and
    closing needs an admin's badge. Only then is stock changed:

    * lost: off on-hand, its cost to Inventory Loss (400071);
    * sold without invoice: off on-hand, its cost to its cost-of-sales
      account (no revenue or cash is recorded);
    * in another location: moved there;
    * left in stock: nothing changes.

    A scanned piece that Odoo has in another location is moved here at once,
    with a note on its line (an internal move, no accounting effect). Other
    unexpected scans are reported only."""

    _name = 'jewellery.stock.count'
    _description = 'Jewellery Stock Count Operation'
    _order = 'create_date desc, id desc'

    name = fields.Char(default='New', required=True, copy=False, readonly=True)
    prefix_choice = fields.Selection(
        selection='_prefix_options', string='Pieces to count', store=False,
        help='SKU prefixes with pieces in stock, and how many.')
    sku_prefix = fields.Char(
        string='SKU Prefix', required=True,
        help='Count every in-stock piece whose internal reference starts with '
             'this prefix, e.g. "GBF8".')
    warehouse_id = fields.Many2one(
        'stock.warehouse', string='Warehouse',
        default=lambda self: self.env['stock.warehouse'].search(
            [('company_id', '=', self.env.company.id)], limit=1),
        help='Count all internal locations of this warehouse. Ignored when a '
             'specific location is set below.')
    location_id = fields.Many2one(
        'stock.location', string='Location',
        domain="[('usage', '=', 'internal'), ('warehouse_id', '=', warehouse_id)]",
        default=lambda self: self.env['stock.warehouse'].search(
            [('company_id', '=', self.env.company.id)], limit=1).lot_stock_id,
        help='Count only this location. Leave empty to count the whole '
             'warehouse above.')
    state = fields.Selection(
        [('draft', 'Draft'), ('in_progress', 'In Progress'), ('done', 'Done')],
        default='draft', required=True, copy=False)
    approved_by_employee_id = fields.Many2one(
        'hr.employee', string='Approved By', readonly=True, copy=False)
    approved_at = fields.Datetime(readonly=True, copy=False)
    adjustment_move_ids = fields.Many2many(
        'account.move', string='Stock Count Entries', readonly=True, copy=False)
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

    @api.model
    def _prefix_options(self):
        """SKU prefixes with pieces in stock anywhere, with how many."""
        self.env.cr.execute("""
            SELECT upper(split_part(pp.default_code, '-', 1)) AS prefix, count(DISTINCT pp.id)
              FROM stock_quant q
              JOIN stock_location l ON l.id = q.location_id AND l.usage = 'internal'
              JOIN product_product pp ON pp.id = q.product_id
             WHERE q.quantity > 0 AND pp.default_code LIKE '%%-%%'
             GROUP BY 1 ORDER BY 1
        """)
        return [(prefix, f'{prefix} · {n} in stock') for prefix, n in self.env.cr.fetchall()]

    @api.onchange('prefix_choice')
    def _onchange_prefix_choice(self):
        if self.prefix_choice:
            self.sku_prefix = self.prefix_choice

    @api.onchange('warehouse_id')
    def _onchange_warehouse_id(self):
        # The warehouse's main stock location by default; clear it to count the
        # whole warehouse.
        self.location_id = self.warehouse_id.lot_stock_id

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

    def _home_location(self):
        """Where 'transfer to this location' puts a piece."""
        self.ensure_one()
        return self.location_id or self.warehouse_id.lot_stock_id

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
        """Closing needs an admin badge, which the scan screen asks for."""
        return self.action_open_scanner()

    def action_reset_to_draft(self):
        self.ensure_one()
        if self.state == 'done':
            raise UserError('An approved count has already changed stock and cannot be reset.')
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
            # Found after all: any decision taken while it was missing is void.
            line.write({'status': 'found', 'scanned_at': fields.Datetime.now(),
                        'resolution': False, 'resolution_location_id': False})
            return self._scan_result('found', sku, 'Counted')

        if line and line.status == 'unexpected':
            return self._scan_result('already', sku, f'Already scanned ({line.reason})')

        # Odoo has it in another location but it is physically here: move it
        # here now, with a note, and carry on scanning. An internal move has no
        # accounting effect, so it needs no approval.
        elsewhere = self._elsewhere_quants(product)
        in_scope = self.env['stock.quant'].sudo().search_count([
            ('product_id', '=', product.id), ('location_id', 'in', self._scope_locations().ids),
            ('quantity', '>', 0)])
        home = self._home_location()
        if elsewhere and not in_scope and home and self.state == 'in_progress':
            origin = ', '.join(elsewhere.location_id.mapped('complete_name'))
            elsewhere.move_quants(location_dest_id=home,
                                  message=f'{self.name}: {sku} scanned in {home.complete_name}')
            note = f'moved here from {origin}'
            ours = self._code_prefix(product.default_code) == self._prefix()
            self.env['jewellery.stock.count.line'].create({
                'count_id': self.id,
                'product_id': product.id,
                'status': 'found' if ours else 'unexpected',
                'reason': note if ours else f'wrong prefix; {note}',
                'scanned_at': fields.Datetime.now(),
            })
            return self._scan_result('moved', sku, f'Counted, {note}' if ours else f'Wrong prefix; {note}')

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
        quants = self.env['stock.quant'].sudo().search([
            ('product_id', '=', product.id), ('location_id.usage', '=', 'internal'), ('quantity', '>', 0)])
        scope = self._scope_locations()
        here = quants.filtered(lambda q: q.location_id in scope)
        if here:
            return 'not in this count'
        if quants:
            return 'in ' + ', '.join(quants.location_id.mapped('complete_name'))
        return 'sold / no stock in Odoo'

    def _elsewhere_quants(self, product):
        """On-hand of this piece in internal locations outside this count."""
        return self.env['stock.quant'].sudo().search([
            ('product_id', '=', product.id), ('location_id.usage', '=', 'internal'),
            ('location_id', 'not in', self._scope_locations().ids), ('quantity', '>', 0)])

    # --- resolving missing pieces ---------------------------------------------

    def _check_open(self):
        if self.state != 'in_progress':
            raise UserError('This count is not in progress.')

    def set_resolution(self, line_id, resolution, location_id=False):
        """Mark a missing piece (from the scan screen). ``resolution`` False
        clears it. Nothing changes in stock until the count is approved."""
        self.ensure_one()
        self._check_open()
        line = self.line_ids.filtered(lambda line: line.id == line_id)
        if not line or line.status == 'found':
            raise UserError('This piece was counted; there is nothing to decide.')
        if resolution and resolution not in dict(RESOLUTIONS):
            raise UserError('Unknown resolution.')
        if line.status == 'unexpected' and resolution not in (False, 'transfer_here'):
            raise UserError('An unexpected piece can only be transferred to this location.')
        if line.status == 'to_find' and resolution and resolution not in MISSING_RESOLUTIONS:
            raise UserError('Choose what happened to the missing piece.')
        if resolution == 'transfer_here' and not self._elsewhere_quants(line.product_id):
            raise UserError('Odoo has no stock of this piece in another location to transfer.')
        location = self.env['stock.location']
        if resolution == 'other_location':
            location = self.env['stock.location'].browse(int(location_id or 0)).exists()
            if not location or location.usage != 'internal':
                raise UserError('Choose the location where the piece is.')
            if location in self._scope_locations():
                raise UserError('That location is part of this count; scan the piece instead.')
        line.write({
            'resolution': resolution or False,
            'resolution_location_id': location.id or False,
            'resolved_by_id': self.env.user.id if resolution else False,
            'resolved_at': fields.Datetime.now() if resolution else False,
        })
        return self.get_scan_state()

    def other_locations(self):
        """Internal locations outside this count, for 'in another location'."""
        self.ensure_one()
        scope = self._scope_locations()
        locations = self.env['stock.location'].search(
            [('usage', '=', 'internal'), ('id', 'not in', scope.ids)], order='complete_name')
        return [{'id': loc.id, 'name': loc.complete_name} for loc in locations]

    # --- approval (admin badge) ------------------------------------------------

    def _badge_admin(self, badge):
        """The employee whose badge this is, when they are an admin: a manager
        on any POS register (Employees with advanced rights), or a user in the
        POS manager group — the same people who approve below-minimum sales."""
        badge = (badge or '').strip()
        if not badge:
            return self.env['hr.employee']
        employee = self.env['hr.employee'].sudo().search([('barcode', '=', badge)], limit=1)
        if not employee:
            return employee
        configs = self.env['pos.config'].sudo().search([])
        if 'advanced_employee_ids' in configs._fields and employee in configs.advanced_employee_ids:
            return employee
        group = self.env.ref('point_of_sale.group_pos_manager', raise_if_not_found=False)
        if group and employee.user_id and group in employee.user_id.all_group_ids:
            return employee
        return self.env['hr.employee']

    def action_approve(self, badge):
        """Close the count with an admin's badge and apply every resolution."""
        self.ensure_one()
        self._check_open()
        employee = self._badge_admin(badge)
        if not employee:
            raise UserError('That badge does not belong to an admin.')
        unresolved = self.line_ids.filtered(lambda line: line.status == 'to_find' and not line.resolution)
        if unresolved:
            raise UserError(
                f'{len(unresolved)} missing piece(s) still need a decision: '
                + ', '.join(unresolved[:10].mapped('default_code')))
        moves = self.env['account.move']
        for line in self.line_ids.filtered(
                lambda line: (line.status == 'to_find' and line.resolution != 'keep')
                or (line.status == 'unexpected' and line.resolution == 'transfer_here')):
            moves |= line._apply_resolution()
        self.write({
            'state': 'done',
            'end_date': fields.Datetime.now(),
            'approved_by_employee_id': employee.id,
            'approved_at': fields.Datetime.now(),
            'adjustment_move_ids': [(6, 0, moves.ids)],
        })
        return self.get_scan_state()

    # --- piece details for the side panel ------------------------------------

    def get_piece(self, product_id):
        self.ensure_one()
        product = self.env['product.product'].browse(int(product_id)).exists()
        if not product:
            raise UserError('Piece not found.')
        tmpl = product.product_tmpl_id
        line = self.line_ids.filtered(lambda line: line.product_id == product)[:1]
        quants = self.env['stock.quant'].sudo().search([
            ('product_id', '=', product.id), ('location_id.usage', '=', 'internal'), ('quantity', '!=', 0)])
        type_labels = dict(tmpl._fields['jewellery_type'].selection) if 'jewellery_type' in tmpl._fields else {}
        stones = tmpl.stone_ids if 'stone_ids' in tmpl._fields else []
        return {
            'product_id': product.id,
            'sku': product.default_code or '',
            'name': (tmpl.website_title if 'website_title' in tmpl._fields and tmpl.website_title
                     else product.display_name),
            'category': tmpl.categ_id.complete_name or '',
            'type': type_labels.get(tmpl.jewellery_type, '') if type_labels else '',
            'karat': (tmpl.gold_purity or '') if 'gold_purity' in tmpl._fields else '',
            'weights': {
                'jewellery': tmpl.gross_jewellery_weight_g,
                'net_gold': tmpl.net_gold_weight_g,
                'stones': tmpl.diamond_weight_g,
                'reading': tmpl.weight_reading_g,
            },
            'stones': [{
                'qty': st.quantity, 'shape': st.shape or '', 'carat': st.total_carat,
                'color': st.color or '', 'clarity': st.clarity or '',
            } for st in stones],
            'price': tmpl.list_price,
            'image': f'/web/image/product.product/{product.id}/image_512' if product.image_128 else '',
            'on_hand': [{'location': q.location_id.complete_name, 'qty': q.quantity} for q in quants],
            'elsewhere': [q.location_id.complete_name for q in self._elsewhere_quants(product)],
            'home': self._home_location().complete_name or '',
            'line': line and {
                'id': line.id, 'status': line.status, 'reason': line.reason or '',
                'resolution': line.resolution or '',
                'resolution_location': line.resolution_location_id.complete_name or '',
                'scanned_at': fields.Datetime.to_string(line.scanned_at)[11:19] if line.scanned_at else '',
            } or False,
        }

    def get_piece_by_line(self, line_id):
        self.ensure_one()
        line = self.line_ids.filtered(lambda line: line.id == line_id)
        if not line:
            raise UserError('Line not found.')
        return self.get_piece(line.product_id.id)

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
            'unresolved': len(to_find_lines.filtered(lambda line: not line.resolution)),
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
                'product_id': line.product_id.id,
                'sku': line.default_code or '',
                'resolution': line.resolution or '',
                'resolution_location': line.resolution_location_id.complete_name or '',
                'status': line.status,
                'reason': line.reason or '',
                'scanned_at': scanned[11:19] if scanned else '',
            })
        return out

    def _scan_result(self, result, sku, message):
        self.ensure_one()
        product = self.env['product.product'].search(
            ['|', ('barcode', '=', sku), ('default_code', '=', sku)], limit=1) if sku else False
        return {
            'result': result,
            'sku': sku,
            'piece': self.get_piece(product.id) if product else False,
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
            'approved_by': self.approved_by_employee_id.name or '',
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
    resolution = fields.Selection(RESOLUTIONS, string='Decision', copy=False)
    resolution_location_id = fields.Many2one(
        'stock.location', string='Found In', domain="[('usage', '=', 'internal')]", copy=False)
    resolved_by_id = fields.Many2one('res.users', string='Decided By', copy=False)
    resolved_at = fields.Datetime(copy=False)

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

    def _apply_resolution(self):
        """Apply this missing piece's decision (on approval). Returns the
        journal entry it posted, if any."""
        self.ensure_one()
        count = self.count_id
        product = self.product_id
        quants = self.env['stock.quant'].sudo().search([
            ('product_id', '=', product.id),
            ('location_id', 'in', count._scope_locations().ids),
            ('quantity', '>', 0)])
        label = f'{count.name}: {product.default_code or product.display_name}'
        if self.resolution == 'transfer_here':
            elsewhere = count._elsewhere_quants(product)
            if elsewhere and count._home_location():
                elsewhere.move_quants(location_dest_id=count._home_location(),
                                      message=f'{label} found here in the count')
            return self.env['account.move']
        if self.resolution == 'other_location':
            if quants:
                quants.move_quants(location_dest_id=self.resolution_location_id,
                                   message=f'{label} found in {self.resolution_location_id.complete_name}')
            return self.env['account.move']

        qty = sum(quants.mapped('quantity'))
        if not qty:
            return self.env['account.move']
        cost = qty * product.standard_price
        for quant in quants:
            qc = quant.with_context(inventory_mode=True, inventory_name=label)
            qc.inventory_quantity = 0
            qc.action_apply_inventory()
        company = count.env.company
        if company.currency_id.is_zero(cost):
            return self.env['account.move']
        accounts = product.product_tmpl_id.get_product_accounts()
        stock_account = accounts.get('stock_valuation')
        if self.resolution == 'lost':
            debit_account = self.env['account.account'].sudo().search([
                ('code', '=', INVENTORY_LOSS_ACCOUNT_CODE), ('company_ids', 'in', company.id)], limit=1)
            if not debit_account:
                raise UserError(f'Account {INVENTORY_LOSS_ACCOUNT_CODE} Inventory Loss is missing; '
                                'run scripts/accounting/configure_accounting.py.')
            what = 'Lost'
        else:
            debit_account = accounts.get('expense')
            what = 'Sold without invoice'
        if not stock_account or not debit_account:
            _logger.warning('[stock-count] %s: no accounts to book %s', label, cost)
            return self.env['account.move']
        move = self.env['account.move'].sudo().create({
            'journal_id': company.account_stock_journal_id.id,
            'ref': f'{label} ({what})',
            'line_ids': [
                (0, 0, {'account_id': debit_account.id, 'name': f'{label} ({what})',
                        'product_id': product.id, 'debit': company.currency_id.round(cost)}),
                (0, 0, {'account_id': stock_account.id, 'name': f'{label} ({what})',
                        'product_id': product.id, 'credit': company.currency_id.round(cost)}),
            ],
        })
        move._post()
        return move

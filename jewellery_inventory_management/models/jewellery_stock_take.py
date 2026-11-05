# -*- coding: utf-8 -*-
# Copyright 2026 Revenax Digital Services
# Author: Mohamed A. Abdallah
# Website: https://www.revenax.com

from markupsafe import escape

from odoo import api, fields, models
from odoo.exceptions import UserError

from .jewellery_stock_count import summary_table_html


class JewelleryStockTake(models.Model):
    """A full stock count of a warehouse (or one of its locations).

    Starting it creates one mini count (``jewellery.stock.count``) per SKU
    prefix that has pieces on hand in the scope. Staff scan inside each mini
    count, several at once on different prefixes; a piece scanned in the
    wrong mini is filed into its own prefix's mini. Each mini is approved
    with an admin badge on its own; the full count is done when every mini is.

    Optionally, "Scan together" opens one scan screen over several mini
    counts at once (any subset of the open ones): every scan is filed into
    its own prefix's mini, the lists and totals are combined, and one admin
    badge approves all the selected minis.
    """

    _name = 'jewellery.stock.take'
    _description = 'Full Stock Count'
    _order = 'create_date desc, id desc'

    name = fields.Char(default='New', required=True, copy=False, readonly=True)
    active = fields.Boolean(default=True, help='Archive an old full count to hide it and its mini counts.')
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
    expected_count = fields.Integer(compute='_compute_stats', string='Total')
    found_count = fields.Integer(compute='_compute_stats', string='Found')
    missing_count = fields.Integer(compute='_compute_stats', string='Missing')
    unexpected_count = fields.Integer(compute='_compute_stats', string='Extra')
    summary_html = fields.Html(compute='_compute_stats', sanitize=False)
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
            take.summary_html = summary_table_html(take._sum_stats(counts), take._meta_html())

    @api.onchange('warehouse_id')
    def _onchange_warehouse_id(self):
        self.location_id = False

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('jewellery.stock.take') or 'New'
        return super().create(vals_list)

    def write(self, vals):
        res = super().write(vals)
        if 'active' in vals:
            # Archiving a full count hides its mini counts with it (and back).
            self.with_context(active_test=False).count_ids.write({'active': vals['active']})
        return res

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

    # --- scanning several mini counts at once ---------------------------------

    def action_open_group_scanner(self):
        self.ensure_one()
        if self.state != 'in_progress':
            raise UserError('Start the full count first.')
        return {
            'type': 'ir.actions.client',
            'tag': 'jewellery_stock_count_scanner',
            'name': f'{self.name} · scan together',
            'params': {'take_id': self.id},
            'context': {'take_id': self.id},
        }

    def _open_minis(self):
        return self.count_ids.filtered(lambda c: c.state == 'in_progress')

    def _selected(self, count_ids):
        """The open minis being scanned together: the chosen ones, or all."""
        self.ensure_one()
        minis = self._open_minis()
        if count_ids:
            minis = minis.filtered(lambda c: c.id in set(count_ids))
        return minis

    def _mini_for(self, product):
        """The mini count of this full count that owns the piece's prefix."""
        prefix = self.env['jewellery.stock.count']._code_prefix(product.default_code)
        return self.count_ids.filtered(lambda c: c._prefix() == prefix)[:1]

    def _meta_html(self):
        """One line under the title: where, by whom, when, mini counts approved."""
        self.ensure_one()
        parts = [escape(self.location_id.complete_name or self.warehouse_id.name or '')]
        if self.user_id:
            parts.append(f'by {escape(self.user_id.name)}')
        if self.start_date:
            parts.append(f'started {fields.Datetime.context_timestamp(self, self.start_date):%d %b, %H:%M}')
        if self.count_ids:
            done = len(self.count_ids.filtered(lambda c: c.state == 'done'))
            parts.append(f'<b>{done} of {len(self.count_ids)}</b> mini counts approved')
        return ' · '.join(p for p in parts if p)

    @staticmethod
    def _sum_stats(counts):
        """The mini counts' _stats_dict added up."""
        keys = ('total', 'expected', 'found', 'missing', 'extra', 'unexpected', 'unresolved')
        stats = dict.fromkeys(keys, 0)
        weights = {side: {'net_gold': 0.0, 'stones': 0.0, 'jewellery': 0.0, 'readings': 0.0}
                   for side in ('found', 'missing', 'total')}
        for mini in counts:
            st = mini._stats_dict()
            for key in keys:
                stats[key] += st[key]
            for side, ws in weights.items():
                for w in ws:
                    ws[w] = round(ws[w] + st['weights'][side][w], 3)
        stats['progress'] = round(100.0 * stats['found'] / stats['total'], 1) if stats['total'] else 0.0
        stats['weights'] = weights
        return stats

    def _group_state(self, count_ids):
        self.ensure_one()
        selected = self._selected(count_ids)
        stats = self._sum_stats(selected)
        lines = []
        for mini in selected:
            for line in mini._lines_payload():
                line.update(count_id=mini.id, count_name=mini.name, prefix=mini.sku_prefix or '')
                lines.append(line)
        scope = self.location_id.display_name or self.warehouse_id.display_name or ''
        return {
            'id': self.id,
            'name': self.name,
            'scope': scope,
            'state': 'in_progress' if selected else 'done',
            'stats': stats,
            'lines': lines,
            'minis': [{
                'id': c.id, 'name': c.name, 'prefix': c.sku_prefix or '', 'state': c.state,
                'found': c.found_count, 'expected': c.expected_count,
                'selected': c in selected,
            } for c in self.count_ids.sorted(lambda c: c.sku_prefix or '')],
            'selected_ids': selected.ids,
        }

    def get_group_scan_state(self, count_ids=None):
        return self._group_state(count_ids)

    def group_process_scan(self, count_ids, barcode):
        """One scan on the together screen, filed into the piece's own mini."""
        self.ensure_one()
        code = (barcode or '').strip()
        res = {'result': 'empty', 'sku': '', 'piece': False, 'message': 'Empty scan'}
        if code:
            product = self.env['product.product'].search(
                ['|', ('barcode', '=', code), ('default_code', '=', code)], limit=1)
            if not product:
                res = {'result': 'unknown', 'sku': code, 'piece': False, 'message': 'Unknown barcode'}
            else:
                sku = product.default_code or product.display_name
                mini = self._mini_for(product)
                if mini and mini.state == 'in_progress':
                    one = mini.process_scan(code)
                    note = f' — {mini.sku_prefix} ({mini.name})'
                    if mini not in self._selected(count_ids):
                        note += ', which is not in this scan'
                    res = {'result': one['result'], 'sku': one['sku'], 'piece': one['piece'],
                           'message': one['message'] + note}
                else:
                    any_mini = mini or self._selected(count_ids)[:1] or self.count_ids[:1]
                    why = (f'{mini.name} ({mini.sku_prefix}) is already approved'
                           if mini else 'no mini count for this prefix in this full count')
                    res = {'result': 'unexpected', 'sku': sku,
                           'piece': any_mini.get_piece(product.id) if any_mini else False,
                           'message': f'Not recorded: {why}'}
        out = self._group_state(count_ids)
        out.update(result=res['result'], sku=res['sku'], piece=res['piece'], message=res['message'])
        return out

    def group_get_piece(self, count_ids, product_id):
        self.ensure_one()
        product = self.env['product.product'].browse(int(product_id)).exists()
        mini = (self._mini_for(product) if product else False) or self._selected(count_ids)[:1] or self.count_ids[:1]
        return mini.get_piece(product_id)

    def _line_mini(self, line_id):
        line = self.env['jewellery.stock.count.line'].browse(int(line_id)).exists()
        if not line or line.count_id.take_id != self:
            raise UserError('Line not found in this full count.')
        return line.count_id

    def group_set_resolution(self, count_ids, line_id, resolution, location_id=False):
        self.ensure_one()
        self._line_mini(line_id).set_resolution(line_id, resolution, location_id)
        return self._group_state(count_ids)

    def group_other_locations(self, count_ids=None):
        self.ensure_one()
        mini = self._selected(count_ids)[:1] or self.count_ids[:1]
        return mini.other_locations() if mini else []

    def group_approve(self, count_ids, badge):
        """Approve every selected open mini with one admin badge. All or
        nothing: if any mini still has undecided missing pieces, none closes."""
        self.ensure_one()
        selected = self._selected(count_ids)
        if not selected:
            raise UserError('No open mini count selected.')
        Count = self.env['jewellery.stock.count']
        employee = Count._badge_admin(badge)
        if not employee:
            raise UserError('That badge does not belong to an admin.')
        undecided = selected.line_ids.filtered(lambda line: line.status == 'to_find' and not line.resolution)
        if undecided:
            raise UserError(
                f'{len(undecided)} missing piece(s) still need a decision: '
                + ', '.join(undecided[:10].mapped('default_code')))
        for mini in selected:
            mini.action_approve(badge)
        out = self._group_state(count_ids)
        out['approved_by'] = employee.name
        out['approved'] = selected.mapped('name')
        return out

# -*- coding: utf-8 -*-
# Copyright 2026 Revenax Digital Services
# Author: Mohamed A. Abdallah
# Website: https://www.revenax.com
"""POS "Transfer" helper: move scanned pieces between the register and an owner,
another branch or On Memo, as a real, validated internal transfer.

The register calls three RPCs on ``pos.session`` (frontend: pos_transfer.js):

* ``jewellery_transfer_setup``: the register's own stock location and the
  parties it may send to / receive from (owner locations OW/*, the other
  branches' stock, On Memo OM/Stock).
* ``jewellery_transfer_piece``: one scanned code -> the piece's details (photo,
  weights, stones, price) and whether it is on hand where it must leave from.
* ``jewellery_transfer_create``: re-checks everything server-side (the party
  whitelist, the memo person, every piece on hand at the source), creates and
  validates the internal transfer, and stores a full snapshot of what was
  handed over (``jewellery.transfer.line``: weights, stones, price, scan time)
  plus who, when, from which register and session. Idempotent per key, so a
  retry after a lost response never moves stock twice.

Open stock counts lose their "missing" line for a piece that leaves their scope
(the piece is accounted for), and the ops app is told the piece's new branch.
"""

import logging
import threading
from html import escape

import requests
from odoo import _, api, fields, models
from odoo.exceptions import UserError

from ..utils import is_serial_sku, transfer_route, transfer_totals

_logger = logging.getLogger(__name__)

PARTY_KINDS = [('owner', 'Owner'), ('branch', 'Branch'), ('memo', 'On Memo')]


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    jewellery_pos_transfer = fields.Boolean('Made at the register', readonly=True, copy=False)
    jewellery_transfer_key = fields.Char(readonly=True, copy=False, index=True)
    jewellery_transfer_direction = fields.Selection(
        [('send', 'Sent from the register'), ('receive', 'Received at the register')],
        readonly=True, copy=False)
    jewellery_party_kind = fields.Selection(PARTY_KINDS, 'Other party', readonly=True, copy=False)
    jewellery_memo_person = fields.Char('On Memo with', readonly=True, copy=False)
    jewellery_pos_config_id = fields.Many2one('pos.config', 'Register', readonly=True, copy=False)
    jewellery_pos_session_id = fields.Many2one('pos.session', 'Register session', readonly=True, copy=False)
    jewellery_employee_id = fields.Many2one('hr.employee', 'Cashier', readonly=True, copy=False)
    jewellery_cashier_name = fields.Char('Cashier name', readonly=True, copy=False)
    jewellery_weights_checked = fields.Boolean('Weights checked by cashier', readonly=True, copy=False)
    jewellery_transfer_line_ids = fields.One2many(
        'jewellery.transfer.line', 'picking_id', 'Pieces handed over', readonly=True)
    jewellery_total_pieces = fields.Integer('Pieces', readonly=True, copy=False)
    jewellery_total_units = fields.Float('Units', digits=(16, 3), readonly=True, copy=False)
    jewellery_total_jewellery_g = fields.Float('Jewellery weight (g)', digits=(16, 3), readonly=True, copy=False)
    jewellery_total_net_gold_g = fields.Float('Net gold (g)', digits=(16, 3), readonly=True, copy=False)
    jewellery_total_stones_g = fields.Float('Stones (g)', digits=(16, 3), readonly=True, copy=False)
    jewellery_total_reading_g = fields.Float('Scale reading (g)', digits=(16, 3), readonly=True, copy=False)

    _jewellery_transfer_key_unique = models.Constraint(
        'UNIQUE(jewellery_transfer_key)',
        'This register transfer was already recorded.',
    )


class JewelleryTransferLine(models.Model):
    _name = 'jewellery.transfer.line'
    _description = 'Piece handed over in a register transfer (snapshot)'
    _order = 'picking_id, sequence, id'

    picking_id = fields.Many2one('stock.picking', required=True, ondelete='cascade', index=True)
    sequence = fields.Integer()
    product_id = fields.Many2one('product.product', required=True, ondelete='restrict', index=True)
    sku = fields.Char('SKU')
    name = fields.Char('Description')
    category = fields.Char()
    jewellery_type = fields.Char('Type')
    karat = fields.Char()
    qty = fields.Float('Quantity', digits=(16, 3))
    jewellery_weight_g = fields.Float('Jewellery (g)', digits=(16, 3))
    net_gold_weight_g = fields.Float('Net gold (g)', digits=(16, 3))
    stones_weight_g = fields.Float('Stones (g)', digits=(16, 3))
    weight_reading_g = fields.Float('Scale reading (g)', digits=(16, 3))
    stones = fields.Char('Stones')
    list_price = fields.Float('Price at transfer')
    scanned_at = fields.Datetime('Scanned at')


class PosSession(models.Model):
    _inherit = 'pos.session'

    # --- parties ----------------------------------------------------------------

    @api.model
    def _jewellery_transfer_here(self, config):
        location = config.picking_type_id.default_location_src_id
        if not location:
            raise UserError(_('This register has no stock location.'))
        return location

    @api.model
    def _jewellery_transfer_parties(self, here):
        """Locations this register may exchange pieces with, keyed by id."""
        Warehouse = self.env['stock.warehouse'].sudo()
        parties = {}
        owners = Warehouse.search([('code', '=', 'OW')], limit=1)
        if owners:
            for loc in self.env['stock.location'].sudo().search(
                    [('location_id', 'child_of', owners.view_location_id.id),
                     ('usage', '=', 'internal')], order='complete_name'):
                parties[loc.id] = {'id': loc.id, 'kind': 'owner', 'label': loc.name,
                                   'location': loc.complete_name, 'warehouse': 'OW'}
        for wh in Warehouse.search([('code', 'not in', ('OW', 'OM'))], order='code'):
            loc = wh.lot_stock_id
            if loc and loc != here:
                parties[loc.id] = {'id': loc.id, 'kind': 'branch', 'label': wh.name.split(' - ')[-1],
                                   'location': loc.complete_name, 'warehouse': wh.code}
        memo = Warehouse.search([('code', '=', 'OM')], limit=1)
        if memo and memo.lot_stock_id:
            loc = memo.lot_stock_id
            parties[loc.id] = {'id': loc.id, 'kind': 'memo', 'label': _('On Memo'),
                               'location': loc.complete_name, 'warehouse': 'OM'}
        return parties

    @api.model
    def _jewellery_transfer_config(self, session_id):
        session = self.sudo().browse(int(session_id))
        if not session.exists() or session.state != 'opened':
            raise UserError(_('Transfers need an open register session.'))
        return session, session.config_id

    @api.model
    def jewellery_transfer_setup(self, session_id):
        session, config = self._jewellery_transfer_config(session_id)
        here = self._jewellery_transfer_here(config)
        return {
            'here': {'id': here.id, 'location': here.complete_name,
                     'label': config.name, 'warehouse': here.warehouse_id.code or ''},
            'parties': list(self._jewellery_transfer_parties(here).values()),
        }

    # --- pieces -----------------------------------------------------------------

    @api.model
    def _jewellery_on_hand(self, product, location):
        quants = self.env['stock.quant'].sudo().search([
            ('product_id', '=', product.id), ('location_id', 'child_of', location.id)])
        return sum(quants.mapped('quantity'))

    @api.model
    def _jewellery_piece_info(self, product):
        tmpl = product.product_tmpl_id
        type_labels = dict(tmpl._fields['jewellery_type'].selection)
        quants = self.env['stock.quant'].sudo().search([
            ('product_id', '=', product.id), ('location_id.usage', '=', 'internal'),
            ('quantity', '!=', 0)])
        stones = [{
            'qty': st.quantity, 'shape': st.shape or '', 'carat': st.total_carat,
            'color': st.color or '', 'clarity': st.clarity or '',
        } for st in tmpl.stone_ids]
        return {
            'product_id': product.id,
            'sku': product.default_code or '',
            'name': (tmpl.website_title if 'website_title' in tmpl._fields and tmpl.website_title
                     else product.display_name),
            'category': tmpl.categ_id.complete_name or '',
            'type': type_labels.get(tmpl.jewellery_type, '') or '',
            'karat': tmpl.gold_purity or tmpl.silver_purity or '',
            'jewellery': round(tmpl.gross_jewellery_weight_g or 0.0, 3),
            'net_gold': round(tmpl.net_gold_weight_g or 0.0, 3),
            'stones_g': round(tmpl.diamond_weight_g or 0.0, 3),
            'reading': round(tmpl.weight_reading_g or 0.0, 3),
            'stones': stones,
            'price': tmpl.list_price,
            'unique': is_serial_sku(product.default_code),
            'image': f'/web/image/product.product/{product.id}/image_512' if product.image_128 else '',
            'on_hand': [{'location': q.location_id.complete_name, 'qty': q.quantity} for q in quants],
        }

    @api.model
    def jewellery_transfer_piece(self, session_id, direction, party_id, code):
        """One scan. ``status``: ok | unknown | elsewhere."""
        session, config = self._jewellery_transfer_config(session_id)
        here = self._jewellery_transfer_here(config)
        parties = self._jewellery_transfer_parties(here)
        if int(party_id) not in parties:
            raise UserError(_('Pick who the transfer is with first.'))
        src_id, _dst_id = transfer_route(direction, here.id, int(party_id))
        source = self.env['stock.location'].sudo().browse(src_id)
        code = (code or '').strip()
        product = self.env['product.product'].sudo().search(
            ['|', ('barcode', '=', code), ('default_code', '=', code)], limit=1) if code else False
        if not product:
            return {'status': 'unknown', 'code': code,
                    'message': _('%s is not a known piece.', code or '?')}
        info = self._jewellery_piece_info(product)
        available = self._jewellery_on_hand(product, source)
        info['available'] = available
        if available <= 0:
            where = ', '.join(f"{q['location']}" for q in info['on_hand'] if q['qty'] > 0)
            return {'status': 'elsewhere', 'code': code, 'piece': info,
                    'message': _('%(sku)s is not in %(src)s. Odoo has it at: %(where)s.',
                                 sku=info['sku'], src=source.complete_name,
                                 where=where or _('nowhere (sold or not stocked)'))}
        return {'status': 'ok', 'code': code, 'piece': info}

    # --- create -------------------------------------------------------------------

    @api.model
    def jewellery_transfer_create(self, session_id, payload, key):
        """Create and validate the internal transfer. Returns ``{name, id, duplicate}``."""
        session, config = self._jewellery_transfer_config(session_id)
        Picking = self.env['stock.picking'].sudo()
        if key:
            existing = Picking.search([('jewellery_transfer_key', '=', key)], limit=1)
            if existing:
                return {'id': existing.id, 'name': existing.name, 'duplicate': True}

        here = self._jewellery_transfer_here(config)
        parties = self._jewellery_transfer_parties(here)
        direction = payload.get('direction')
        party = parties.get(int(payload.get('party_id') or 0))
        if not party:
            raise UserError(_('That destination is not allowed from this register.'))
        memo_person = (payload.get('memo_person') or '').strip()
        if party['kind'] == 'memo' and not memo_person:
            raise UserError(_('On Memo needs the name of the person who takes the pieces.'))
        src_id, dst_id = transfer_route(direction, here.id, party['id'])
        Location = self.env['stock.location'].sudo()
        source, dest = Location.browse(src_id), Location.browse(dst_id)

        lines = payload.get('lines') or []
        if not lines:
            raise UserError(_('Scan at least one piece.'))
        products = self.env['product.product'].sudo().browse([int(line['product_id']) for line in lines])
        problems = []
        wanted: dict[int, float] = {}
        for line in lines:
            pid = int(line['product_id'])
            wanted[pid] = wanted.get(pid, 0.0) + float(line.get('qty') or 1.0)
        for product in products:
            have = self._jewellery_on_hand(product, source)
            if have < wanted[product.id]:
                problems.append(f'{product.default_code} ({have:g} of {wanted[product.id]:g})')
        if problems:
            raise UserError(_('Not on hand in %(src)s any more: %(list)s',
                              src=source.complete_name, list=', '.join(problems)))

        employee = self.env['hr.employee'].sudo().browse(int(payload.get('employee_id') or 0)).exists()
        cashier = payload.get('cashier_name') or employee.name or self.env.user.name
        who = party['label'] if party['kind'] != 'memo' else f"{party['label']}: {memo_person}"
        picking_type = here.warehouse_id.int_type_id or config.picking_type_id.warehouse_id.int_type_id
        if not picking_type:
            raise UserError(_('This branch has no internal transfer type.'))

        picking = Picking.create({
            'picking_type_id': picking_type.id,
            'location_id': source.id,
            'location_dest_id': dest.id,
            'origin': f'{config.name} · {"Send to" if direction == "send" else "Receive from"} {who} · by {cashier}',
            # Responsible = the cashier's (archived) Odoo user, so lists and
            # filters show who did it, not the shared register login.
            'user_id': employee.user_id.id or self.env.user.id,
            'jewellery_pos_transfer': True,
            'jewellery_transfer_key': key or False,
            'jewellery_transfer_direction': direction,
            'jewellery_party_kind': party['kind'],
            'jewellery_memo_person': memo_person or False,
            'jewellery_pos_config_id': config.id,
            'jewellery_pos_session_id': session.id,
            'jewellery_employee_id': employee.id or False,
            'jewellery_cashier_name': cashier,
            'jewellery_weights_checked': bool(payload.get('weights_checked')),
            'move_ids': [(0, 0, {
                'product_id': product.id,
                'product_uom_qty': wanted[product.id],
                'product_uom': product.uom_id.id,
                'location_id': source.id,
                'location_dest_id': dest.id,
            }) for product in products],
        })
        picking.action_confirm()
        picking.action_assign()
        for move in picking.move_ids:
            if move.quantity < move.product_uom_qty:
                raise UserError(_('%s could not be reserved in %s.', move.product_id.default_code,
                                  source.complete_name))
            move.picked = True
        result = picking.with_context(skip_backorder=True, skip_sms=True,
                                      skip_immediate=True).button_validate()
        if picking.state != 'done':
            raise UserError(_('The transfer could not be validated (%s).', result))

        # Snapshot exactly what was handed over.
        by_pid = {int(line['product_id']): line for line in lines}
        snap, totals_in = [], []
        for seq, product in enumerate(products):
            info = self._jewellery_piece_info(product)
            scanned = by_pid[product.id].get('scanned_at')
            qty = wanted[product.id]
            snap.append({
                'picking_id': picking.id, 'sequence': seq, 'product_id': product.id,
                'sku': info['sku'], 'name': info['name'], 'category': info['category'],
                'jewellery_type': info['type'], 'karat': info['karat'], 'qty': qty,
                'jewellery_weight_g': info['jewellery'], 'net_gold_weight_g': info['net_gold'],
                'stones_weight_g': info['stones_g'], 'weight_reading_g': info['reading'],
                'stones': '; '.join(f"{s['qty']:g}x {s['shape']} {s['carat']:.3f}ct {s['color']}/{s['clarity']}"
                                    for s in info['stones']),
                'list_price': info['price'],
                'scanned_at': fields.Datetime.to_datetime(scanned[:19].replace('T', ' ')) if scanned else False,
            })
            totals_in.append({'qty': qty, 'jewellery': info['jewellery'], 'net_gold': info['net_gold'],
                              'stones': info['stones_g'], 'reading': info['reading']})
        self.env['jewellery.transfer.line'].sudo().create(snap)
        totals = transfer_totals(totals_in)
        picking.write({
            'jewellery_total_pieces': totals['pieces'],
            'jewellery_total_units': totals['units'],
            'jewellery_total_jewellery_g': totals['jewellery'],
            'jewellery_total_net_gold_g': totals['net_gold'],
            'jewellery_total_stones_g': totals['stones'],
            'jewellery_total_reading_g': totals['reading'],
        })
        picking.message_post(body=self._jewellery_transfer_note(picking, snap, totals, who, cashier))

        self._jewellery_transfer_drop_count_lines(products, source)
        self._jewellery_transfer_push_ops(products, dest)
        return {'id': picking.id, 'name': picking.name, 'duplicate': False, 'totals': totals}

    @api.model
    def _jewellery_transfer_note(self, picking, snap, totals, who, cashier):
        rows = ''.join(
            f"<tr><td>{escape(s['sku'] or '')}</td><td>{escape(s['karat'] or '')}</td>"
            f"<td>{s['qty']:g}</td><td>{s['jewellery_weight_g']:.3f}</td>"
            f"<td>{s['net_gold_weight_g']:.3f}</td><td>{s['stones_weight_g']:.3f}</td>"
            f"<td>{s['weight_reading_g']:.3f}</td></tr>" for s in snap)
        return (
            f"<p><b>Register transfer</b> by {escape(cashier)} with {escape(who)}: "
            f"{escape(picking.location_id.complete_name)} → {escape(picking.location_dest_id.complete_name)}. "
            f"Weights checked: {'yes' if picking.jewellery_weights_checked else 'no'}.</p>"
            "<table class='table table-sm'><tr><th>SKU</th><th>Karat</th><th>Qty</th><th>Jewellery g</th>"
            "<th>Net gold g</th><th>Stones g</th><th>Reading g</th></tr>"
            f"{rows}<tr><th>{totals['pieces']} pieces</th><th></th><th>{totals['units']:g}</th>"
            f"<th>{totals['jewellery']:.3f}</th><th>{totals['net_gold']:.3f}</th>"
            f"<th>{totals['stones']:.3f}</th><th>{totals['reading']:.3f}</th></tr></table>"
        )

    @api.model
    def _jewellery_transfer_drop_count_lines(self, products, source):
        """A piece that left an open count's place is accounted for: drop its
        "missing" line so nobody marks it Lost."""
        if 'jewellery.stock.count.line' not in self.env:
            return
        try:
            with self.env.cr.savepoint():
                lines = self.env['jewellery.stock.count.line'].sudo().search([
                    ('product_id', 'in', products.ids), ('status', '=', 'to_find'),
                    ('count_id.state', '!=', 'done')])
                for line in lines:
                    count = line.count_id
                    scope = count.location_id or count.warehouse_id.view_location_id
                    if scope and (source.parent_path or '').startswith(scope.parent_path or '~'):
                        line.unlink()
        except Exception:
            _logger.warning('register transfer: could not tidy open counts', exc_info=True)

    @api.model
    def _jewellery_transfer_push_ops(self, products, dest):
        """Tell the ops app each piece's new branch (after commit, never blocks)."""
        try:
            params = self.env['ir.config_parameter'].sudo()
            url = (params.get_param('jewellery_evaluator.ops_sold_sync_url') or '').strip()
            token = (params.get_param('jewellery_evaluator.ops_sold_sync_token') or '').strip()
            code = dest.warehouse_id.code
            if not url or not token or not code or not url.endswith('/sold'):
                return
            url = url[:-len('/sold')] + '/warehouse'
            events = [{'sku': p.default_code, 'warehouse': code} for p in products if p.default_code]

            def send():
                def run():
                    try:
                        requests.post(url, json={'events': events}, timeout=15,
                                      headers={'Authorization': f'Bearer {token}'}).raise_for_status()
                    except Exception as exc:
                        _logger.warning('[ops-warehouse] push failed: %s', exc)
                threading.Thread(target=run, daemon=True, name='ops-warehouse-sync').start()

            self.env.cr.postcommit.add(send)
        except Exception:
            _logger.warning('[ops-warehouse] could not queue push', exc_info=True)

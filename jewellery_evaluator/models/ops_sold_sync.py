# -*- coding: utf-8 -*-
# Copyright 2026 Revenax Digital Services
# Author: Mohamed A. Abdallah
# Website: https://www.revenax.com
"""Tell the operations app which pieces are sold.

The ops app (Neon) is the audit copy of every registered piece. Odoo is where
pieces are sold, so Odoo pushes each piece's sold state to
``POST <ops>/api/odoo/sold``: right after a POS order or a customer invoice /
refund is posted, and once a night for every piece (the backstop for
cancelled invoices, missed pushes and the first backfill).

The state is recomputed from Odoo's own sale and return lines each time
(``utils.fold_sold_state``), never toggled, so a repeated push is harmless.

Off until both ``jewellery_evaluator.ops_sold_sync_url`` and
``jewellery_evaluator.ops_sold_sync_token`` are set. Never breaks a sale: the
live push runs after commit on a background thread and only logs failures.
"""

import logging
import threading

import requests
from odoo import api, fields, models
from odoo.exceptions import UserError

from ..utils import fold_sold_state

_logger = logging.getLogger(__name__)

PARAM_URL = 'jewellery_evaluator.ops_sold_sync_url'
PARAM_TOKEN = 'jewellery_evaluator.ops_sold_sync_token'
TIMEOUT_SECONDS = 15
BATCH_SIZE = 500
SOLD_POS_STATES = ('paid', 'done', 'invoiced')


class JewelleryOpsSoldSync(models.AbstractModel):
    _name = 'jewellery.ops.sold.sync'
    _description = 'Sold-state sync to the operations app'

    @api.model
    def _endpoint(self):
        params = self.env['ir.config_parameter'].sudo()
        url = (params.get_param(PARAM_URL) or '').strip()
        token = (params.get_param(PARAM_TOKEN) or '').strip()
        return (url, token) if url and token else (None, None)

    @api.model
    def _sold_states(self, products):
        """``[{sku, sold, sold_at, sold_ref}]`` for the products that have a SKU."""
        products = products.sudo().with_context(active_test=False).filtered('default_code')
        if not products:
            return []
        movements: dict[int, list] = {p.id: [] for p in products}

        pos_lines = self.env['pos.order.line'].sudo().search_read(
            [('product_id', 'in', products.ids),
             ('order_id.state', 'in', SOLD_POS_STATES)],
            ['product_id', 'qty', 'order_id'])
        orders = {
            o['id']: o for o in self.env['pos.order'].sudo().search_read(
                [('id', 'in', list({line['order_id'][0] for line in pos_lines}))],
                ['date_order', 'pos_reference', 'name'])
        }
        for line in pos_lines:
            order = orders[line['order_id'][0]]
            movements[line['product_id'][0]].append((
                line['qty'], fields.Datetime.to_string(order['date_order']) + '+00:00',
                order['pos_reference'] or order['name']))

        # Manual and website invoices. A POS invoice repeats its order's lines,
        # which are counted above.
        inv_lines = self.env['account.move.line'].sudo().search_read(
            [('product_id', 'in', products.ids),
             ('display_type', '=', 'product'),
             ('parent_state', '=', 'posted'),
             ('move_id.move_type', 'in', ('out_invoice', 'out_refund')),
             ('move_id.pos_order_ids', '=', False)],
            ['product_id', 'quantity', 'move_id'])
        moves = {
            m['id']: m for m in self.env['account.move'].sudo().search_read(
                [('id', 'in', list({line['move_id'][0] for line in inv_lines}))],
                ['move_type', 'invoice_date', 'date', 'name'])
        }
        for line in inv_lines:
            move = moves[line['move_id'][0]]
            sign = -1 if move['move_type'] == 'out_refund' else 1
            day = move['invoice_date'] or move['date']
            movements[line['product_id'][0]].append((
                sign * line['quantity'], f'{fields.Date.to_string(day)} 00:00:00+00:00', move['name']))

        states = []
        for product in products:
            state = fold_sold_state(movements[product.id])
            states.append({'sku': product.default_code, **state})
        return states

    @api.model
    def _send(self, url, token, states):
        response = requests.post(
            url, json={'events': states}, timeout=TIMEOUT_SECONDS,
            headers={'Authorization': f'Bearer {token}'})
        response.raise_for_status()
        return response.json()

    @api.model
    def push_after_commit(self, products):
        """Push these products' sold state once the current transaction commits."""
        try:
            url, token = self._endpoint()
            if not url:
                return
            states = self._sold_states(products)
            if not states:
                return

            def send():
                def run():
                    try:
                        self._send(url, token, states)
                    except Exception as exc:
                        _logger.warning('[ops-sold] push of %s failed: %s',
                                        ', '.join(s['sku'] for s in states), exc)
                threading.Thread(target=run, daemon=True, name='ops-sold-sync').start()

            self.env.cr.postcommit.add(send)
        except Exception as exc:
            _logger.warning('[ops-sold] could not queue push: %s', exc)

    @api.model
    def cron_reconcile(self):
        """Push the sold state of every piece with a SKU (nightly backstop)."""
        url, token = self._endpoint()
        if not url:
            _logger.info('[ops-sold] sync is off (%s / %s not set)', PARAM_URL, PARAM_TOKEN)
            return
        products = self.env['product.product'].sudo().with_context(active_test=False).search(
            [('default_code', '!=', False)])
        sent = 0
        for start in range(0, len(products), BATCH_SIZE):
            states = self._sold_states(products[start:start + BATCH_SIZE])
            if states:
                self._send(url, token, states)
                sent += len(states)
        _logger.info('[ops-sold] reconciled %s pieces', sent)


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    def retire_jewellery_piece(self):
        """Take a never-sold piece off the books: on-hand to 0, then archive.

        Called by the operations app when an admin approves a delete request.
        Refuses a piece that has a sale, so a delete can never hide a sold piece.
        """
        self.ensure_one()
        products = self.with_context(active_test=False).product_variant_ids
        for state in self.env['jewellery.ops.sold.sync']._sold_states(products):
            if state['sold']:
                raise UserError(f"{state['sku']} was sold ({state['sold_ref']}); it cannot be deleted.")
        quants = self.env['stock.quant'].sudo().search(
            [('product_id', 'in', products.ids),
             ('location_id.usage', '=', 'internal'),
             ('quantity', '!=', 0)])
        for quant in quants:
            qc = quant.with_context(inventory_mode=True)
            qc.inventory_quantity = 0
            qc.action_apply_inventory()
        self.write({'active': False})
        return {'archived': True, 'quants_zeroed': len(quants)}

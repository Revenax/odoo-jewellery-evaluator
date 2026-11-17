# -*- coding: utf-8 -*-
# Copyright 2026 Revenax Digital Services
# Author: Mohamed A. Abdallah
# Website: https://www.revenax.com
"""POS "Print A5" / "Print A5 Gift": send an order's invoice to the branch's A5
printer through the operations app's print queue.

The register calls ``pos.session.jewellery_print_a5(session_id, order_id, kind)``.
Odoo renders the PDF (``a5`` = the gold A5 invoice, ``gift`` = the same layout
without prices) and POSTs it to ``<ops>/api/odoo/invoice-print`` with the
branch code. The ops app queues it per branch; the print client on the shop PC
(marjaan-operations-client ``print_invoices.js``) polls
``/api/invoice-print-queue``, prints at A5 and acknowledges. Same URL root and
token as the sold sync (``jewellery_evaluator.ops_sold_sync_url`` / ``_token``).
"""

import base64
import logging

import requests
from odoo import _, api, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

REPORTS = {
    'a5': 'account.report_invoice_with_payments',   # restyled by the gold A5 layout
    'gift': 'jewellery_evaluator.report_gift_invoice',
}
TIMEOUT_SECONDS = 25


class PosSession(models.Model):
    _inherit = 'pos.session'

    @api.model
    def jewellery_print_a5(self, session_id, order_id, kind, cashier_name=''):
        """Queue the order's A5 invoice (or gift copy) at this branch's printer."""
        if kind not in REPORTS:
            raise UserError(_('Unknown print type.'))
        session = self.sudo().browse(int(session_id))
        if not session.exists():
            raise UserError(_('Register session not found.'))
        order = self.env['pos.order'].sudo().browse(int(order_id or 0)).exists()
        if not order or order.config_id != session.config_id:
            raise UserError(_('This order is not saved yet. Try again in a moment.'))
        move = order.account_move
        if not move or move.state != 'posted':
            raise UserError(_('The invoice for this order is not ready yet. Try again in a moment.'))

        params = self.env['ir.config_parameter'].sudo()
        sold_url = (params.get_param('jewellery_evaluator.ops_sold_sync_url') or '').strip()
        token = (params.get_param('jewellery_evaluator.ops_sold_sync_token') or '').strip()
        if not sold_url.endswith('/sold') or not token:
            raise UserError(_('The A5 printer is not connected (operations app link not set).'))
        url = sold_url[:-len('/sold')] + '/invoice-print'

        warehouse = session.config_id.picking_type_id.warehouse_id.code or ''
        pdf, _fmt = self.env['ir.actions.report'].sudo()._render_qweb_pdf(REPORTS[kind], move.ids)
        payload = {
            'warehouse': warehouse,
            'kind': kind,
            'invoice': move.name,
            'order': order.pos_reference or order.name,
            'register': session.config_id.name,
            'requested_by': cashier_name or self.env.user.name,
            'copies': 1,
            'pdf_base64': base64.b64encode(pdf).decode(),
        }
        try:
            response = requests.post(url, json=payload, timeout=TIMEOUT_SECONDS,
                                     headers={'Authorization': f'Bearer {token}'})
            response.raise_for_status()
            job = response.json()
        except Exception as exc:
            _logger.warning('[a5-print] %s %s for %s failed: %s', kind, move.name, warehouse, exc)
            raise UserError(_('Could not reach the printer queue. Try again.')) from exc
        _logger.info('[a5-print] queued %s %s at %s (job %s)', kind, move.name, warehouse, job.get('id'))
        return {'id': job.get('id'), 'invoice': move.name, 'warehouse': warehouse}

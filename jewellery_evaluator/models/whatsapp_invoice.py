# -*- coding: utf-8 -*-
# Copyright 2026 Revenax Digital Services
# Author: Mohamed A. Abdallah
# Website: https://www.revenax.com
"""Send each POS invoice to the customer on WhatsApp.

A cron (every 2 minutes) picks posted POS invoices, renders the invoice PDF (Marjaan's gold
layout) and hands it to the local WhatsApp gateway (``marjaan-whatsapp``, see
docs/whatsapp.md), which sends the approved ``order_confirmation`` template:
"Dear {{1}}, thank you for shopping at Marjaan Jewellery ... Your order {{2}} is confirmed.
Total: {{3}} EGP. Your invoice is attached ..." with the PDF as the document header.

Never in the sale path: the till only creates the invoice; sending happens later in the
cron, so a WhatsApp or gateway problem can never slow down or fail a sale.

Switches (``ir.config_parameter``):

- ``jewellery_evaluator.whatsapp_enabled``: ``True`` to send. Anything else is a no-op.
- ``jewellery_evaluator.whatsapp_since``: UTC datetime ``YYYY-MM-DD HH:MM:SS``. Only invoices
  created at or after it are sent, so turning the feature on never messages past customers.
  Required: with no value nothing is sent.
- ``jewellery_evaluator.whatsapp_gateway_url``: default ``http://127.0.0.1:8076/send``.
- ``jewellery_evaluator.whatsapp_template``: default ``order_confirmation``.

Each invoice is sent at most once (``jewellery_wa_state``). A failure is retried on the next
runs, up to 3 attempts. A customer with no valid Egyptian mobile is marked ``skipped``.
"""

import base64
import json
import logging
import urllib.error
import urllib.request

from odoo import api, fields, models

from .. import utils

_logger = logging.getLogger(__name__)

PARAM = 'jewellery_evaluator.whatsapp_'
MAX_ATTEMPTS = 3
BATCH = 20
INVOICE_REPORT = 'account.report_invoice_with_payments'  # restyled by our gold invoice layout


class AccountMove(models.Model):
    _inherit = 'account.move'

    jewellery_wa_state = fields.Selection(
        [('sent', 'Sent'), ('failed', 'Failed'), ('skipped', 'Skipped')],
        string='WhatsApp invoice', copy=False, index=True, readonly=True,
        help='Whether this POS invoice was sent to the customer on WhatsApp.')
    jewellery_wa_attempts = fields.Integer(string='WhatsApp attempts', copy=False, readonly=True)
    jewellery_wa_info = fields.Char(string='WhatsApp detail', copy=False, readonly=True,
                                    help='Recipient and message id when sent; the reason when skipped or failed.')

    @api.model
    def _jewellery_wa_settings(self):
        icp = self.env['ir.config_parameter'].sudo()
        return {
            'enabled': icp.get_param(PARAM + 'enabled') == 'True',
            'since': icp.get_param(PARAM + 'since') or '',
            'url': icp.get_param(PARAM + 'gateway_url') or 'http://127.0.0.1:8076/send',
            'template': icp.get_param(PARAM + 'template') or 'order_confirmation',
        }

    @api.model
    def cron_send_whatsapp_invoices(self):
        cfg = self._jewellery_wa_settings()
        if not cfg['enabled'] or not cfg['since']:
            return
        invoices = self.sudo().search([
            ('move_type', '=', 'out_invoice'),
            ('state', '=', 'posted'),
            ('pos_order_ids', '!=', False),
            ('create_date', '>=', cfg['since']),
            '|', ('jewellery_wa_state', '=', False),
            '&', ('jewellery_wa_state', '=', 'failed'), ('jewellery_wa_attempts', '<', MAX_ATTEMPTS),
        ], order='id', limit=BATCH)
        for inv in invoices:
            try:
                inv._jewellery_wa_send(cfg)
            except Exception:  # never let one invoice stop the batch
                _logger.exception('WhatsApp invoice %s: unexpected error', inv.name)
                inv.write({'jewellery_wa_state': 'failed', 'jewellery_wa_attempts': inv.jewellery_wa_attempts + 1,
                           'jewellery_wa_info': 'unexpected error (see server log)'})
            # Commit per invoice: a crash later in the batch must not lose the "sent" mark
            # and send the same invoice twice on the next run.
            self.env.cr.commit()

    def _jewellery_wa_send(self, cfg):
        self.ensure_one()
        partner = self.partner_id
        to = utils.whatsapp_mobile(partner.phone)
        if not to:
            self.write({'jewellery_wa_state': 'skipped',
                        'jewellery_wa_info': f'no valid Egyptian mobile on the customer ({partner.phone or "empty"})'})
            return
        pdf, _ = self.env['ir.actions.report'].sudo()._render_qweb_pdf(INVOICE_REPORT, self.ids)
        payload = {
            'to': to,
            'template': cfg['template'],
            'language': 'en',
            'params': [partner.name or 'Customer', self.name, utils.format_egp_amount(self.amount_total)],
            'document': {'base64': base64.b64encode(pdf).decode(),
                         'filename': f'Marjaan Invoice {self.name}.pdf'},
            'source': 'odoo-pos-invoice',
        }
        req = urllib.request.Request(cfg['url'], data=json.dumps(payload).encode(), method='POST',
                                     headers={'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(req, timeout=45) as resp:
                result = json.loads(resp.read() or b'{}')
        except urllib.error.HTTPError as err:
            detail = (err.read() or b'')[:300].decode(errors='replace')
            self._jewellery_wa_failed(f'gateway HTTP {err.code}: {detail}')
            return
        except (urllib.error.URLError, TimeoutError, OSError) as err:
            self._jewellery_wa_failed(f'gateway unreachable: {type(err).__name__}')
            return
        self.write({'jewellery_wa_state': 'sent', 'jewellery_wa_attempts': self.jewellery_wa_attempts + 1,
                    'jewellery_wa_info': f'+{to} · {result.get("wamid") or ""}'[:250]})
        self.message_post(body=f'Invoice sent to the customer on WhatsApp (+{to}).')

    def _jewellery_wa_failed(self, reason):
        attempts = self.jewellery_wa_attempts + 1
        self.write({'jewellery_wa_state': 'failed', 'jewellery_wa_attempts': attempts,
                    'jewellery_wa_info': reason[:250]})
        _logger.warning('WhatsApp invoice %s failed (attempt %s): %s', self.name, attempts, reason)
        if attempts >= MAX_ATTEMPTS:
            self.message_post(body=f'WhatsApp invoice could not be sent after {attempts} attempts: {reason[:200]}')

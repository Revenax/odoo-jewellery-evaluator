# -*- coding: utf-8 -*-
# Copyright 2026 Revenax Digital Services
# Author: Mohamed A. Abdallah
# Website: https://www.revenax.com
import json
import pprint

from odoo import http
from odoo.addons.payment.logging import get_payment_logger
from odoo.http import request
from werkzeug.exceptions import Forbidden

from ..kashier_utils import redirect_signature, signature_ok, webhook_signature
from ..models.payment_transaction import RETURN_URL, WEBHOOK_URL

_logger = get_payment_logger(__name__)


class KashierController(http.Controller):

    @http.route(RETURN_URL, type='http', auth='public', methods=['GET'])
    def kashier_return(self, **params):
        """The customer's browser coming back from Kashier's checkout."""
        _logger.info('Kashier redirect:\n%s', pprint.pformat(params))
        data = {
            'reference': params.get('merchantOrderId'), 'status': params.get('paymentStatus'),
            'amount': params.get('amount'), 'currency': params.get('currency'),
            'transaction_id': params.get('transactionId'),
        }
        tx_sudo = request.env['payment.transaction'].sudo()._search_by_reference('kashier', data)
        if tx_sudo:
            expected = redirect_signature(params, tx_sudo.provider_id._kashier_api_key())
            if not signature_ok(params.get('signature'), expected):
                _logger.warning('Kashier redirect with an invalid signature for %s', tx_sudo.reference)
                raise Forbidden()
            tx_sudo._process('kashier', data)
        return request.redirect('/payment/status')

    @http.route(WEBHOOK_URL, type='http', auth='public', methods=['POST'], csrf=False)
    def kashier_webhook(self):
        """Server-to-server notification; the source of truth when the
        customer closes the tab before the redirect."""
        body = json.loads(request.httprequest.get_data() or b'{}')
        event, payload = body.get('event'), body.get('data') or {}
        _logger.info('Kashier webhook %s:\n%s', event, pprint.pformat(payload))
        if event not in ('pay', 'authorize'):
            return request.make_response('', status=200)
        data = {
            'reference': payload.get('merchantOrderId'), 'status': payload.get('status'),
            'amount': payload.get('amount'), 'currency': payload.get('currency'),
            'transaction_id': payload.get('transactionId'),
        }
        tx_sudo = request.env['payment.transaction'].sudo()._search_by_reference('kashier', data)
        if tx_sudo:
            expected = webhook_signature(payload, tx_sudo.provider_id._kashier_api_key())
            if not signature_ok(request.httprequest.headers.get('x-kashier-signature'), expected):
                _logger.warning('Kashier webhook with an invalid signature for %s', tx_sudo.reference)
                raise Forbidden()
            if tx_sudo.state == 'done':
                return request.make_response('', status=409)  # already processed
            tx_sudo._process('kashier', data)
        return request.make_response('', status=200)

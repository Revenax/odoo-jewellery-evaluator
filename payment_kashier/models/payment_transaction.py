# -*- coding: utf-8 -*-
# Copyright 2026 Revenax Digital Services
# Author: Mohamed A. Abdallah
# Website: https://www.revenax.com
from datetime import timedelta
from urllib.parse import parse_qsl, urlsplit

from odoo import _, api, fields, models
from odoo.addons.payment import utils as payment_utils
from odoo.addons.payment.logging import get_payment_logger
from odoo.exceptions import ValidationError
from odoo.tools import urls

from ..kashier_utils import STATUS_DONE, STATUS_PENDING

_logger = get_payment_logger(__name__)

RETURN_URL = '/payment/kashier/return'
WEBHOOK_URL = '/payment/kashier/webhook'


class PaymentTransaction(models.Model):
    _inherit = 'payment.transaction'

    @api.model
    def _compute_reference(self, provider_code, prefix=None, separator='-', **kwargs):
        # Kashier refuses an order reference it has seen before (ERR_ORD_02).
        if provider_code == 'kashier':
            if not prefix:
                prefix = self.sudo()._compute_reference_prefix(separator, **kwargs) or None
            prefix = payment_utils.singularize_reference_prefix(prefix=prefix, separator=separator)
        return super()._compute_reference(provider_code, prefix=prefix, separator=separator, **kwargs)

    def _get_specific_rendering_values(self, processing_values):
        if self.provider_code != 'kashier':
            return super()._get_specific_rendering_values(processing_values)
        provider = self.provider_id
        base_url = self.get_base_url()
        payload = {
            'expireAt': (fields.Datetime.now() + timedelta(hours=1)).strftime('%Y-%m-%dT%H:%M:%S.000Z'),
            'maxFailureAttempts': 3,
            'paymentType': 'credit',
            'amount': f'{self.amount:.2f}',
            'currency': self.currency_id.name,
            'order': self.reference,
            'merchantId': provider.kashier_merchant_id,
            'merchantRedirect': urls.urljoin(base_url, RETURN_URL),
            'serverWebhook': urls.urljoin(base_url, WEBHOOK_URL),
            'redirectMethod': 'get',
            'display': 'ar' if (self.partner_lang or '').startswith('ar') else 'en',
            'type': 'one-time',
            'allowedMethods': 'card,wallet',
            'brandColor': '#1A1A24',
            'description': f'{self.company_id.name} {self.reference}',
            'customer': {'email': self.partner_email or '', 'reference': str(self.partner_id.id)},
        }
        try:
            session = provider._send_api_request('POST', '/v3/payment/sessions', json=payload, reference=self.reference)
        except ValidationError as error:
            self._set_error(str(error))
            return {}
        self.provider_reference = session.get('_id')
        session_url = urlsplit(session['sessionUrl'])
        # A GET form drops the action's own query string, so ?mode=test
        # travels as a hidden field instead.
        return {
            'api_url': session_url._replace(query='').geturl(),
            'url_params': dict(parse_qsl(session_url.query)),
        }

    @api.model
    def _extract_reference(self, provider_code, payment_data):
        if provider_code != 'kashier':
            return super()._extract_reference(provider_code, payment_data)
        return payment_data.get('reference')

    def _extract_amount_data(self, payment_data):
        if self.provider_code != 'kashier':
            return super()._extract_amount_data(payment_data)
        return {'amount': float(payment_data.get('amount') or 0), 'currency_code': payment_data.get('currency')}

    def _apply_updates(self, payment_data):
        if self.provider_code != 'kashier':
            return super()._apply_updates(payment_data)
        if payment_data.get('transaction_id'):
            self.provider_reference = payment_data['transaction_id']
        status = payment_data.get('status')
        if status == STATUS_DONE:
            self._set_done()
        elif status == STATUS_PENDING:
            self._set_pending()
        else:
            _logger.info('Kashier: unsuccessful payment for %s: %s', self.reference, status)
            self._set_error(_('Your payment was not completed (%(status)s). Please try again.', status=status or '?'))

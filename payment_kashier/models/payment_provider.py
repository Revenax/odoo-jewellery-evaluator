# -*- coding: utf-8 -*-
# Copyright 2026 Revenax Digital Services
# Author: Mohamed A. Abdallah
# Website: https://www.revenax.com
from odoo import fields, models

from ..kashier_utils import API_URL


class PaymentProvider(models.Model):
    _inherit = 'payment.provider'

    code = fields.Selection(selection_add=[('kashier', 'Kashier')], ondelete={'kashier': 'set default'})
    kashier_merchant_id = fields.Char(string='Merchant ID', required_if_provider='kashier', copy=False)
    kashier_test_api_key = fields.Char(string='Test Payment API Key', copy=False, groups='base.group_system')
    kashier_test_secret_key = fields.Char(string='Test Secret Key', copy=False, groups='base.group_system')
    kashier_live_api_key = fields.Char(string='Live Payment API Key', copy=False, groups='base.group_system')
    kashier_live_secret_key = fields.Char(string='Live Secret Key', copy=False, groups='base.group_system')

    def _kashier_mode(self):
        self.ensure_one()
        return 'live' if self.state == 'enabled' else 'test'

    def _kashier_api_key(self):
        self.ensure_one()
        return self.sudo()[f'kashier_{self._kashier_mode()}_api_key'] or ''

    def _kashier_secret_key(self):
        self.ensure_one()
        return self.sudo()[f'kashier_{self._kashier_mode()}_secret_key'] or ''

    def _get_default_payment_method_codes(self):
        self.ensure_one()
        if self.code != 'kashier':
            return super()._get_default_payment_method_codes()
        return {'card'}

    # === REQUEST HELPERS === #

    def _build_request_url(self, endpoint, **kwargs):
        if self.code != 'kashier':
            return super()._build_request_url(endpoint, **kwargs)
        return f'{API_URL[self._kashier_mode()]}{endpoint}'

    def _build_request_headers(self, method, endpoint, payload, **kwargs):
        if self.code != 'kashier':
            return super()._build_request_headers(method, endpoint, payload, **kwargs)
        return {
            'Authorization': self._kashier_secret_key(),
            'api-key': self._kashier_api_key(),
            'Content-Type': 'application/json',
        }

    def _parse_response_error(self, response):
        if self.code != 'kashier':
            return super()._parse_response_error(response)
        try:
            body = response.json()
        except ValueError:
            return response.text
        message = body.get('message') or body.get('error') or body
        return message.get('en') if isinstance(message, dict) and 'en' in message else str(message)

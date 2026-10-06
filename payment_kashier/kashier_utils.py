# -*- coding: utf-8 -*-
# Copyright 2026 Revenax Digital Services
# Author: Mohamed A. Abdallah
# Website: https://www.revenax.com
"""Kashier signing rules, without Odoo (tested in tests/test_kashier.py).

Both checks are keyed with the *Payment API Key* (not the Secret Key):
https://developers.kashier.io/docs/webhooks#step-4-verify-the-signature
https://developers.kashier.io/docs (Direct API > Signature: redirect)
"""
import hashlib
import hmac
from urllib.parse import quote

API_URL = {'test': 'https://test-api.kashier.io', 'live': 'https://api.kashier.io'}

# Kashier signs this fixed, ordered list on the redirect; a parameter absent
# from the URL is signed as the literal string "null".
REDIRECT_FIELDS = (
    'paymentStatus', 'cardDataToken', 'maskedCard', 'merchantOrderId', 'orderId',
    'cardBrand', 'orderReference', 'transactionId', 'amount', 'currency',
)

STATUS_DONE, STATUS_PENDING = 'SUCCESS', 'PENDING'


def _hmac(key, payload):
    return hmac.new(key.encode('utf-8'), payload.encode('utf-8'), hashlib.sha256).hexdigest()


def redirect_signature(params, api_key):
    """Expected signature of the customer's redirect back to the shop."""
    body = '&'.join(f'{field}={params.get(field, "null")}' for field in REDIRECT_FIELDS)
    return _hmac(api_key, body)


def _js_value(value):
    # Values as JavaScript's query-string would print them: 100.0 -> "100".
    if isinstance(value, bool):
        return 'true' if value else 'false'
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def webhook_signature(data, api_key):
    """Expected x-kashier-signature of a webhook: data.signatureKeys sorted,
    key=URL-encoded value pairs joined with &."""
    parts = []
    for key in sorted(data.get('signatureKeys') or []):
        value = data.get(key)
        parts.append(key if value is None else f'{key}={quote(_js_value(value), safe="")}')
    return _hmac(api_key, '&'.join(parts))


def signature_ok(received, expected):
    return bool(received) and hmac.compare_digest(received.lower(), expected.lower())

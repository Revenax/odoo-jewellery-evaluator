# -*- coding: utf-8 -*-
# Copyright 2026 Revenax Digital Services
# Author: Mohamed A. Abdallah
# Website: https://www.revenax.com
"""Kashier signature rules (payment_kashier/kashier_utils.py), without Odoo."""

import importlib.util
import os

_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "payment_kashier", "kashier_utils.py"))
_spec = importlib.util.spec_from_file_location("kashier_utils", _path)
ku = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ku)

# Kashier's own worked example (docs, Webhooks > step by step), key "11111".
DOC_DATA = {
    "amount": 1, "channel": "online | e-commerce", "currency": "EGP",
    "kashierOrderId": "9ad06b17-755b-4e21-9774-aff3e2726ac9", "merchantOrderId": "1653481557813",
    "method": "card", "orderReference": "TEST-ORD-38855", "status": "SUCCESS",
    "transactionId": "TX-249893963", "transactionResponseCode": "00",
    "signatureKeys": ["transactionResponseCode", "amount", "channel", "currency", "kashierOrderId",
                      "merchantOrderId", "method", "orderReference", "status", "transactionId"],
}
DOC_DIGEST = "9610477b2255b2a8ef84fd89adfaa5f1305ff9c20324205851890f1ea03109f4"


def test_webhook_signature_matches_kashier_example():
    assert ku.webhook_signature(DOC_DATA, "11111") == DOC_DIGEST


def test_webhook_float_amount_prints_like_javascript():
    assert ku.webhook_signature({**DOC_DATA, "amount": 1.0}, "11111") == DOC_DIGEST


def test_tampered_webhook_fails():
    assert not ku.signature_ok(DOC_DIGEST, ku.webhook_signature({**DOC_DATA, "amount": 2}, "11111"))


def test_redirect_signature_signs_missing_fields_as_null():
    a = ku.redirect_signature({"paymentStatus": "SUCCESS", "amount": "100"}, "k")
    b = ku.redirect_signature({"paymentStatus": "SUCCESS", "amount": "100", "cardBrand": "null"}, "k")
    assert a == b


def test_signature_ok_is_case_insensitive_and_rejects_empty():
    assert ku.signature_ok(DOC_DIGEST.upper(), DOC_DIGEST)
    assert not ku.signature_ok("", DOC_DIGEST)
    assert not ku.signature_ok(None, DOC_DIGEST)

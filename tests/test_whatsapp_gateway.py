# -*- coding: utf-8 -*-
# Copyright 2026 Revenax Digital Services
# Author: Mohamed A. Abdallah
# Website: https://www.revenax.com
"""WhatsApp gateway: webhook signature, verification, parsing, phone numbers, sending."""
import hashlib
import hmac
import importlib.util
import json
import os

import pytest

_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "whatsapp_gateway", "gateway.py"))
_spec = importlib.util.spec_from_file_location("wa_gateway", _path)
gw = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gw)

SECRET = "app-secret"


def sign(body, secret=SECRET):
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


# ---- signature

def test_valid_signature_accepted():
    body = b'{"a":1}'
    assert gw.verify_signature(SECRET, body, sign(body))


@pytest.mark.parametrize("header", [None, "", "sha1=abc", "sha256=deadbeef"])
def test_bad_or_missing_signature_rejected(header):
    assert not gw.verify_signature(SECRET, b'{"a":1}', header)


def test_tampered_body_rejected():
    assert not gw.verify_signature(SECRET, b'{"a":2}', sign(b'{"a":1}'))


def test_no_secret_configured_rejects_everything():
    body = b"{}"
    assert not gw.verify_signature("", body, sign(body, ""))


# ---- subscription check

def test_verification_echoes_challenge():
    params = {"hub.mode": ["subscribe"], "hub.verify_token": ["vt"], "hub.challenge": ["123"]}
    assert gw.verification_response(params, "vt") == (200, "123")


def test_verification_wrong_token():
    params = {"hub.mode": ["subscribe"], "hub.verify_token": ["nope"], "hub.challenge": ["123"]}
    assert gw.verification_response(params, "vt")[0] == 403


def test_verification_without_configured_token():
    params = {"hub.mode": ["subscribe"], "hub.verify_token": [""], "hub.challenge": ["1"]}
    assert gw.verification_response(params, "")[0] == 403


# ---- phone numbers

@pytest.mark.parametrize("raw,expected", [
    ("01063864994", "201063864994"),
    ("+20 106 386 4994", "201063864994"),
    ("00201063864994", "201063864994"),
    ("201063864994", "201063864994"),
    ("+1 (555) 165-9467", "15551659467"),
    ("123", ""),
    ("", ""),
    (None, ""),
])
def test_normalize_phone(raw, expected):
    assert gw.normalize_phone(raw) == expected


# ---- webhook parsing

def _wrap(value):
    return {"object": "whatsapp_business_account",
            "entry": [{"id": "957977993801864", "changes": [{"field": "messages", "value": value}]}]}


def test_parses_text_message_with_contact_name():
    ev = gw.parse_webhook(_wrap({
        "contacts": [{"wa_id": "201063864994", "profile": {"name": "Mohamed"}}],
        "messages": [{"id": "wamid.IN1", "from": "201063864994", "timestamp": "1", "type": "text",
                      "text": {"body": "Hello"}}]}))
    assert ev[0]["kind"] == "message" and ev[0]["text"] == "Hello" and ev[0]["name"] == "Mohamed"


def test_parses_business_scoped_user_id_sender():
    ev = gw.parse_webhook(_wrap({
        "contacts": [{"user_id": "EG.1125565290080476", "profile": {"name": "Mohamed A. Abdallah"}}],
        "messages": [{"id": "wamid.X", "from_user_id": "EG.1125565290080476", "type": "text",
                      "text": {"body": "Good evening"}}]}))
    assert ev[0]["from"] == "EG.1125565290080476" and ev[0]["name"] == "Mohamed A. Abdallah"


def test_parses_button_reply_and_caption():
    ev = gw.parse_webhook(_wrap({"messages": [
        {"id": "a", "from": "1", "type": "interactive", "interactive": {"button_reply": {"title": "Yes"}}},
        {"id": "b", "from": "1", "type": "image", "image": {"caption": "ring"}},
    ]}))
    assert [e["text"] for e in ev] == ["Yes", "ring"]


def test_parses_statuses():
    ev = gw.parse_webhook(_wrap({"statuses": [
        {"id": "wamid.OUT1", "status": "delivered", "recipient_id": "201063864994", "timestamp": "2"}]}))
    assert ev == [{"kind": "status", "wamid": "wamid.OUT1", "status": "delivered",
                   "recipient": "201063864994", "timestamp": "2", "errors": None, "raw": ev[0]["raw"]}]


@pytest.mark.parametrize("payload", [None, {}, {"object": "page"}, {"object": "whatsapp_business_account"},
                                     _wrap({})])
def test_unknown_shapes_give_no_events(payload):
    assert gw.parse_webhook(payload) == []


# ---- outbound body

def test_template_body_with_params():
    body = gw.build_message("201063864994", template="order_ready", language="ar", params=["MJ-1", 4500])
    assert body["type"] == "template"
    assert body["template"]["language"] == {"code": "ar"}
    assert body["template"]["components"][0]["parameters"] == [
        {"type": "text", "text": "MJ-1"}, {"type": "text", "text": "4500"}]


def test_text_body():
    body = gw.build_message("201063864994", text="hi")
    assert body["type"] == "text" and body["text"]["body"] == "hi"


@pytest.mark.parametrize("kw", [{}, {"template": "x", "text": "y"}])
def test_needs_exactly_one_of_template_or_text(kw):
    with pytest.raises(ValueError):
        gw.build_message("1", **kw)


# ---- never leak the token

def test_graph_error_scrubs_token():
    token = "EAA" + "x" * 60
    raw = json.dumps({"error": {"message": f"Malformed access token {token}", "code": 190}})
    safe = gw.safe_graph_error(raw, token)
    assert token not in json.dumps(safe) and safe["code"] == 190


def test_graph_error_scrubs_token_like_text_even_without_token():
    raw = json.dumps({"error": {"message": "bad EAA" + "Z" * 40, "code": 190}})
    assert "EAAZZZ" not in gw.safe_graph_error(raw, "")["message"]


# ---- receive end to end (store + signature)

def test_receive_stores_and_updates_status(tmp_path):
    store = gw.Store(str(tmp_path / "wa.db"))
    g = gw.Gateway(store, env={"WHATSAPP_APP_SECRET": SECRET})
    store.add(wamid="wamid.OUT1", direction="out", peer="201063864994", type="template", status="accepted")
    body = json.dumps(_wrap({
        "statuses": [{"id": "wamid.OUT1", "status": "read", "recipient_id": "201063864994"}],
        "messages": [{"id": "wamid.IN1", "from": "201063864994", "type": "text", "text": {"body": "Thanks"}}],
    })).encode()
    assert g.receive(body, sign(body))[0] == 200
    rows = {r["wamid"]: r for r in store.recent(10)}
    assert rows["wamid.OUT1"]["status"] == "read"
    assert rows["wamid.IN1"]["direction"] == "in" and rows["wamid.IN1"]["text"] == "Thanks"


def test_receive_rejects_unsigned(tmp_path):
    g = gw.Gateway(gw.Store(str(tmp_path / "wa.db")), env={"WHATSAPP_APP_SECRET": SECRET})
    assert g.receive(b"{}", None)[0] == 401


def test_send_refuses_bad_number_and_missing_config(tmp_path):
    g = gw.Gateway(gw.Store(str(tmp_path / "wa.db")), env={})
    assert g.send({"to": "12", "text": "x"})[0] == 400
    assert g.send({"to": "01063864994", "text": "x"})[0] == 503


# ---- documents (POS invoice PDFs)

def test_template_with_document_header():
    body = gw.build_message("201063864994", template="order_confirmation", language="en",
                            params=["Sara", "MJ-1619", "13,500"], document_id="MEDIA1", filename="Invoice.pdf")
    comps = body["template"]["components"]
    assert comps[0] == {"type": "header", "parameters": [
        {"type": "document", "document": {"id": "MEDIA1", "filename": "Invoice.pdf"}}]}
    assert [p["text"] for p in comps[1]["parameters"]] == ["Sara", "MJ-1619", "13,500"]


def test_text_with_document_becomes_captioned_document():
    body = gw.build_message("201063864994", text="Your invoice", document_id="M2", filename="a.pdf")
    assert body["type"] == "document" and body["document"] == {"id": "M2", "filename": "a.pdf", "caption": "Your invoice"}


def test_multipart_media_layout():
    data, ctype = gw.multipart_media(b"%PDF-1.4", 'inv"oice.pdf', boundary="BOUND")
    assert ctype == "multipart/form-data; boundary=BOUND"
    assert b'name="messaging_product"\r\n\r\nwhatsapp' in data
    assert b'filename="invoice.pdf"' in data and b"%PDF-1.4" in data and data.endswith(b"--BOUND--\r\n")


def test_send_rejects_bad_document(tmp_path):
    g = gw.Gateway(gw.Store(str(tmp_path / "wa.db")),
                   env={"WHATSAPP_TOKEN": "t", "WHATSAPP_PHONE_NUMBER_ID": "1"})
    assert g.send({"to": "01063864994", "template": "x", "document": {"base64": "not base64!!"}})[0] == 400
    assert g.send({"to": "01063864994", "template": "x", "document": {"base64": ""}})[0] == 400

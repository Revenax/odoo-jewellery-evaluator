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


# ---- staff inbox (ops app)

BSUID = "EG.1154488940450454"


def test_bsuid_kept_and_sent_as_recipient():
    assert gw.normalize_peer(BSUID) == BSUID
    assert gw.normalize_peer(" 01063864994 ") == "201063864994"
    body = gw.build_message(BSUID, text="Hi")
    assert body["recipient"] == BSUID and "to" not in body
    assert gw.build_message("201063864994", text="Hi")["to"] == "201063864994"


@pytest.mark.parametrize("header,ok", [
    ("Bearer k3y", True), ("Bearer wrong", False), ("k3y", False), (None, False), ("", False)])
def test_bearer_check(header, ok):
    assert gw.check_bearer(header, "k3y") is ok


def test_bearer_never_matches_empty_key():
    assert not gw.check_bearer("Bearer ", "")


def test_window_open():
    assert gw.window_open(1000.0, 1000.0 + 3600)
    assert not gw.window_open(1000.0, 1000.0 + 24 * 3600)
    assert not gw.window_open(None, 1000.0)


def _inbox(tmp_path):
    store = gw.Store(str(tmp_path / "wa.db"))
    g = gw.Gateway(store, env={"WHATSAPP_APP_SECRET": SECRET})
    store.add(wamid="w1", direction="in", peer=BSUID, name="Nina", type="text", text="Hello", status="received")
    store.add(wamid="w2", direction="out", peer="201007709545", type="template", text="template:x", status="read")
    store.add(wamid="w3", direction="in", peer=BSUID, name=None, type="image", text=None, status="received")
    return store, g


def test_conversations_grouped_with_unread_and_window(tmp_path):
    store, g = _inbox(tmp_path)
    status, rows = g.conversations()
    assert status == 200 and [r["peer"] for r in rows] == [BSUID, "201007709545"]
    nina = rows[0]
    assert nina["name"] == "Nina" and nina["unread"] == 2 and nina["window_open"]
    assert nina["last"]["type"] == "image"
    assert rows[1]["unread"] == 0 and not rows[1]["window_open"]


def test_thread_oldest_first_and_seen_clears_unread(tmp_path):
    store, g = _inbox(tmp_path)
    status, t = g.thread(BSUID)
    assert status == 200 and [m["text"] for m in t["messages"]] == ["Hello", None] and t["window_open"]
    assert g.seen({"peer": BSUID}) == (200, {"ok": True, "marked": 2})
    assert g.conversations()[1][0]["unread"] == 0
    assert g.seen({"peer": BSUID})[1]["marked"] == 0


def test_reply_validation_and_closed_window(tmp_path):
    store, g = _inbox(tmp_path)
    assert g.reply({"peer": BSUID, "text": "  "})[0] == 400
    assert g.reply({"peer": "x", "text": "hi"})[0] == 400
    assert g.reply({"peer": BSUID, "text": "x" * 5000})[0] == 400
    assert g.reply({"peer": "201007709545", "text": "hi"})[0] == 409  # never wrote to us
    assert g.reply({"peer": BSUID, "text": "hi"}, now=10**10)[0] == 409  # window long closed
    assert g.reply({"peer": BSUID, "text": "We open at 11"})[0] == 503  # open window; no token here


def test_store_migrates_seen_at(tmp_path):
    import sqlite3
    path = str(tmp_path / "old.db")
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE messages (id INTEGER PRIMARY KEY, wamid TEXT, direction TEXT NOT NULL, peer TEXT, "
                   "name TEXT, type TEXT, text TEXT, status TEXT, error TEXT, source TEXT, payload TEXT, "
                   "created_at REAL NOT NULL, updated_at REAL NOT NULL)")
    store = gw.Store(path)
    store.add(wamid="w", direction="in", peer=BSUID, status="received")
    assert store.mark_seen(BSUID) == ["w"]


def test_media_id_only_for_incoming_media():
    assert gw.media_id_of("image", json.dumps({"image": {"id": "12345678", "mime_type": "image/jpeg"}})) == "12345678"
    assert gw.media_id_of("text", json.dumps({"text": {"body": "x"}})) is None
    assert gw.media_id_of("image", "not json") is None


def test_thread_exposes_media_id_and_media_is_whitelisted(tmp_path):
    store = gw.Store(str(tmp_path / "wa.db"))
    g = gw.Gateway(store, env={"WHATSAPP_TOKEN": "t"})
    store.add(wamid="w", direction="in", peer=BSUID, type="image", status="received",
              payload=json.dumps({"type": "image", "image": {"id": "99887766"}}))
    assert g.thread(BSUID)[1]["messages"][0]["media_id"] == "99887766"
    assert g.media("11112222")[0] == 404  # never sent to us
    assert g.media("../etc")[0] == 404


def test_notify_is_off_without_url(tmp_path):
    g = gw.Gateway(gw.Store(str(tmp_path / "wa.db")), env={"WHATSAPP_OPS_KEY": "k"})
    g._notify({"from": BSUID, "name": "Nina", "type": "text", "text": "hi"})  # no URL: no thread, no error


# ---- inbox v2: templates, photos, unread

GRAPH_TEMPLATES = {"data": [
    {"name": "welcome_contact", "status": "APPROVED", "language": "en", "category": "MARKETING",
     "components": [{"type": "BODY", "text": "Hi {{1}}, this is Marjaan."}]},
    {"name": "order_confirmation", "status": "APPROVED", "language": "en", "category": "UTILITY",
     "components": [{"type": "HEADER", "format": "DOCUMENT"},
                    {"type": "BODY", "text": "Dear {{1}}, order {{2}} total {{3}}."}]},
    {"name": "draft_one", "status": "PENDING", "language": "en", "components": []},
]}


def test_summarize_templates_keeps_approved_with_param_count():
    out = gw.summarize_templates(GRAPH_TEMPLATES)
    assert [t["name"] for t in out] == ["order_confirmation", "welcome_contact"]
    assert out[0]["params"] == 3 and out[0]["header"] == "DOCUMENT"
    assert out[1]["params"] == 1 and out[1]["header"] is None


def test_render_template():
    assert gw.render_template("Hi {{1}}, order {{2}}", ["Sara", "MJ-1"]) == "Hi Sara, order MJ-1"
    assert gw.render_template("Hi {{1}} {{2}}", ["Sara"]) == "Hi Sara {{2}}"


def test_image_message_with_caption_and_recipient():
    body = gw.build_message(BSUID, text="Ring", image_id="IMG1")
    assert body["recipient"] == BSUID and body["type"] == "image"
    assert body["image"] == {"id": "IMG1", "caption": "Ring"}
    assert gw.build_message("201063864994", image_id="IMG1")["image"] == {"id": "IMG1"}


def _tpl_gateway(tmp_path):
    g = gw.Gateway(gw.Store(str(tmp_path / "wa.db")), env={"WHATSAPP_TOKEN": "", "WHATSAPP_PHONE_NUMBER_ID": "1"})
    g._templates = (10**12, gw.summarize_templates(GRAPH_TEMPLATES))  # cached, far future
    return g


def test_send_template_validation(tmp_path):
    g = _tpl_gateway(tmp_path)
    assert g.send_template({"peer": "x", "template": "welcome_contact", "params": ["A"]})[0] == 400
    assert g.send_template({"peer": "01063864994", "template": "nope", "params": []})[0] == 400
    assert "attachment" in g.send_template({"peer": "01063864994", "template": "order_confirmation",
                                            "params": ["a", "b", "c"]})[1]["error"]
    assert g.send_template({"peer": "01063864994", "template": "welcome_contact", "params": []})[0] == 400
    assert g.send_template({"peer": "01063864994", "template": "welcome_contact", "params": ["a\nb"]})[0] == 400
    # valid: reaches send(), which stops at the missing token
    assert g.send_template({"peer": "01063864994", "template": "welcome_contact", "params": ["Sara"]})[0] == 503


def test_reply_photo_validation(tmp_path):
    store, g = _inbox(tmp_path)
    assert g.reply({"peer": BSUID, "image": {"base64": "aGk=", "mime": "image/gif"}})[1]["error"].startswith("photos")
    assert g.reply({"peer": BSUID, "image": {"base64": "!!", "mime": "image/jpeg"}})[0] == 400
    assert g.reply({"peer": BSUID, "text": "x" * 2000, "image": {"base64": "aGk="}})[0] == 400


def test_mark_unread_and_outbound_media(tmp_path):
    store, g = _inbox(tmp_path)
    g.seen({"peer": BSUID})
    assert g.unread({"peer": BSUID}) == (200, {"ok": True, "marked": 1})
    assert g.conversations()[1][0]["unread"] == 1
    store.add(wamid="w9", direction="out", peer=BSUID, type="image", status="sent",
              payload=json.dumps({"type": "image", "image": {"id": "55554444"}}))
    assert g.thread(BSUID)[1]["messages"][-1]["media_id"] == "55554444"
    assert store.has_media("55554444")

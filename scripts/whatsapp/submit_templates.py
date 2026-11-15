# -*- coding: utf-8 -*-
# Copyright 2026 Revenax Digital Services
# Author: Mohamed A. Abdallah
# Website: https://www.revenax.com
"""Submit Marjaan's WhatsApp message templates to Meta for approval. Runs ON the Odoo box as root.

    sudo EXAMPLE_PDF=/tmp/wa_invoice.pdf python3 submit_templates.py          # submit missing ones
    sudo python3 submit_templates.py --status                                 # list status only

Templates are UTILITY (transactional), English only (owner decision 2026-11-15), wording
approved by the owner. Document-header templates need an example PDF for Meta's reviewers,
uploaded through the app's resumable upload. A template that already exists is skipped,
so re-running is safe. Approval arrives on the webhook (message_template_status_update)
and is visible with --status.
"""
import json
import os
import re
import sys
import urllib.error
import urllib.request

ENV = dict(l.strip().split("=", 1) for l in open("/etc/marjaan-whatsapp.env") if "=" in l)  # noqa: E741
TOKEN = ENV["WHATSAPP_TOKEN"]
APP_ID = os.environ.get("APP_ID", "1149149594233355")
MESSAGING_ACCOUNT = os.environ.get("MESSAGING_ACCOUNT", "1109104548407047")
GRAPH = "https://graph.facebook.com/v25.0"

TEMPLATES = [
    {
        "name": "order_confirmation",
        "document": True,
        "body": ("Dear {{1}}, thank you for shopping at Marjaan Jewellery ✨ Your order {{2}} is confirmed. "
                 "Total: {{3}} EGP. Your invoice is attached for your records. For sizing, cleaning or "
                 "any help, simply reply to this message."),
        "example": ["Sara", "MJ-1619", "13,500"],
    },
    {
        "name": "order_ready_pickup",
        "body": ("Hi {{1}}, good news! Your order {{2}} is ready for pickup at Marjaan {{3}}. "
                 "We look forward to seeing you."),
        "example": ["Sara", "MJ-1619", "Sway Mall"],
    },
    {
        "name": "payment_received",
        "body": ("Dear {{1}}, we have received your payment of {{2}} EGP for {{3}}. "
                 "Thank you for choosing Marjaan Jewellery."),
        "example": ["Sara", "13,500", "order MJ-1619"],
    },
    {
        "name": "buyback_receipt",
        "document": True,
        "body": ("Dear {{1}}, thank you for your trust. We have bought your piece ({{2}}) for {{3}} EGP. "
                 "Your receipt is attached."),
        "example": ["Sara", "18K Gold Ring · 4.45 g", "21,000"],
    },
    {
        "name": "welcome_contact",
        "body": ("Hi {{1}}, this is Marjaan Jewellery. Thank you for visiting us. This is our official "
                 "WhatsApp; reply here anytime for prices, new pieces or help with an order."),
        "example": ["Sara"],
    },
]


def call(req):
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        err = json.loads(e.read() or b"{}").get("error", {})
        msg = re.sub(r"EAA\w+", "[token]", str(err.get("error_user_msg") or err.get("message", "")))[:300]
        return {"_error": f"code {err.get('code')} subcode {err.get('error_subcode')}: {msg}"}


def auth(extra=None):
    return {"Authorization": f"Bearer {TOKEN}", **(extra or {})}


def existing():
    d = call(urllib.request.Request(
        f"{GRAPH}/{MESSAGING_ACCOUNT}/message_templates?fields=name,status,language,category&limit=100",
        headers=auth()))
    return {t["name"]: t for t in d.get("data", [])}


def example_handle():
    data = open(os.environ["EXAMPLE_PDF"], "rb").read()
    s = call(urllib.request.Request(
        f"{GRAPH}/{APP_ID}/uploads?file_length={len(data)}&file_type=application/pdf&file_name=invoice.pdf",
        method="POST", headers=auth()))
    if "_error" in s:
        raise SystemExit("upload session: " + s["_error"])
    h = call(urllib.request.Request(
        f"{GRAPH}/{s['id']}", data=data, method="POST",
        headers={"Authorization": f"OAuth {TOKEN}", "file_offset": "0"}))
    if "_error" in h:
        raise SystemExit("upload: " + h["_error"])
    return h["h"]


def main():
    have = existing()
    if "--status" in sys.argv:
        for t in TEMPLATES:
            cur = have.get(t["name"])
            print(f"{t['name']:22} {cur['status'] if cur else 'not submitted':10} {cur['category'] if cur else ''}")
        return
    handle = None
    for t in TEMPLATES:
        if t["name"] in have:
            print(f"{t['name']:22} exists: {have[t['name']]['status']}")
            continue
        components = []
        if t.get("document"):
            handle = handle or example_handle()
            components.append({"type": "HEADER", "format": "DOCUMENT", "example": {"header_handle": [handle]}})
        components.append({"type": "BODY", "text": t["body"], "example": {"body_text": [t["example"]]}})
        payload = {"name": t["name"], "language": "en", "category": "UTILITY", "components": components}
        r = call(urllib.request.Request(
            f"{GRAPH}/{MESSAGING_ACCOUNT}/message_templates", data=json.dumps(payload).encode(),
            method="POST", headers=auth({"Content-Type": "application/json"})))
        print(f"{t['name']:22} " + (r["_error"] if "_error" in r else f"submitted: {r.get('status')} {r.get('category')}"))


if __name__ == "__main__":
    main()

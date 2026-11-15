# -*- coding: utf-8 -*-
# Copyright 2026 Revenax Digital Services
# Author: Mohamed A. Abdallah
# Website: https://www.revenax.com
"""Send an APPROVED WhatsApp template (optionally with a document header). Runs ON the Odoo box as root.

    sudo TO=01007709545 TEMPLATE=order_confirmation PARAMS='["Nihal","MJ-1619","13,500"]' \
         FILE=/tmp/wa_invoice.pdf FILENAME="Marjaan Invoice MJ-1619.pdf" python3 send_template.py

Templates may be sent at any time (no 24-hour window). FILE is required for templates
whose header is a DOCUMENT (order_confirmation, buyback_receipt) and must be left out for
the others. The message is logged in the gateway's SQLite so delivery statuses update it.
Graph errors are printed as code/subcode only, never with the token.
"""
import json
import os
import re
import sqlite3
import time
import urllib.error
import urllib.request
import uuid

ENV = dict(l.strip().split("=", 1) for l in open("/etc/marjaan-whatsapp.env") if "=" in l)  # noqa: E741
TOKEN, PHONE_ID = ENV["WHATSAPP_TOKEN"], ENV["WHATSAPP_PHONE_NUMBER_ID"]
GRAPH = "https://graph.facebook.com/v25.0"
DB = "/var/lib/marjaan-whatsapp/whatsapp.db"


def call(req):
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        err = json.loads(e.read() or b"{}").get("error", {})
        msg = re.sub(r"EAA\w+", "[token]", str(err.get("error_data", {}).get("details") or err.get("message", "")))
        raise SystemExit(f"ERROR code {err.get('code')} subcode {err.get('error_subcode')}: {msg[:300]}")


def upload(path, filename):
    data = open(path, "rb").read()
    b = uuid.uuid4().hex
    body = (
        f"--{b}\r\nContent-Disposition: form-data; name=\"messaging_product\"\r\n\r\nwhatsapp\r\n"
        f"--{b}\r\nContent-Disposition: form-data; name=\"type\"\r\n\r\napplication/pdf\r\n"
        f"--{b}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{filename}\"\r\n"
        f"Content-Type: application/pdf\r\n\r\n"
    ).encode() + data + f"\r\n--{b}--\r\n".encode()
    return call(urllib.request.Request(
        f"{GRAPH}/{PHONE_ID}/media", data=body, method="POST",
        headers={"Authorization": f"Bearer {TOKEN}",
                 "Content-Type": f"multipart/form-data; boundary={b}"}))["id"]


def main():
    to = re.sub(r"\D", "", os.environ["TO"])
    if to.startswith("0"):
        to = "20" + to[1:]
    name = os.environ["TEMPLATE"]
    params = json.loads(os.environ.get("PARAMS", "[]"))
    components = []
    if os.environ.get("FILE"):
        filename = os.environ.get("FILENAME") or os.path.basename(os.environ["FILE"])
        media_id = upload(os.environ["FILE"], filename)
        components.append({"type": "header", "parameters": [
            {"type": "document", "document": {"id": media_id, "filename": filename}}]})
    if params:
        components.append({"type": "body", "parameters": [{"type": "text", "text": str(p)} for p in params]})
    msg = {"messaging_product": "whatsapp", "to": to, "type": "template",
           "template": {"name": name, "language": {"code": os.environ.get("LANG_CODE", "en")},
                        "components": components}}
    wamid = call(urllib.request.Request(
        f"{GRAPH}/{PHONE_ID}/messages", data=json.dumps(msg).encode(), method="POST",
        headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}))["messages"][0]["id"]
    now = time.time()
    with sqlite3.connect(DB) as db:
        db.execute("INSERT INTO messages (wamid, direction, peer, type, text, status, source, created_at, updated_at) "
                   "VALUES (?,?,?,?,?,?,?,?,?)",
                   (wamid, "out", to, "template", f"template:{name} {params}", "accepted",
                    os.environ.get("SOURCE", "send_template"), now, now))
    print(f"sent template {name} to {to}")


if __name__ == "__main__":
    main()

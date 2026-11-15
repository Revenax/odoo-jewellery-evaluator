# -*- coding: utf-8 -*-
# Copyright 2026 Revenax Digital Services
# Author: Mohamed A. Abdallah
# Website: https://www.revenax.com
"""Send a file (PDF, image) over WhatsApp with a caption. Runs ON the Odoo box as root.

    sudo TO=201063864994 FILE=/tmp/invoice.pdf FILENAME="Marjaan Invoice MJ-1617.pdf" \
         CAPTION_FILE=/tmp/caption.txt python3 send_document.py

Reads the token and phone number id from /etc/marjaan-whatsapp.env (never prints them),
uploads the file as WhatsApp media, sends it as a document (or image, by mime type), and
logs the message in the gateway's SQLite so delivery statuses update it.

A free-form message like this only reaches someone who wrote to the number in the last
24 hours. Outside that window use an approved template (docs/whatsapp.md section 6).
"""
import json
import mimetypes
import os
import re
import sqlite3
import time
import urllib.error
import urllib.request
import uuid

ENV = dict(l.strip().split("=", 1) for l in open("/etc/marjaan-whatsapp.env") if "=" in l)
TOKEN, PHONE_ID = ENV["WHATSAPP_TOKEN"], ENV["WHATSAPP_PHONE_NUMBER_ID"]
GRAPH = "https://graph.facebook.com/v25.0"
DB = "/var/lib/marjaan-whatsapp/whatsapp.db"


def call(req):
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        err = json.loads(e.read() or b"{}").get("error", {})
        msg = re.sub(r"EAA\w+", "[token]", str(err.get("message", "")))[:200]  # never echo the token
        raise SystemExit(f"ERROR code {err.get('code')} subcode {err.get('error_subcode')}: {msg}")


def main():
    to = re.sub(r"\D", "", os.environ["TO"])
    if to.startswith("0"):
        to = "20" + to[1:]
    path = os.environ["FILE"]
    filename = os.environ.get("FILENAME") or os.path.basename(path)
    caption = open(os.environ["CAPTION_FILE"]).read().strip() if os.environ.get("CAPTION_FILE") else ""
    mime = mimetypes.guess_type(filename)[0] or "application/pdf"
    kind = "image" if mime.startswith("image/") else "document"

    data = open(path, "rb").read()
    b = uuid.uuid4().hex
    body = (
        f"--{b}\r\nContent-Disposition: form-data; name=\"messaging_product\"\r\n\r\nwhatsapp\r\n"
        f"--{b}\r\nContent-Disposition: form-data; name=\"type\"\r\n\r\n{mime}\r\n"
        f"--{b}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{filename}\"\r\n"
        f"Content-Type: {mime}\r\n\r\n"
    ).encode() + data + f"\r\n--{b}--\r\n".encode()
    media_id = call(urllib.request.Request(
        f"{GRAPH}/{PHONE_ID}/media", data=body, method="POST",
        headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": f"multipart/form-data; boundary={b}"}))["id"]

    payload = {"id": media_id}
    if caption:
        payload["caption"] = caption[:1024]
    if kind == "document":
        payload["filename"] = filename
    msg = {"messaging_product": "whatsapp", "to": to, "type": kind, kind: payload}
    wamid = call(urllib.request.Request(
        f"{GRAPH}/{PHONE_ID}/messages", data=json.dumps(msg).encode(), method="POST",
        headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}))["messages"][0]["id"]

    now = time.time()
    with sqlite3.connect(DB) as db:
        db.execute("INSERT INTO messages (wamid, direction, peer, type, text, status, source, created_at, updated_at) "
                   "VALUES (?,?,?,?,?,?,?,?,?)",
                   (wamid, "out", to, kind, f"{kind}: {filename}", "accepted",
                    os.environ.get("SOURCE", "send_document"), now, now))
    print(f"sent {kind} {filename} to {to}")


if __name__ == "__main__":
    main()

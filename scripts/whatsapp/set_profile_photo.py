# -*- coding: utf-8 -*-
# Copyright 2026 Revenax Digital Services
# Author: Mohamed A. Abdallah
# Website: https://www.revenax.com
"""Set the WhatsApp business profile photo. Runs ON the Odoo box as root.

    sudo PHOTO=/tmp/wa_profile.jpg [PHONE_ID=<id>] python3 set_profile_photo.py

The photo must be a square JPEG (640x640 works); WhatsApp crops it to a circle, so keep
the mark inside the centre. Uses Meta's resumable upload: an upload session on the APP
(/{app-id}/uploads) gives a handle, which goes to /{phone-number-id}/whatsapp_business_profile.
The 2026-11-15 photo (gold Marjaan mark on navy) was built from
marjaan_branding/static/img/icon-512x512.png scaled to 86% on a 640px #0f1138 square.
"""
import json
import os
import re
import urllib.error
import urllib.request

ENV = dict(l.strip().split("=", 1) for l in open("/etc/marjaan-whatsapp.env") if "=" in l)
TOKEN = ENV["WHATSAPP_TOKEN"]
PHONE_ID = os.environ.get("PHONE_ID") or ENV["WHATSAPP_PHONE_NUMBER_ID"]  # PHONE_ID= for another number
APP_ID = os.environ.get("APP_ID", "1149149594233355")
GRAPH = "https://graph.facebook.com/v25.0"


def call(req):
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        err = json.loads(e.read() or b"{}").get("error", {})
        msg = re.sub(r"EAA\w+", "[token]", str(err.get("message", "")))[:200]
        raise SystemExit(f"ERROR code {err.get('code')} subcode {err.get('error_subcode')}: {msg}")


data = open(os.environ["PHOTO"], "rb").read()
session = call(urllib.request.Request(
    f"{GRAPH}/{APP_ID}/uploads?file_length={len(data)}&file_type=image/jpeg", method="POST",
    headers={"Authorization": f"Bearer {TOKEN}"}))["id"]
handle = call(urllib.request.Request(
    f"{GRAPH}/{session}", data=data, method="POST",
    headers={"Authorization": f"OAuth {TOKEN}", "file_offset": "0"}))["h"]
ok = call(urllib.request.Request(
    f"{GRAPH}/{PHONE_ID}/whatsapp_business_profile", method="POST",
    data=json.dumps({"messaging_product": "whatsapp", "profile_picture_handle": handle}).encode(),
    headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}))
print("profile photo updated:", ok.get("success"))

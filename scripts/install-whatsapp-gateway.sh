#!/usr/bin/env bash
# -*- coding: utf-8 -*-
# Copyright 2026 Revenax Digital Services
# Author: Mohamed A. Abdallah
# Website: https://www.revenax.com
#
# Install / update the WhatsApp gateway (whatsapp_gateway/gateway.py) on the Odoo box as
# the systemd service marjaan-whatsapp on 127.0.0.1:8076, and route ONLY the public
# webhook path /whatsapp/webhook to it through nginx. Server-side, like the price feed:
# re-run if the box is rebuilt.
#
#   scripts/install-whatsapp-gateway.sh          # from the Mac (copies + installs over SSH)
#
# Secrets live in /etc/marjaan-whatsapp.env (root 600, read by systemd):
#   WHATSAPP_TOKEN        system-user token        (pasted by the owner, never by script)
#   WHATSAPP_APP_SECRET   Meta app secret          (pasted by the owner, never by script)
#   WHATSAPP_VERIFY_TOKEN webhook verify token     (generated here once if missing)
#   WHATSAPP_PHONE_NUMBER_ID                       (set here if missing; not a secret)
# This script never prints any of them.
set -euo pipefail
cd "$(dirname "$0")/.."
KEY="${MARJAAN_PEM:-$HOME/Documents/Marjaan/marjaan-odoo-19.pem}"
HOST="${MARJAAN_HOST:-ubuntu@odoo.marjaanjewellery.com}"
PHONE_NUMBER_ID="${WHATSAPP_PHONE_NUMBER_ID:-1438279769373042}"

scp -q -i "$KEY" whatsapp_gateway/gateway.py "$HOST:/tmp/marjaan-whatsapp-gateway.py"
ssh -i "$KEY" "$HOST" "sudo bash -s" -- "$PHONE_NUMBER_ID" <<'REMOTE'
set -euo pipefail
PHONE_NUMBER_ID="$1"
ENVF=/etc/marjaan-whatsapp.env
SITE=/etc/nginx/sites-available/odoo
install -d -m 755 /opt/marjaan-whatsapp
install -m 644 /tmp/marjaan-whatsapp-gateway.py /opt/marjaan-whatsapp/gateway.py
rm -f /tmp/marjaan-whatsapp-gateway.py
install -d -o odoo -g odoo -m 750 /var/lib/marjaan-whatsapp

touch "$ENVF"; chown root:root "$ENVF"; chmod 600 "$ENVF"
grep -q '^WHATSAPP_VERIFY_TOKEN=' "$ENVF" || echo "WHATSAPP_VERIFY_TOKEN=$(openssl rand -hex 24)" >> "$ENVF"
grep -q '^WHATSAPP_PHONE_NUMBER_ID=' "$ENVF" || echo "WHATSAPP_PHONE_NUMBER_ID=$PHONE_NUMBER_ID" >> "$ENVF"

cat > /etc/systemd/system/marjaan-whatsapp.service <<'UNIT'
[Unit]
Description=Marjaan WhatsApp gateway (Cloud API webhook + send, 127.0.0.1:8076)
After=network-online.target
Wants=network-online.target

[Service]
User=odoo
Group=odoo
EnvironmentFile=/etc/marjaan-whatsapp.env
ExecStart=/usr/bin/python3 /opt/marjaan-whatsapp/gateway.py
Restart=always
RestartSec=5
MemoryMax=96M
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
PrivateTmp=true
ReadWritePaths=/var/lib/marjaan-whatsapp

[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable --now marjaan-whatsapp >/dev/null
systemctl restart marjaan-whatsapp

if ! grep -q 'location = /whatsapp/webhook' "$SITE"; then
    BAK="$SITE.bak-$(date +%Y%m%d-%H%M%S)"
    cp -a "$SITE" "$BAK"
    # First server block (the 443 one): right after its error_log line.
    awk '!done && /error_log/ { print; print "    # WhatsApp Cloud API webhook -> marjaan-whatsapp gateway (scripts/install-whatsapp-gateway.sh)";
         print "    location = /whatsapp/webhook {"; print "        proxy_pass http://127.0.0.1:8076;";
         print "        client_max_body_size 1m;"; print "    }"; done=1; next } { print }' "$BAK" > "$SITE"
    if ! nginx -t 2>/dev/null; then cp -a "$BAK" "$SITE"; nginx -t; echo "nginx -t failed, restored $BAK" >&2; exit 1; fi
    echo "nginx route added (backup $BAK)"
fi
nginx -t 2>/dev/null && systemctl reload nginx
sleep 2
systemctl is-active marjaan-whatsapp
curl -fsS http://127.0.0.1:8076/health; echo
REMOTE

#!/bin/bash
# Install / update the local price feed (price_feed/edahab_feed.py) as the
# systemd service marjaan-price-feed: loopback-only http://127.0.0.1:8075.
# Server-side, like the watchdog and backups: re-run if the box is rebuilt.
set -euo pipefail
REPO=${REPO:-/opt/odoo/custom-addons/jewellery_evaluator}
PY=${PY:-/opt/odoo/odoo-venv/bin/python3}
sudo install -d -o odoo -g odoo -m 750 /var/lib/marjaan-price-feed
sudo tee /etc/systemd/system/marjaan-price-feed.service >/dev/null <<UNIT
[Unit]
Description=Marjaan local gold/silver/USD price feed (eDahab -> 127.0.0.1:8075)
After=network-online.target
Wants=network-online.target

[Service]
User=odoo
Group=odoo
ExecStart=$PY $REPO/price_feed/edahab_feed.py
Restart=always
RestartSec=10
MemoryMax=128M
NoNewPrivileges=true
ProtectSystem=strict
ReadWritePaths=/var/lib/marjaan-price-feed

[Install]
WantedBy=multi-user.target
UNIT
sudo systemctl daemon-reload
sudo systemctl enable --now marjaan-price-feed
sudo systemctl restart marjaan-price-feed
sleep 5
curl -fsS http://127.0.0.1:8075/prices | head -c 400; echo

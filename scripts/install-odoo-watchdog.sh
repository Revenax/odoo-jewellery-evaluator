#!/usr/bin/env bash
# -*- coding: utf-8 -*-
# Copyright 2026 Revenax Digital Services
#
# Installs Odoo self-healing on the prod box. Two layers:
#   1. A systemd drop-in so the odoo.service AUTO-RESTARTS when its process exits
#      (crash / failed start / kill). The stock unit has no Restart= directive,
#      so today a dead Odoo just stays dead until someone runs it by hand — the
#      "odoo is down again" problem.
#   2. A 1-minute watchdog timer that restarts Odoo if it has given up
#      (systemd start-limit hit) OR is alive-but-unresponsive (the 502 / hung
#      case that Restart= cannot see). Mirrors a manual `systemctl restart odoo`,
#      but instant and unattended.
#
# Deploy-safe: the watchdog only acts on a 'failed' service or an 'active'-but-
# hung one. The 'inactive'/'activating' states a deploy briefly produces are
# left alone, so it never fights remote-deploy.sh.
#
# Idempotent — safe to re-run. Run as a sudoer on the prod box. NOT in git's
# deploy path; this is server-side infra (like the patched wkhtmltopdf), so if
# the EC2 box is rebuilt, re-run this.
set -euo pipefail

echo "[1/4] watchdog script -> /opt/odoo/odoo-watchdog.sh"
sudo tee /opt/odoo/odoo-watchdog.sh >/dev/null <<'WATCHDOG'
#!/usr/bin/env bash
# Restart Odoo if it has crashed/failed or gone unresponsive (502 / timeout).
# Mirrors a manual `systemctl restart odoo`, instant and unattended.
set -uo pipefail
LOG=/var/log/odoo-watchdog.log
URL="http://127.0.0.1:8069/web/login"
log() { echo "$(date '+%F %T') $*" >>"$LOG" 2>/dev/null; }

healthy() {
  local c
  c=$(curl -s -o /dev/null -w '%{http_code}' --max-time 15 "$URL" 2>/dev/null)
  [ -n "$c" ] && [ "$c" != "000" ] && [ "${c:0:1}" != "5" ]
}

state=$(systemctl is-active odoo 2>/dev/null)
case "$state" in
  failed)
    log "service=failed -> systemctl restart odoo"
    systemctl restart odoo
    ;;
  active)
    # Alive but maybe hung (nginx would show 502). Confirm twice before acting
    # so a freshly-started, still-loading Odoo is not killed.
    if ! healthy; then
      sleep 10
      if ! healthy; then
        log "service=active but unresponsive -> systemctl restart odoo"
        systemctl restart odoo
      fi
    fi
    ;;
  *)
    : # inactive / activating / deactivating -> deploy or transition; leave alone
    ;;
esac
WATCHDOG
sudo chmod +x /opt/odoo/odoo-watchdog.sh

echo "[2/4] systemd drop-in: auto-restart odoo on failure"
sudo mkdir -p /etc/systemd/system/odoo.service.d
sudo tee /etc/systemd/system/odoo.service.d/restart.conf >/dev/null <<'DROPIN'
[Unit]
StartLimitIntervalSec=300
StartLimitBurst=5

[Service]
Restart=on-failure
RestartSec=5
DROPIN

echo "[3/4] watchdog service + 1-minute timer"
sudo tee /etc/systemd/system/odoo-watchdog.service >/dev/null <<'SVC'
[Unit]
Description=Odoo watchdog (restart if down or unresponsive)
After=odoo.service

[Service]
Type=oneshot
ExecStart=/opt/odoo/odoo-watchdog.sh
SVC
sudo tee /etc/systemd/system/odoo-watchdog.timer >/dev/null <<'TMR'
[Unit]
Description=Run the Odoo watchdog every minute

[Timer]
OnBootSec=2min
OnUnitActiveSec=60
AccuracySec=10s

[Install]
WantedBy=timers.target
TMR

echo "[4/4] reload + enable"
sudo systemctl daemon-reload
sudo systemctl enable --now odoo-watchdog.timer
echo "Done. Drop-in + watchdog active:"
systemctl show odoo -p Restart -p RestartUSec
systemctl list-timers odoo-watchdog.timer --no-pager 2>/dev/null | head -3

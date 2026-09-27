#!/usr/bin/env bash
# Copyright 2026 Revenax Digital Services
# Author: Mohamed A. Abdallah
# Website: https://www.revenax.com
#
# Proper log rotation for the production box (idempotent — safe to re-run).
#   scp scripts/install-logrotate.sh ubuntu@host:/tmp/ && ssh ubuntu@host 'sudo bash /tmp/install-logrotate.sh'
#
# Replaces /etc/logrotate.d/00-size-guard, which was wrong in a subtle way: it
# listed /var/log/syslog, which /etc/logrotate.d/rsyslog already owns. logrotate
# rejects a path claimed twice ("duplicate log entry"), so it skipped syslog in
# the rsyslog block and exited non-zero every day. The size guard it meant to
# add now lives where it belongs:
#
#   odoo.log  -> its own rule: daily, 30 compressed days, AND early rotation at
#                200 MB (a crash-loop once wrote 7.1 GB of tracebacks in hours).
#                `create` + move is safe: Odoo logs through WatchedFileHandler,
#                which reopens the file when its inode changes — no copytruncate.
#   syslog &c -> the package rule keeps weekly x4, plus `maxsize 200M`.
#   timer     -> logrotate runs HOURLY so a size limit is checked within the
#                hour instead of once a day. `daily`/`weekly` still rotate on
#                schedule (logrotate tracks that in its state file).
#
# Like the watchdog, this is server config outside the deploy path: re-run it if
# the EC2 box is ever rebuilt.

set -euo pipefail
[ "$(id -u)" = 0 ] || { echo "run as root (sudo)"; exit 1; }

cat > /etc/logrotate.d/odoo <<'CONF'
/var/log/odoo/*.log {
    su odoo odoo
    daily
    maxsize 200M
    rotate 30
    compress
    delaycompress
    dateext
    dateformat -%Y%m%d-%s
    missingok
    notifempty
    create 0644 odoo odoo
}
CONF

rm -f /etc/logrotate.d/00-size-guard

# Size limit on the rsyslog block (a dpkg conffile: unattended-upgrades keeps
# local edits, and a manual upgrade will ask — keep the local version).
grep -q '^\s*maxsize' /etc/logrotate.d/rsyslog || sed -i '/^{/a\	maxsize 200M' /etc/logrotate.d/rsyslog

mkdir -p /etc/systemd/system/logrotate.timer.d
cat > /etc/systemd/system/logrotate.timer.d/hourly.conf <<'CONF'
[Timer]
OnCalendar=
OnCalendar=hourly
AccuracySec=5min
CONF
systemctl daemon-reload
systemctl restart logrotate.timer

# Validate the whole configuration (debug mode changes nothing).
if logrotate -d /etc/logrotate.conf 2>&1 | grep -E '^error'; then
  echo "logrotate config has errors (above)"; exit 1
fi
echo "logrotate config OK"
systemctl list-timers logrotate.timer --no-pager | sed -n 1,2p

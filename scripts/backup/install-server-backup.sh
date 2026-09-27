#!/usr/bin/env bash
# Copyright 2026 Revenax Digital Services
# Author: Mohamed A. Abdallah
# Website: https://www.revenax.com
#
# Install the nightly backup on the production box (idempotent — safe to re-run).
#   scp scripts/backup/{server-backup.sh,install-server-backup.sh} ubuntu@host:/tmp/
#   ssh ubuntu@host 'sudo bash /tmp/install-server-backup.sh /tmp/server-backup.sh'
#
# Like the watchdog and wkhtmltopdf, this lives on the box, NOT in the deploy
# path: re-run it if the EC2 instance is ever rebuilt.

set -euo pipefail
SRC="${1:-$(dirname "$0")/server-backup.sh}"
[ "$(id -u)" = 0 ] || { echo "run as root (sudo)"; exit 1; }

install -m 755 "$SRC" /usr/local/sbin/marjaan-backup

if ! command -v aws >/dev/null 2>&1; then
  echo "installing AWS CLI v2"
  command -v unzip >/dev/null || apt-get install -y -qq unzip
  t="$(mktemp -d)"
  curl -fsSL "https://awscli.amazonaws.com/awscli-exe-linux-$(uname -m).zip" -o "$t/awscli.zip"
  unzip -q "$t/awscli.zip" -d "$t" && "$t/aws/install" --update >/dev/null
  rm -rf "$t"
fi
aws --version

if [ ! -f /etc/marjaan-backup.env ]; then
  cat > /etc/marjaan-backup.env <<'ENV'
# Filled in from the output of scripts/backup/aws-setup-cloudshell.sh.
# Empty = local-only backups (the job still runs and still alerts on failure).
BACKUP_BUCKET=
AWS_ACCESS_KEY_ID=
AWS_SECRET_ACCESS_KEY=
AWS_DEFAULT_REGION=us-east-1
ENV
fi
chmod 600 /etc/marjaan-backup.env; chown root:root /etc/marjaan-backup.env

cat > /etc/systemd/system/marjaan-backup.service <<'UNIT'
[Unit]
Description=Nightly backup of production Odoo (db + filestore + config)
After=postgresql.service network-online.target
Wants=network-online.target

[Service]
Type=oneshot
ExecStart=/usr/local/sbin/marjaan-backup
Nice=10
IOSchedulingClass=idle
UNIT

cat > /etc/systemd/system/marjaan-backup.timer <<'UNIT'
[Unit]
Description=Run the Marjaan production backup nightly, after the shop closes

[Timer]
OnCalendar=*-*-* 03:15:00 Africa/Cairo
RandomizedDelaySec=10min
Persistent=true

[Install]
WantedBy=timers.target
UNIT

systemctl daemon-reload
systemctl enable --now marjaan-backup.timer
systemctl list-timers marjaan-backup.timer --no-pager

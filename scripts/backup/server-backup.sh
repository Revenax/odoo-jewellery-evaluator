#!/usr/bin/env bash
# Copyright 2026 Revenax Digital Services
# Author: Mohamed A. Abdallah
# Website: https://www.revenax.com
#
# Nightly backup ON the production box, run by marjaan-backup.timer as root.
# Installed to /usr/local/sbin/marjaan-backup by install-server-backup.sh.
#
#   1. pg_dump -> /var/backups/marjaan/db, verified with pg_restore -l + sha256.
#      Kept locally for KEEP_LOCAL nights: the fast path back from a bad data
#      edit, independent of the network.
#   2. If /etc/marjaan-backup.env holds S3 credentials, ship the dump, the
#      server-config snapshot and the filestore to S3. The key is WRITE-ONLY
#      (put + list, no get, no delete) and the bucket is versioned, so a stolen
#      server key can neither read the data nor destroy the history.
#   3. Any failure -> Revenax Pulse `job-failed` (Odoo already owns that topic;
#      a failed backup is a failed job, so no new topic and no overlap).
#
# The local copy on this disk does NOT protect against losing this disk. The
# S3 copy and the Mac mini pull (backup-to-local.sh) are what do.

set -euo pipefail
DB="${MARJAAN_DB:-marjaan}"
DIR=/var/backups/marjaan
FILESTORE=/opt/odoo/.local/share/Odoo/filestore/$DB
KEEP_LOCAL="${KEEP_LOCAL:-7}"
STAMP="$(date -u +%Y%m%d-%H%M%S)"
STEP="start"

# shellcheck disable=SC1091
[ -f /etc/revenax-pulse.env ] && . /etc/revenax-pulse.env
# shellcheck disable=SC1091
[ -f /etc/marjaan-backup.env ] && . /etc/marjaan-backup.env

pulse() {  # pulse <topic> <title> <body> <idempotency-key> — never blocks, never fails the job
  [ -n "${REVENAX_PULSE_SERVICE_NAME:-}" ] && [ -n "${REVENAX_PULSE_API_KEY:-}" ] || return 0
  curl -s -o /dev/null --max-time 5 -X POST https://pulse.revenax.com/notify \
    -H "X-Service-Name: ${REVENAX_PULSE_SERVICE_NAME}" -H "X-API-Key: ${REVENAX_PULSE_API_KEY}" \
    -H "Idempotency-Key: $4" -H 'Content-Type: application/json' \
    --data "$(printf '{"topic":"%s","title":"%s","body":"%s","data":{"host":"%s"}}' "$1" "$2" "$3" "$(hostname)")" \
    >/dev/null 2>&1 || true
}
on_err() {
  echo "backup FAILED at step: $STEP" >&2
  pulse job-failed "Nightly backup failed" "Production Odoo backup failed at: $STEP" "backup:failed:$(date -u +%F)"
}
trap on_err ERR

install -d -m 700 "$DIR" "$DIR/db" "$DIR/config"

STEP="pg_dump"
OUT="$DIR/db/$DB-$STAMP.dump"
sudo -u postgres pg_dump -Fc -Z 6 -d "$DB" > "$OUT.partial"
STEP="verify dump"
pg_restore -l "$OUT.partial" > /dev/null
mv "$OUT.partial" "$OUT"
sha256sum "$OUT" | cut -d' ' -f1 > "$OUT.sha256"
echo "db dump $(du -h "$OUT" | cut -f1) ok"

STEP="config snapshot"
CFG="$DIR/config/config-$STAMP.tgz"
tar -czf "$CFG" --ignore-failed-read -C / etc/odoo.conf etc/systemd/system/odoo.service.d \
  opt/odoo/ee-odoo-bin opt/odoo/odoo-watchdog.sh etc/nginx/sites-available/odoo \
  etc/logrotate.d etc/revenax-pulse.env 2>/dev/null || true
chmod 600 "$CFG" 2>/dev/null || true

STEP="local retention"
ls -1 "$DIR"/db/"$DB"-*.dump | sort -r | tail -n +"$((KEEP_LOCAL+1))" | while read -r f; do rm -f "$f" "$f.sha256"; done
ls -1 "$DIR"/config/config-*.tgz 2>/dev/null | sort -r | tail -n +"$((KEEP_LOCAL+1))" | xargs -r rm -f

if [ -n "${BACKUP_BUCKET:-}" ] && [ -n "${AWS_ACCESS_KEY_ID:-}" ] && [ -n "${AWS_SECRET_ACCESS_KEY:-}" ]; then
  export AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-us-east-1}"
  STEP="s3 upload db"
  aws s3 cp --only-show-errors "$OUT" "s3://$BACKUP_BUCKET/db/$(basename "$OUT")"
  aws s3 cp --only-show-errors "$OUT.sha256" "s3://$BACKUP_BUCKET/db/$(basename "$OUT").sha256"
  STEP="s3 upload config"
  [ -f "$CFG" ] && aws s3 cp --only-show-errors "$CFG" "s3://$BACKUP_BUCKET/config/$(basename "$CFG")"
  STEP="s3 sync filestore"
  # Additive: Odoo attachments are content-addressed and never rewritten, so no --delete.
  aws s3 sync --only-show-errors "$FILESTORE/" "s3://$BACKUP_BUCKET/filestore/"
  echo "s3 upload to $BACKUP_BUCKET ok"
else
  echo "S3 not configured (/etc/marjaan-backup.env) — local copy only"
fi

date -u +%FT%TZ > "$DIR/last-success"
echo "backup $STAMP OK"

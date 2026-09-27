#!/bin/bash
# Copyright 2026 Revenax Digital Services
# Author: Mohamed A. Abdallah
# Website: https://www.revenax.com
#
# Pull a verified backup of production Marjaan Odoo onto THIS machine.
# Built for a Mac mini on a nightly cron; runs anywhere with bash + ssh + rsync.
#
# What it takes, every run:
#   db/        pg_dump custom-format of the `marjaan` database (+ .sha256)
#   filestore/ an rsync MIRROR of the attachment store, never deleting
#   config/    /etc/odoo.conf, systemd drop-ins, the ee-odoo-bin wrapper,
#              watchdog, nginx site, logrotate rules (contains SECRETS: 0600)
#   neon/      the ops-app database, only if NEON_DATABASE_URL is set and a
#              local pg_dump exists (`brew install libpq`)
#
# Why the filestore is a mirror that never deletes: Odoo names every attachment
# by the sha1 of its content and never rewrites one, so a mirror that only ever
# adds files is a superset able to serve ANY older database dump. One copy
# covers every point in time; no per-night tarball needed.
#
# Verification, because an unverified backup is not a backup:
#   - the dump is staged on the server and read back with `pg_restore -l`
#     (proves the archive is structurally complete) before it is fetched
#   - its sha256 is taken on the server and re-checked after transfer
#   - a manifest records row counts so a restore can be sanity-checked
#
# macOS cron note: cron cannot read ~/Documents, ~/Desktop or ~/Downloads
# (privacy protection) without Full Disk Access. Keep the SSH key in ~/.ssh
# and the backup dir outside those folders — the defaults below already do.
#
# Overrides go in ~/.config/marjaan-backup.env (sourced if present), e.g.
#   MARJAAN_BACKUP_DIR=/Volumes/Backup/Marjaan
#   KEEP_DAILY=30
#   NEON_DATABASE_URL=postgres://...

set -euo pipefail
export PATH="/opt/homebrew/bin:/opt/homebrew/opt/libpq/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"

CONF="${HOME}/.config/marjaan-backup.env"
# shellcheck disable=SC1090
[ -f "$CONF" ] && . "$CONF"

HOST="${MARJAAN_HOST:-ubuntu@odoo.marjaanjewellery.com}"
KEY="${MARJAAN_SSH_KEY:-$HOME/.ssh/marjaan-odoo-19.pem}"
DIR="${MARJAAN_BACKUP_DIR:-$HOME/MarjaanBackups}"
DB="${MARJAAN_DB:-marjaan}"
FILESTORE="${MARJAAN_FILESTORE:-/opt/odoo/.local/share/Odoo/filestore/marjaan}"
KEEP_DAILY="${KEEP_DAILY:-30}"      # newest N nightly dumps
KEEP_MONTHLY="${KEEP_MONTHLY:-12}"  # plus the first dump of each of the last N months
KEEP_CONFIG="${KEEP_CONFIG:-14}"

[ -f "$KEY" ] || KEY="$HOME/Documents/marjaan-odoo-19.pem"   # interactive fallback
SSH_OPTS="-i $KEY -o BatchMode=yes -o ConnectTimeout=30 -o ServerAliveInterval=15 -o StrictHostKeyChecking=accept-new"
STAMP="$(date +%Y%m%d-%H%M%S)"
LOG="$DIR/backup.log"

mkdir -p "$DIR/db" "$DIR/filestore" "$DIR/config" "$DIR/neon" "$DIR/.staging"
chmod 700 "$DIR" "$DIR/config"

log()  { printf '%s %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" | tee -a "$LOG"; }
fail() {
  log "FAILED: $*"
  osascript -e "display notification \"$*\" with title \"Marjaan backup FAILED\"" >/dev/null 2>&1 || true
  exit 1
}

# One run at a time — a slow night must not collide with the next one.
LOCK="$DIR/.lock"
if ! mkdir "$LOCK" 2>/dev/null; then
  # stale lock from a crashed run (>6h) is cleared, a live one is respected
  if [ -n "$(find "$LOCK" -maxdepth 0 -mmin +360 2>/dev/null)" ]; then rmdir "$LOCK"; mkdir "$LOCK"
  else fail "another backup is already running ($LOCK)"; fi
fi
REMOTE_STAGE=""
cleanup() {
  rmdir "$LOCK" 2>/dev/null || true
  [ -n "$REMOTE_STAGE" ] && ssh $SSH_OPTS "$HOST" "rm -rf '$REMOTE_STAGE'" >/dev/null 2>&1 || true
  rm -rf "$DIR/.staging/$STAMP"
}
trap cleanup EXIT

log "=== backup $STAMP start -> $DIR"

# ── 1. Database: dump + verify ON the server, then fetch ─────────────────────
REMOTE_STAGE="$(ssh $SSH_OPTS "$HOST" DB="$DB" bash -s <<'REMOTE'
set -euo pipefail
d="$(mktemp -d /var/tmp/marjaan-bk.XXXXXX)"; chmod 700 "$d"
sudo -u postgres pg_dump -Fc -Z 6 -d "$DB" > "$d/db.dump"
pg_restore -l "$d/db.dump" > /dev/null          # structurally complete, or fail here
sha256sum "$d/db.dump" | cut -d' ' -f1 > "$d/db.sha256"
{
  echo "taken_at_utc=$(date -u +%FT%TZ)"
  echo "host=$(hostname)"
  echo "pg_version=$(sudo -u postgres psql -Atc 'show server_version')"
  for t in product_template pos_order account_move stock_quant res_partner; do
    echo "rows_$t=$(sudo -u postgres psql -d "$DB" -Atc "select count(*) from $t")"
  done
  echo "odoo_addons_rev=$(sudo -u odoo git -C /opt/odoo/custom-addons/jewellery_evaluator rev-parse --short HEAD 2>/dev/null || echo n/a)"
} > "$d/manifest"
# Server-side config that is NOT in git (a rebuilt box needs all of it).
sudo tar -czf "$d/config.tgz" --ignore-failed-read -C / \
  etc/odoo.conf etc/systemd/system/odoo.service.d opt/odoo/ee-odoo-bin \
  opt/odoo/odoo-watchdog.sh etc/nginx/sites-available/odoo etc/logrotate.d \
  etc/revenax-pulse.env 2>/dev/null || true
[ -f "$d/config.tgz" ] && sudo chown "$(id -u):$(id -g)" "$d/config.tgz"
echo "$d"
REMOTE
)" || fail "remote dump step failed"
[ -n "$REMOTE_STAGE" ] || fail "remote dump returned no staging dir"

LOCAL_STAGE="$DIR/.staging/$STAMP"; mkdir -p "$LOCAL_STAGE"
rsync -a --partial -e "ssh $SSH_OPTS" "$HOST:$REMOTE_STAGE/" "$LOCAL_STAGE/" || fail "fetching the dump"

want="$(cat "$LOCAL_STAGE/db.sha256")"
got="$(shasum -a 256 "$LOCAL_STAGE/db.dump" | cut -d' ' -f1)"
[ "$want" = "$got" ] || fail "checksum mismatch after transfer ($want vs $got)"
head -c 5 "$LOCAL_STAGE/db.dump" | grep -q PGDMP || fail "dump header is not PGDMP"

mv "$LOCAL_STAGE/db.dump"     "$DIR/db/$DB-$STAMP.dump"
mv "$LOCAL_STAGE/db.sha256"   "$DIR/db/$DB-$STAMP.dump.sha256"
mv "$LOCAL_STAGE/manifest"    "$DIR/db/$DB-$STAMP.manifest"
if [ -f "$LOCAL_STAGE/config.tgz" ]; then
  mv "$LOCAL_STAGE/config.tgz" "$DIR/config/config-$STAMP.tgz"
  chmod 600 "$DIR/config/config-$STAMP.tgz"
else
  log "WARN server config snapshot missing this run"
fi
log "db: $(du -h "$DIR/db/$DB-$STAMP.dump" | cut -f1) verified (sha256 $got)"

# ── 2. Filestore: additive mirror (never --delete, see header) ───────────────
rsync -a --partial --stats -e "ssh $SSH_OPTS" --rsync-path="sudo rsync" \
  "$HOST:$FILESTORE/" "$DIR/filestore/" > "$DIR/.staging/rsync-$STAMP.txt" 2>&1 \
  || { cat "$DIR/.staging/rsync-$STAMP.txt" >> "$LOG"; fail "filestore rsync"; }
log "filestore: $(du -sh "$DIR/filestore" | cut -f1), $(find "$DIR/filestore" -type f | wc -l | tr -d ' ') files"
rm -f "$DIR/.staging/rsync-$STAMP.txt"

# ── 3. Optional: the ops-app database (Neon) ─────────────────────────────────
if [ -n "${NEON_DATABASE_URL:-}" ]; then
  if command -v pg_dump >/dev/null 2>&1; then
    pg_dump -Fc "$NEON_DATABASE_URL" -f "$DIR/neon/ops-$STAMP.dump" \
      && log "neon: $(du -h "$DIR/neon/ops-$STAMP.dump" | cut -f1)" \
      || log "WARN neon dump failed (Odoo backup still succeeded)"
    ls -1 "$DIR"/neon/ops-*.dump 2>/dev/null | sort -r | tail -n +"$((KEEP_DAILY+1))" | xargs rm -f 2>/dev/null || true
  else
    log "WARN NEON_DATABASE_URL set but no local pg_dump (brew install libpq)"
  fi
fi

# ── 4. Retention (bash 3.2-safe: macOS ships an old bash) ────────────────────
all="$(ls -1 "$DIR"/db/"$DB"-*.dump 2>/dev/null | sort)"
daily="$(printf '%s\n' "$all" | tail -n "$KEEP_DAILY")"
firsts=""; prev=""
for f in $all; do
  ym="$(basename "$f" | sed -E "s/^$DB-([0-9]{6}).*/\1/")"
  [ "$ym" != "$prev" ] && firsts="$firsts $f" && prev="$ym"
done
monthly="$(printf '%s\n' $firsts | tail -n "$KEEP_MONTHLY")"
pruned=0
for f in $all; do
  if ! printf '%s\n' "$daily" "$monthly" | grep -qxF "$f"; then
    rm -f "$f" "$f.sha256" "${f%.dump}.manifest"; pruned=$((pruned+1))
  fi
done
ls -1 "$DIR"/config/config-*.tgz 2>/dev/null | sort -r | tail -n +"$((KEEP_CONFIG+1))" | xargs rm -f 2>/dev/null || true

date '+%Y-%m-%d %H:%M:%S' > "$DIR/last-success"
log "=== backup $STAMP OK (dumps kept: $(ls -1 "$DIR"/db/*.dump | wc -l | tr -d ' '), pruned: $pruned)"

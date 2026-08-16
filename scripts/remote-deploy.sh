#!/bin/bash
# Runs on the EC2 host via SSH. Set GIT_REPO_PATH (repo dir on server). Optionally: ODOO_BIN, ODOO_PYTHON, ODOO_CONFIG.

set -euo pipefail

[ -n "${GIT_REPO_PATH:-}" ] || { echo "Error: GIT_REPO_PATH not set"; exit 1; }

MODULE_NAME="${MODULE_NAME:-jewellery_evaluator}"
if [[ ! "$MODULE_NAME" =~ ^[a-z0-9_]+$ ]]; then
  echo "Error: MODULE_NAME must contain only lowercase letters, numbers, and underscores"
  exit 1
fi

# Modules that live as normal subdirectories of the repo (space-separated).
# Unlike MODULE_NAME (the repo root itself), these are staged from $GIT_REPO_PATH/<name>.
SUBMODULES="${SUBMODULES:-jewellery_inventory_management}"

cd "$GIT_REPO_PATH" || exit 1
[ -d .git ] || { echo "Error: not a git repo. Clone into $GIT_REPO_PATH first."; exit 1; }

# --- Revenax Pulse -------------------------------------------------------
# A deploy stops and restarts Odoo, so it is worth announcing — especially when
# it FAILS, since the shop is then running the previous code (or nothing).
# Credentials come from /etc/revenax-pulse.env or the environment. Never allowed
# to affect the deploy: backgrounded, output discarded, always returns success.
[ -r /etc/revenax-pulse.env ] && . /etc/revenax-pulse.env
pulse() {  # pulse <topic> <title> <body> <idempotency-key>
  [ -n "${REVENAX_PULSE_SERVICE_NAME:-}" ] || return 0
  [ -n "${REVENAX_PULSE_API_KEY:-}" ] || return 0
  ( curl -s -o /dev/null --max-time 5 -X POST https://pulse.revenax.com/notify \
      -H "X-Service-Name: ${REVENAX_PULSE_SERVICE_NAME}" \
      -H "X-API-Key: ${REVENAX_PULSE_API_KEY}" \
      -H "Idempotency-Key: $4" \
      -H 'Content-Type: application/json' \
      --data "$(printf '{"topic":"%s","title":"%s","body":"%s","data":{"host":"%s","commit":"%s"}}' \
                "$1" "$2" "$3" "$(hostname)" "${DEPLOY_SHA:-unknown}")" || true ) >/dev/null 2>&1 &
}
# Announce a failure wherever the script exits non-zero, so no early `exit 1`
# can slip out silently.
_pulse_on_exit() {
  # Accepts the exit code as $1 because when chained after other commands in a
  # trap, $? is that command's status, not the script's.
  rc=${1:-$?}
  if [ "$rc" -ne 0 ]; then
    pulse deploy-failed "Deploy failed" \
      "remote-deploy.sh exited $rc on $(hostname). Odoo may be running the previous code." \
      "deploy-failed:${DEPLOY_SHA:-unknown}:${rc}"
    sleep 1   # give the backgrounded curl a moment before the shell dies
  fi
}
trap _pulse_on_exit EXIT

git fetch origin main
git pull --ff-only origin main || git rebase origin/main || { echo "Error: pull/rebase failed"; exit 1; }
DEPLOY_SHA=$(git rev-parse --short HEAD 2>/dev/null || echo unknown)
pulse deploy-started "Deploy started" \
  "Upgrading ${MODULE_NAME} to ${DEPLOY_SHA} on $(hostname)." \
  "deploy-started:${DEPLOY_SHA}"

# Stop Odoo so upgrade does not hit lock timeouts
STOP_TIMEOUT="${GRACEFUL_STOP_TIMEOUT:-60}"
sudo systemctl stop odoo || exit 1
deadline=$(($(date +%s) + STOP_TIMEOUT))
while systemctl is-active -q odoo 2>/dev/null && [ "$(date +%s)" -lt "$deadline" ]; do sleep 2; done

# Resolve Odoo command from systemd if not set
if [ -z "${ODOO_BIN:-}" ] || [ ! -x "$ODOO_BIN" ]; then
  # Use the EFFECTIVE ExecStart (the last one). `systemctl cat` prints the base
  # unit's ExecStart AND any drop-in override; a drop-in clears with `ExecStart=`
  # then sets the real one, so the last non-empty line is what actually runs.
  # Without `tail -1` we'd pick the base unit's (the old source odoo-bin), which
  # after the Enterprise cutover runs April core against the July DB and crashes.
  _line=$(systemctl cat odoo 2>/dev/null | sed -n 's/^ExecStart=//p' | grep -v '^$' | tail -1)
  ODOO_PYTHON="${ODOO_PYTHON:-$(echo "$_line" | tr ' ' '\n' | grep -E '^/.*/(python3?|python)$' | head -1)}"
  ODOO_BIN="${ODOO_BIN:-$(echo "$_line" | tr ' ' '\n' | grep -E '^/.*odoo-bin' | head -1)}"
  [ -z "$ODOO_BIN" ] && ODOO_BIN=$(echo "$_line" | tr ' ' '\n' | grep -E '^/.*odoo' | grep -v python | head -1)
fi
[ -n "$ODOO_BIN" ] && [ -x "$ODOO_BIN" ] || { echo "Error: ODOO_BIN not found. Set it or fix systemd unit."; sudo systemctl start odoo 2>/dev/null; exit 1; }

CONFIG="${ODOO_CONFIG:-/etc/odoo.conf}"

# Database to upgrade. CRITICAL: `odoo -u` needs a target database; without -d
# (and with no db_name in the config) it SILENTLY upgrades nothing — every
# data/XML change (cron records, report templates, views, security) is skipped
# and only Python reloads via the restart. Resolve from $ODOO_DB, else the
# config's db_name, defaulting to the known production DB. Override with ODOO_DB.
DB_NAME="${ODOO_DB:-$(awk -F= '/^[[:space:]]*db_name[[:space:]]*=/{gsub(/[[:space:]]/,"",$2); print $2; exit}' "$CONFIG")}"
[ -n "$DB_NAME" ] && [ "$DB_NAME" != "False" ] || DB_NAME="marjaan"

OUT=$(mktemp)
STAGE_ROOT=$(mktemp -d)
# Chains _pulse_on_exit: a bare `trap ... EXIT` REPLACES the handler set above,
# so without naming it here a mid-run failure would clean up silently and never
# report deploy-failed.
trap 'rc=$?; rm -rf "$STAGE_ROOT" "$OUT"; sudo systemctl start odoo 2>/dev/null; _pulse_on_exit "$rc"' EXIT

# Primary module: the repo root IS the jewellery_evaluator addon (see CLAUDE.md packaging).
ln -s "$GIT_REPO_PATH" "$STAGE_ROOT/$MODULE_NAME"
UPGRADE_MODULES="$MODULE_NAME"

# Additional modules live as subdirectories of the repo. Because the repo root is
# itself an addon, a nested subdir is NOT a top-level addon at runtime. The repo's
# parent dir is on the runtime addons path (that's how MODULE_NAME is found), so make
# each submodule a PERSISTENT sibling symlink there — this is what makes it visible to
# "Update Apps List"/install and at runtime, not just during this upgrade. Also stage it
# in STAGE_ROOT so the -u upgrade below sees it regardless of addons_path layout.
ADDONS_PARENT="$(dirname "$GIT_REPO_PATH")"
for sub in $SUBMODULES; do
  if [ -f "$GIT_REPO_PATH/$sub/__manifest__.py" ]; then
    ln -sfn "$GIT_REPO_PATH/$sub" "$ADDONS_PARENT/$sub"
    ln -s "$GIT_REPO_PATH/$sub" "$STAGE_ROOT/$sub"
    UPGRADE_MODULES="$UPGRADE_MODULES,$sub"
  else
    echo "Warning: submodule '$sub' has no __manifest__.py; skipping."
  fi
done

EXISTING_ADDONS_PATH=$(awk -F= '/^[[:space:]]*addons_path[[:space:]]*=/{sub(/^[[:space:]]+/, "", $2); sub(/[[:space:]]+$/, "", $2); print $2; exit}' "$CONFIG")
if [ -n "$EXISTING_ADDONS_PATH" ]; then
  ADDONS_PATH="$STAGE_ROOT,$EXISTING_ADDONS_PATH"
else
  ADDONS_PATH="$STAGE_ROOT"
fi

run_upgrade() {
  # NOTE: we deliberately do NOT pass --addons-path here. On the Enterprise box the
  # server runs the deb Odoo (via the ee-odoo-bin wrapper) whose config addons_path
  # already points at the enterprise addons (/opt/odoo-e/.../addons) + custom-addons.
  # Passing an explicit --addons-path re-introduced the OLD source core
  # (/opt/odoo/odoo/odoo/addons) into the odoo.addons namespace first, so core
  # modules (e.g. base_setup) loaded April code against the July DB and the upgrade
  # crashed. The custom modules are found via the config's custom-addons entry (the
  # repo checkout is /opt/odoo/custom-addons/jewellery_evaluator; submodules are the
  # persistent sibling symlinks created above), so the config path is sufficient.
  if [ -n "${ODOO_PYTHON:-}" ] && [ -x "$ODOO_PYTHON" ]; then
    sudo -u odoo "$ODOO_PYTHON" "$ODOO_BIN" -d "$DB_NAME" -u "$UPGRADE_MODULES" --stop-after-init -c "$CONFIG" "$@"
  else
    sudo -u odoo "$ODOO_BIN" -d "$DB_NAME" -u "$UPGRADE_MODULES" --stop-after-init -c "$CONFIG" "$@"
  fi
}
run_upgrade >"$OUT" 2>&1 || { cat "$OUT"; exit 1; }

trap _pulse_on_exit EXIT
sudo systemctl start odoo || exit 1
pulse deploy-finished "Deploy finished" \
  "${MODULE_NAME} upgraded to ${DEPLOY_SHA} and Odoo restarted." \
  "deploy-finished:${DEPLOY_SHA}"
echo "Deployment successful."

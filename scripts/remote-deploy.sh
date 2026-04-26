#!/bin/bash
# Runs on the EC2 host via SSH. Set GIT_REPO_PATH (repo dir on server). Optionally: ODOO_BIN, ODOO_PYTHON, ODOO_CONFIG.

set -euo pipefail

[ -n "${GIT_REPO_PATH:-}" ] || { echo "Error: GIT_REPO_PATH not set"; exit 1; }

MODULE_NAME="${MODULE_NAME:-jewellery_evaluator}"
if [[ ! "$MODULE_NAME" =~ ^[a-z0-9_]+$ ]]; then
  echo "Error: MODULE_NAME must contain only lowercase letters, numbers, and underscores"
  exit 1
fi

cd "$GIT_REPO_PATH" || exit 1
[ -d .git ] || { echo "Error: not a git repo. Clone into $GIT_REPO_PATH first."; exit 1; }

git fetch origin main
git pull --ff-only origin main || git rebase origin/main || { echo "Error: pull/rebase failed"; exit 1; }

# Stop Odoo so upgrade does not hit lock timeouts
STOP_TIMEOUT="${GRACEFUL_STOP_TIMEOUT:-60}"
sudo systemctl stop odoo || exit 1
deadline=$(($(date +%s) + STOP_TIMEOUT))
while systemctl is-active -q odoo 2>/dev/null && [ "$(date +%s)" -lt "$deadline" ]; do sleep 2; done

# Resolve Odoo command from systemd if not set
if [ -z "${ODOO_BIN:-}" ] || [ ! -x "$ODOO_BIN" ]; then
  _line=$(systemctl cat odoo 2>/dev/null | sed -n 's/^ExecStart=//p')
  ODOO_PYTHON="${ODOO_PYTHON:-$(echo "$_line" | tr ' ' '\n' | grep -E '^/.*/(python3?|python)$' | head -1)}"
  ODOO_BIN="${ODOO_BIN:-$(echo "$_line" | tr ' ' '\n' | grep -E '^/.*odoo-bin' | head -1)}"
  [ -z "$ODOO_BIN" ] && ODOO_BIN=$(echo "$_line" | tr ' ' '\n' | grep -E '^/.*odoo' | grep -v python | head -1)
fi
[ -n "$ODOO_BIN" ] && [ -x "$ODOO_BIN" ] || { echo "Error: ODOO_BIN not found. Set it or fix systemd unit."; sudo systemctl start odoo 2>/dev/null; exit 1; }

CONFIG="${ODOO_CONFIG:-/etc/odoo.conf}"
OUT=$(mktemp)
STAGE_ROOT=$(mktemp -d)
trap 'rm -rf "$STAGE_ROOT" "$OUT"; sudo systemctl start odoo 2>/dev/null' EXIT

ln -s "$GIT_REPO_PATH" "$STAGE_ROOT/$MODULE_NAME"

EXISTING_ADDONS_PATH=$(awk -F= '/^[[:space:]]*addons_path[[:space:]]*=/{sub(/^[[:space:]]+/, "", $2); sub(/[[:space:]]+$/, "", $2); print $2; exit}' "$CONFIG")
if [ -n "$EXISTING_ADDONS_PATH" ]; then
  ADDONS_PATH="$STAGE_ROOT,$EXISTING_ADDONS_PATH"
else
  ADDONS_PATH="$STAGE_ROOT"
fi

run_upgrade() {
  if [ -n "${ODOO_PYTHON:-}" ] && [ -x "$ODOO_PYTHON" ]; then
    sudo -u odoo "$ODOO_PYTHON" "$ODOO_BIN" -u "$MODULE_NAME" --stop-after-init -c "$CONFIG" --addons-path "$ADDONS_PATH" "$@"
  else
    sudo -u odoo "$ODOO_BIN" -u "$MODULE_NAME" --stop-after-init -c "$CONFIG" --addons-path "$ADDONS_PATH" "$@"
  fi
}
run_upgrade >"$OUT" 2>&1 || { cat "$OUT"; exit 1; }

trap - EXIT
sudo systemctl start odoo || exit 1
echo "Deployment successful."

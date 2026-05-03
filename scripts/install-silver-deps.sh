#!/usr/bin/env bash
# Install selenium + a Chromium browser into the Python interpreter Odoo uses.
# Chromedriver is fetched at runtime by Selenium Manager (built into selenium >= 4.6),
# so we don't need to install/maintain it separately.
#
# Usage:
#   sudo ./scripts/install-silver-deps.sh           # auto-detect Odoo python
#   sudo ODOO_PYTHON=/path/to/python install...     # explicit override

set -euo pipefail

log() { printf '\033[1;34m[silver-deps]\033[0m %s\n' "$*"; }
err() { printf '\033[1;31m[silver-deps]\033[0m %s\n' "$*" >&2; }

# ── 1. Find the Odoo Python ────────────────────────────────────────────────
detect_python() {
  if [ -n "${ODOO_PYTHON:-}" ] && [ -x "$ODOO_PYTHON" ]; then
    echo "$ODOO_PYTHON"; return
  fi
  # systemd unit (mirrors scripts/remote-deploy.sh)
  if command -v systemctl >/dev/null 2>&1; then
    local line
    line=$(systemctl cat odoo 2>/dev/null | sed -n 's/^ExecStart=//p' | head -1 || true)
    if [ -n "$line" ]; then
      local py
      py=$(echo "$line" | tr ' ' '\n' | grep -E '^/.*/(python3?|python)$' | head -1 || true)
      [ -n "$py" ] && [ -x "$py" ] && { echo "$py"; return; }
    fi
  fi
  # Common venv paths
  for p in \
    /opt/odoo/venv/bin/python /opt/odoo/.venv/bin/python \
    /home/odoo/venv/bin/python /home/odoo/.venv/bin/python \
    /usr/bin/python3 /usr/local/bin/python3; do
    [ -x "$p" ] && { echo "$p"; return; }
  done
  err "Could not locate Odoo's Python. Set ODOO_PYTHON=/path/to/python and retry."
  exit 1
}

PY="$(detect_python)"
log "Using Python: $PY ($($PY --version 2>&1))"

# ── 2. Pick a browser installer for this OS ────────────────────────────────
OS="$(uname -s)"
install_browser() {
  case "$OS" in
    Linux)
      if command -v google-chrome >/dev/null 2>&1; then
        log "google-chrome already installed: $(google-chrome --version)"
        return
      fi
      if command -v apt-get >/dev/null 2>&1; then
        # Prefer Google Chrome (.deb pulls in every shared lib it needs).
        # Ubuntu's "chromium" is a snap which fails to launch from systemd cron.
        log "Installing google-chrome-stable from official Google repo…"
        sudo apt-get update -qq
        sudo apt-get install -y --no-install-recommends ca-certificates curl gnupg
        sudo install -m 0755 -d /etc/apt/keyrings
        curl -fsSL https://dl.google.com/linux/linux_signing_key.pub \
          | sudo gpg --dearmor -o /etc/apt/keyrings/google-chrome.gpg
        echo "deb [arch=amd64 signed-by=/etc/apt/keyrings/google-chrome.gpg] https://dl.google.com/linux/chrome/deb/ stable main" \
          | sudo tee /etc/apt/sources.list.d/google-chrome.list >/dev/null
        sudo apt-get update -qq
        sudo apt-get install -y --no-install-recommends google-chrome-stable
        log "Installed: $(google-chrome --version)"
      elif command -v dnf >/dev/null 2>&1; then
        log "Installing google-chrome-stable via dnf…"
        sudo dnf install -y https://dl.google.com/linux/direct/google-chrome-stable_current_x86_64.rpm
      elif command -v yum >/dev/null 2>&1; then
        log "Installing google-chrome-stable via yum…"
        sudo yum install -y https://dl.google.com/linux/direct/google-chrome-stable_current_x86_64.rpm
      else
        err "No supported package manager (apt-get/dnf/yum). Install Google Chrome manually."
        exit 1
      fi
      ;;
    Darwin)
      if [ -d "/Applications/Google Chrome.app" ] || command -v chromium >/dev/null 2>&1; then
        log "Chrome/Chromium already installed."
        return
      fi
      if command -v brew >/dev/null 2>&1; then
        log "Installing google-chrome via Homebrew cask…"
        brew install --cask google-chrome
      else
        err "Homebrew not found. Install Chrome from https://www.google.com/chrome/"
        exit 1
      fi
      ;;
    *) err "Unsupported OS: $OS"; exit 1 ;;
  esac
}
install_browser

# ── 3. Install selenium into Odoo's Python ─────────────────────────────────
log "Installing selenium>=4.15 into $PY…"
if [ "$(id -u)" -eq 0 ] && id odoo >/dev/null 2>&1; then
  # System Odoo install: write into Odoo's site-packages as the odoo user
  sudo -u odoo "$PY" -m pip install --upgrade 'selenium>=4.15.0' \
    || "$PY" -m pip install --upgrade 'selenium>=4.15.0'
else
  "$PY" -m pip install --upgrade 'selenium>=4.15.0'
fi

# ── 4. Verify ──────────────────────────────────────────────────────────────
log "Verifying selenium import and Chromium binary…"
"$PY" - <<'PY'
import selenium, tempfile
print(f"selenium {selenium.__version__} OK")
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
opts = Options()
opts.add_argument("--headless=new")
opts.add_argument("--no-sandbox")
opts.add_argument("--disable-dev-shm-usage")
opts.add_argument("--disable-gpu")
opts.add_argument(f"--user-data-dir={tempfile.mkdtemp(prefix='chrome-smoke-')}")
opts.add_argument("--remote-debugging-pipe")
try:
    d = webdriver.Chrome(options=opts)  # Selenium Manager fetches chromedriver
    d.quit()
    print("Headless Chrome launched OK")
except Exception as e:
    print(f"WARN: Chrome smoke test failed: {e}")
    raise SystemExit(1)
PY

log "Done. Restart Odoo and run scheduled action 'Update Silver Prices' to scrape now."
log "  sudo systemctl restart odoo"

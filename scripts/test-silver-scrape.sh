#!/usr/bin/env bash
# Run the silver scrape standalone, mirroring what silver_price_service does.
# Proves whether selenium/chromedriver work in this environment, independent of Odoo.
#
# Usage:
#   ./scripts/test-silver-scrape.sh \
#     "https://dahabmasr.com/silver-price-today-en" \
#     "/html/body/div[3]/main/div[2]/div/div[2]/section/div/div[2]/div[1]/table/tbody/tr[1]/td[3]"
#
# Or run as the odoo user to match cron context:
#   sudo -u odoo ./scripts/test-silver-scrape.sh "<url>" "<xpath>"

set -euo pipefail

URL="${1:-https://dahabmasr.com/silver-price-today-en}"
XPATH="${2:-/html/body/div[3]/main/div[2]/div/div[2]/section/div/div[2]/div[1]/table/tbody/tr[1]/td[3]}"

# Detect Odoo's Python so we exercise the same selenium install
detect_python() {
  if [ -n "${ODOO_PYTHON:-}" ] && [ -x "$ODOO_PYTHON" ]; then echo "$ODOO_PYTHON"; return; fi
  if command -v systemctl >/dev/null 2>&1; then
    local line py
    line=$(systemctl cat odoo 2>/dev/null | sed -n 's/^ExecStart=//p' | head -1 || true)
    py=$(echo "$line" | tr ' ' '\n' | grep -E '^/.*/(python3?|python)$' | head -1 || true)
    [ -n "$py" ] && [ -x "$py" ] && { echo "$py"; return; }
  fi
  command -v python3 || { echo "no python found" >&2; exit 1; }
}
PY="$(detect_python)"
echo "[scrape-test] python: $PY"
echo "[scrape-test] url:    $URL"
echo "[scrape-test] xpath:  $XPATH"

URL="$URL" XPATH="$XPATH" "$PY" - <<'PY'
import os, re, sys, tempfile, traceback
URL = os.environ["URL"]
XPATH = os.environ["XPATH"]
try:
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
except ImportError as e:
    print(f"FAIL: selenium not importable for {sys.executable}: {e}")
    sys.exit(2)

opts = Options()
for a in (
    "--headless=new", "--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu",
    f"--user-data-dir={tempfile.mkdtemp(prefix='chrome-test-')}",
    "--remote-debugging-pipe",
    "--disable-extensions", "--disable-plugins", "--disable-sync",
    "--disable-translate", "--disable-background-networking",
    "--no-first-run", "--log-level=3",
):
    opts.add_argument(a)

try:
    driver = webdriver.Chrome(options=opts)
except Exception as e:
    print("FAIL: could not start Chrome.")
    traceback.print_exc()
    sys.exit(3)

try:
    driver.implicitly_wait(10)
    driver.get(URL)
    def ready(d):
        el = d.find_element(By.XPATH, XPATH)
        t = (el.text or "").strip()
        return el if t and t != "--" else False
    el = WebDriverWait(driver, 30).until(ready)
    text = el.text.strip()
    print(f"[scrape-test] cell text: {text!r}")
    m = re.search(r"\d+(?:\.\d+)?", text.replace(",", ""))
    if not m:
        print("FAIL: no number in cell text"); sys.exit(4)
    print(f"OK: silver 999 = {float(m.group(0))} per gram")
except Exception:
    print("FAIL: scrape error")
    traceback.print_exc()
    sys.exit(5)
finally:
    driver.quit()
PY

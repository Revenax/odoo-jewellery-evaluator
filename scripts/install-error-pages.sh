#!/usr/bin/env bash
# -*- coding: utf-8 -*-
# Copyright 2026 Revenax Digital Services
# Author: Mohamed A. Abdallah
# Website: https://www.revenax.com
#
# Install the Revenax-branded nginx error pages (500/502/503/504) on the Odoo box.
# Server-side, NOT part of the deploy: re-run if the box or nginx is rebuilt.
#
#   scripts/install-error-pages.sh                       # from your Mac (copies + installs over SSH)
#
# The pages are shown when nginx itself produces the error (Odoo down = 502,
# Odoo too slow = 504). Odoo's own error responses pass through untouched
# (no proxy_intercept_errors), so RPC/JSON errors keep working.
set -euo pipefail
cd "$(dirname "$0")/.."
KEY="${MARJAAN_PEM:-$HOME/Documents/Marjaan/marjaan-odoo-19.pem}"
HOST="${MARJAAN_HOST:-ubuntu@odoo.marjaanjewellery.com}"
SITE="${NGINX_SITE:-/etc/nginx/sites-available/odoo}"

python3 nginx/error-pages/build.py >/dev/null
scp -q -i "$KEY" nginx/error-pages/html/*.html "$HOST:/tmp/"

ssh -i "$KEY" "$HOST" "sudo bash -s" -- "$SITE" <<'REMOTE'
set -euo pipefail
SITE="$1"
DIR=/var/www/revenax-errors
SNIP=/etc/nginx/snippets/revenax-error-pages.conf
mkdir -p "$DIR"
for c in 500 502 503 504; do install -m 0644 "/tmp/$c.html" "$DIR/$c.html"; rm -f "/tmp/$c.html"; done

cat > "$SNIP" <<'EOF'
# Revenax-branded error pages (scripts/install-error-pages.sh in odoo-gold-pricing-engine).
error_page 500 /__errors/500.html;
error_page 502 /__errors/502.html;
error_page 503 /__errors/503.html;
error_page 504 /__errors/504.html;
location ^~ /__errors/ {
    internal;
    alias /var/www/revenax-errors/;
    add_header Cache-Control "no-store" always;
}
EOF

if grep -q 'snippets/revenax-error-pages.conf' "$SITE"; then
    echo "include already present in $SITE"
else
    BAK="$SITE.bak-$(date +%Y%m%d-%H%M%S)"
    cp -a "$SITE" "$BAK"
    # First server block only (the 443 one); the port-80 block only redirects.
    awk '!done && /error_log/ { print; print "    include snippets/revenax-error-pages.conf;"; done=1; next } { print }' "$BAK" > "$SITE"
    if ! nginx -t 2>/dev/null; then
        cp -a "$BAK" "$SITE"; nginx -t; echo "nginx -t failed, restored $BAK" >&2; exit 1
    fi
    echo "added include to $SITE (backup $BAK)"
fi
nginx -t
systemctl reload nginx
echo "installed: $(ls $DIR)"
REMOTE

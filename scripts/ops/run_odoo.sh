#!/usr/bin/env bash
# -*- coding: utf-8 -*-
# Copyright 2026 Revenax Digital Services
# Author: Mohamed A. Abdallah
#
# Run a Python script inside the PRODUCTION Odoo shell (database `marjaan`).
#
#   scripts/ops/run_odoo.sh scripts/ops/hard_delete.py SKUS=GRF8-0124          # dry run
#   scripts/ops/run_odoo.sh scripts/ops/hard_delete.py SKUS=GRF8-0124 COMMIT=1 # apply
#
# Every script in scripts/ops rolls back unless COMMIT=1. Always dry-run first.
set -euo pipefail
SCRIPT="$1"; shift
KEY="${MARJAAN_PEM:-$HOME/Documents/Marjaan/marjaan-odoo-19.pem}"
HOST="${MARJAAN_HOST:-ubuntu@odoo.marjaanjewellery.com}"
NAME="ops_$(basename "$SCRIPT")"
scp -q -i "$KEY" "$SCRIPT" "$HOST:/tmp/$NAME"
# KEY=VALUE args become env vars for the shell (values must not contain spaces or quotes).
ENVS="$*"
ssh -i "$KEY" "$HOST" "sudo cp /tmp/$NAME /opt/odoo/tmp/$NAME && sudo -u odoo env $ENVS bash -c '/opt/odoo/ee-odoo-bin shell -c /etc/odoo.conf -d marjaan --no-http < /opt/odoo/tmp/$NAME' 2>&1 | grep -v -E ' INFO | WARNING '"

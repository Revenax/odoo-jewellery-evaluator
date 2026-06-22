#!/bin/bash
# CI: lint, test, type-check. Run locally or via GitHub Actions.

set -euo pipefail

cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

for cmd in ruff pytest mypy; do
  command -v "$cmd" &>/dev/null || { echo "Error: $cmd not found. pip install -r requirements-dev.txt"; exit 1; }
done

ruff check jewellery_evaluator/ jewellery_inventory_management/ tests/
pytest tests/ -v
mypy jewellery_evaluator/utils.py --ignore-missing-imports

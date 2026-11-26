#!/usr/bin/env bash
# Linux/macOS setup: venv + deps + .env template.
# (The 8 employee kits are already committed under ./employees; to re-hire them from the
#  official installer instead, run:  bash hire_employees.sh)
set -euo pipefail
python3 -m venv venv
./venv/bin/pip install -r requirements.txt
[ -f .env ] || { cp .env.example .env; echo "Created .env - fill in your values."; }
echo "Try: ./venv/bin/python bridge/run_daily.py --demo --dry-run"

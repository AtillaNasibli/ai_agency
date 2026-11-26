#!/usr/bin/env bash
cd "$(dirname "$0")"
[ -d venv ] || python3 -m venv venv
./venv/bin/pip install -q -r requirements.txt
./venv/bin/pip install -q -r requirements-litellm.txt || echo "LiteLLM skipped, using built-in HTTP path."
[ -f .env ] || { cp .env.example .env; echo "Created .env - fill in SMTP/SHEET values."; }
./venv/bin/python app.py

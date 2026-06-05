#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────
#  J.A.R.V.I.S. launcher — sets up a venv, installs deps, starts the terminal.
# ──────────────────────────────────────────────────────────────────────────
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -d .venv ]; then
  echo "▸ creating virtualenv…"
  python3 -m venv .venv
  ./.venv/bin/pip install -q --upgrade pip setuptools wheel
fi

echo "▸ installing dependencies…"
./.venv/bin/pip install -q -r requirements.txt

if [ ! -f .env ] && [ -z "${DEEPSEEK_API_KEY:-}" ]; then
  echo "▸ no .env found — copying .env.example (AI core will run OFFLINE until you add a key)"
  cp -n .env.example .env || true
fi

echo "▸ launching J.A.R.V.I.S. …"
exec ./.venv/bin/python app.py

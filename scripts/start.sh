#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

if [ ! -x .venv/bin/python ] || [ ! -f dist/index.html ] || [ ! -f data/uzex.duckdb ]; then
  echo 'Run bash scripts/install.sh first; original CSV files must be in data/raw.' >&2
  exit 1
fi
exec .venv/bin/python -m uvicorn server.app:app --host "${UZEX_HOST:-0.0.0.0}" --port "${UZEX_PORT:-${PORT:-8000}}"

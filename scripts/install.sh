#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

if [ ! -x .venv/bin/python ]; then
  python -m venv .venv
fi
.venv/bin/python -m pip install --disable-pip-version-check -r requirements.lock.txt
npm ci --no-audit --no-fund
.venv/bin/python -m server.import_data
npm run build

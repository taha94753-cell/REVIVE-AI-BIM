#!/usr/bin/env bash
# REVIVE first-time setup for macOS / Linux. Safe to run again: it repairs a broken setup.
set -e
cd "$(dirname "$0")"
PY=""
for c in python3.12 python3.13 python3.14 python3.11 python3; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(0 if (3,11) <= sys.version_info[:2] <= (3,14) else 1)'; then PY="$c"; break; fi
done
if [ -z "$PY" ]; then echo "No Python 3.11-3.14 found (3.12 recommended). Install it (python.org or your package manager) and run again."; exit 1; fi
echo "Using $($PY --version) ($PY)"
if [ -x .venv/bin/python ] && ! .venv/bin/python -c 'import sys; sys.exit(0 if (3,11) <= sys.version_info[:2] <= (3,14) else 1)' >/dev/null 2>&1; then
  echo "The existing .venv is broken; rebuilding it."; rm -rf .venv
fi
[ -x .venv/bin/python ] || "$PY" -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements-lock.txt || .venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m revive setup
.venv/bin/python -m revive doctor || true
echo "Setup complete. Start with ./run.sh"

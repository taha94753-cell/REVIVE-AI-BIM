#!/usr/bin/env bash
# Start REVIVE. Runs setup first if the environment is missing or broken.
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python ] || ! .venv/bin/python -c 'import fastapi, uvicorn, xgboost, shap, ifcopenshell, pulp, segno' >/dev/null 2>&1; then
  echo "Environment missing or incomplete: running setup first."
  ./setup.sh || exit 1
fi
exec .venv/bin/python -m revive serve --open "$@"

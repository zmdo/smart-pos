#!/bin/bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
export PYTHONUTF8=1
CASE_PYTHON=${CASE_PYTHON:-/root/apps/non-grid-calibration/.venv/bin/python}
exec "$CASE_PYTHON" -m unittest discover -s scripts/body_scan/tests -t . -v

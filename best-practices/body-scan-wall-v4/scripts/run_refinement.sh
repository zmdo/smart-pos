#!/bin/bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
unset PYTHONPATH
export PYTHONUTF8=1
export OMP_NUM_THREADS=${OMP_NUM_THREADS:-4}
CASE_PYTHON=${CASE_PYTHON:-/root/apps/non-grid-calibration/.venv/bin/python}
exec "$CASE_PYTHON" -u -m scripts.body_scan_approved "$@"

#!/bin/bash
set -euo pipefail
CASE_DELIVERY_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
unset PYTHONPATH
export PYTHONNOUSERSITE=1 PYTHONUTF8=1
CASE_PYTHON=${CASE_PYTHON:-/root/apps/non-grid-calibration/.venv/bin/python}
exec "$CASE_PYTHON" -u "$CASE_DELIVERY_ROOT/launch.py" "$@"

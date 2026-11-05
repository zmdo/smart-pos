#!/bin/bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
export PYTHONUTF8=1
export OMP_NUM_THREADS=${OMP_NUM_THREADS:-4}
CASE_CAMERA_PYTHON=${CASE_CAMERA_PYTHON:-/root/apps/non-grid-calibration/.venv/bin/python}
exec "$CASE_CAMERA_PYTHON" -u -m scripts.non_grid_camera "$@"

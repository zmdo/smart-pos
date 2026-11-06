#!/bin/bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
unset PYTHONPATH
export PYTHONNOUSERSITE=1
CASE_PYTHON=${CASE_PYTHON:-/root/apps/non-grid-calibration/.venv/bin/python}
"$CASE_PYTHON" -m unittest discover -s scripts/body_scan_contracts/tests
"$CASE_PYTHON" -m unittest discover -s scripts/body_scan_phase_classification/tests

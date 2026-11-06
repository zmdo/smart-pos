#!/bin/bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
unset PYTHONPATH
export PYTHONUTF8=1
CASE_PYTHON=${CASE_PYTHON:-/root/apps/non-grid-calibration/.venv/bin/python}
"$CASE_PYTHON" verify_snapshot.py
"$CASE_PYTHON" -m unittest discover -s scripts/body_scan_person_scale/tests -v
"$CASE_PYTHON" -m unittest discover -s scripts/body_scan_group_display/tests -v

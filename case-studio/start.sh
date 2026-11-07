#!/bin/bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
export PYTHONUTF8=1 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
CASE_PYTHON=${CASE_PYTHON:-/root/apps/non-grid-calibration/.venv/bin/python}
exec "$CASE_PYTHON" -m uvicorn app:app --host 0.0.0.0 --port "${PORT:-6008}" --workers 1 --proxy-headers --forwarded-allow-ips='*'

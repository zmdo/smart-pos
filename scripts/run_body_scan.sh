#!/bin/bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
CASE_PYTHON=${CASE_PYTHON:-/root/apps/portrait-studio/.venv/bin/python}
exec "$CASE_PYTHON" -u -m scripts.body_scan "$@"

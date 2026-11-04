#!/bin/bash
set -euo pipefail
cd /root/apps/case-studio
JOB=${CASE_JOB:-/root/autodl-fs/case-studio/batches/287a8a82df2f2fca2c22299b/job.json}
OUT=${CASE_GRID_OUT:-/root/autodl-fs/case-studio/experiments/grid-single-$(date +%Y%m%d-%H%M%S)-$$}
# Twelve singles (including recovered detections) + two comparison skip controls.
if [ "$#" -eq 0 ]; then
  set -- a0005 a0008 a0009 a0015 a0025 a0070 a0072 a0079 a0090 a0091 a0093 a0094 a0018 a0180
fi
/root/apps/portrait-studio/.venv/bin/python -u tools/grid_rectify_single.py \
  --job "$JOB" --asset-id "$@" --out "$OUT"
printf 'Results: %s\n' "$OUT"

#!/bin/bash
set -euo pipefail
cd /root/apps/case-studio
JOB=${CASE_JOB:-/root/autodl-fs/case-studio/batches/287a8a82df2f2fca2c22299b/job.json}
OUT=${CASE_GRID_OUT:-/root/autodl-fs/case-studio/experiments/grid-single-$(date +%Y%m%d-%H%M%S)-$$}
# Four singles + two comparisons to verify skipping. Arguments override sample IDs.
if [ "$#" -eq 0 ]; then set -- a0005 a0015 a0093 a0094 a0018 a0180; fi
/root/apps/portrait-studio/.venv/bin/python -u tools/grid_rectify_single.py \
  --job "$JOB" --asset-id "$@" --out "$OUT"
printf 'Results: %s\n' "$OUT"

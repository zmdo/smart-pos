#!/bin/bash
set -euo pipefail
cd /root/apps/case-studio
INPUT=${CASE_SHOULDER_INPUT:-/root/autodl-fs/case-studio/experiments/grid-single-v2-20261105/grid-crop-v23-verified}
PREVIOUS=${CASE_SHOULDER_PREVIOUS:-/root/autodl-fs/case-studio/experiments/grid-single-v2-20261105/grid-standard-frame-v1-768x1280}
JOB=${CASE_JOB:-/root/autodl-fs/case-studio/batches/287a8a82df2f2fca2c22299b/job.json}
OUT=${CASE_SHOULDER_OUT:-/root/autodl-fs/case-studio/experiments/grid-shoulder-frame-$(date +%Y%m%d-%H%M%S)-$$}
/root/apps/portrait-studio/.venv/bin/python -u tools/grid_shoulder_frame.py \
  --input "$INPUT" --job "$JOB" --previous-standard "$PREVIOUS" --out "$OUT" "$@"
printf 'Results: %s\n' "$OUT"

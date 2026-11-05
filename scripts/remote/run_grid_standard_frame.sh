#!/bin/bash
set -euo pipefail
cd /root/apps/case-studio
INPUT=${CASE_FRAME_INPUT:-/root/autodl-fs/case-studio/experiments/grid-single-v2-20261105/grid-crop-v23-verified}
OUT=${CASE_FRAME_OUT:-/root/autodl-fs/case-studio/experiments/grid-standard-frame-$(date +%Y%m%d-%H%M%S)-$$}
/root/apps/portrait-studio/.venv/bin/python -u tools/grid_standard_frame.py \
  --input "$INPUT" --out "$OUT" \
  --width "${CASE_FRAME_WIDTH:-768}" --height "${CASE_FRAME_HEIGHT:-1280}" "$@"
printf 'Results: %s\n' "$OUT"

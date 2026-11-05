#!/bin/bash
set -euo pipefail
cd /root/apps/case-studio
PREVIOUS=${CASE_TALL_PREVIOUS:-/root/autodl-fs/case-studio/experiments/grid-single-v2-20261105/grid-shoulder-frame-v1-verified}
RECTIFIED=${CASE_TALL_RECTIFIED:-/root/autodl-fs/case-studio/experiments/grid-single-v2-20261105/grid-crop-v23-verified}
OUT=${CASE_TALL_OUT:-/root/autodl-fs/case-studio/experiments/grid-shoulder-tall-$(date +%Y%m%d-%H%M%S)-$$}
/root/apps/portrait-studio/.venv/bin/python -u tools/grid_shoulder_frame_tall.py \
  --previous "$PREVIOUS" --rectified "$RECTIFIED" --out "$OUT" "$@"
printf 'Results: %s\n' "$OUT"

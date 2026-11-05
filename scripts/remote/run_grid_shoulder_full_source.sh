#!/bin/bash
set -euo pipefail
cd /root/apps/case-studio
PREVIOUS=${CASE_FULL_SOURCE_PREVIOUS:-/root/autodl-fs/case-studio/experiments/grid-single-v2-20261105/grid-shoulder-uniform-v3-verified}
RECTIFIED=${CASE_FULL_SOURCE_RECTIFIED:-/root/autodl-fs/case-studio/experiments/grid-single-v2-20261105/grid-crop-v23-verified}
OUT=${CASE_FULL_SOURCE_OUT:-/root/autodl-fs/case-studio/experiments/grid-shoulder-full-source-$(date +%Y%m%d-%H%M%S)-$$}
/root/apps/portrait-studio/.venv/bin/python -u tools/grid_shoulder_frame_full_source.py \
  --previous "$PREVIOUS" --rectified "$RECTIFIED" --out "$OUT" "$@"
printf 'Results: %s\n' "$OUT"

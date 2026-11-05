#!/bin/bash
set -euo pipefail
cd /root/apps/case-studio
POSES=${CASE_UNIFORM_POSES:-/root/autodl-fs/case-studio/experiments/grid-single-v2-20261105/grid-shoulder-frame-v1-verified}
RECTIFIED=${CASE_UNIFORM_RECTIFIED:-/root/autodl-fs/case-studio/experiments/grid-single-v2-20261105/grid-crop-v23-verified}
PREVIOUS=${CASE_UNIFORM_PREVIOUS:-/root/autodl-fs/case-studio/experiments/grid-single-v2-20261105/grid-shoulder-tall-v2-verified}
OUT=${CASE_UNIFORM_OUT:-/root/autodl-fs/case-studio/experiments/grid-shoulder-uniform-$(date +%Y%m%d-%H%M%S)-$$}
/root/apps/portrait-studio/.venv/bin/python -u tools/grid_shoulder_frame_uniform.py \
  --poses "$POSES" --rectified "$RECTIFIED" --previous "$PREVIOUS" --out "$OUT" "$@"
printf 'Results: %s\n' "$OUT"

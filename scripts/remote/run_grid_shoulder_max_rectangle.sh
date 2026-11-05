#!/bin/bash
set -euo pipefail
cd /root/apps/case-studio
PREVIOUS=${CASE_MAX_RECT_PREVIOUS:-/root/autodl-fs/case-studio/experiments/grid-single-v2-20261105/grid-shoulder-full-source-v4-verified}
OUT=${CASE_MAX_RECT_OUT:-/root/autodl-fs/case-studio/experiments/grid-shoulder-max-rectangle-$(date +%Y%m%d-%H%M%S)-$$}
/root/apps/portrait-studio/.venv/bin/python -u tools/grid_shoulder_frame_max_rectangle.py \
  --previous "$PREVIOUS" --out "$OUT" "$@"
printf 'Results: %s\n' "$OUT"

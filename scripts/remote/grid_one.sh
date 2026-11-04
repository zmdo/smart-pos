#!/bin/bash
set -uo pipefail
cd /root/apps/case-studio
B=/root/autodl-fs/case-studio/batches/287a8a82df2f2fca2c22299b/input/私教会员案例项目
/root/apps/portrait-studio/.venv/bin/python tools/grid_rectify.py \
  --src "$B/景田店/董彦琦/30d3021690de42a92336410c18745261_compress.jpg" \
  --out /tmp/grid/dong_side 2>&1 | tail -25

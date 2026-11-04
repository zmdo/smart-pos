#!/bin/bash
set -uo pipefail
cd /root/apps/case-studio
rm -rf /tmp/v8b && mkdir -p /tmp/v8b
/root/apps/portrait-studio/.venv/bin/python tools/standardize_pair_v8.py \
  --src "/root/autodl-fs/case-studio/batches/287a8a82df2f2fca2c22299b/input/私教会员案例项目/景田店/董彦琦/30d3021690de42a92336410c18745261_compress.jpg" \
  --out /tmp/v8b --no-vlm 2>&1 | tail -30
ls -la /tmp/v8b

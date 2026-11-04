#!/bin/bash
set -uo pipefail
cd /root/apps/case-studio
B=/root/autodl-fs/case-studio/batches/287a8a82df2f2fca2c22299b/input/私教会员案例项目
V=/root/apps/portrait-studio/.venv/bin/python
rm -rf /tmp/final && mkdir -p /tmp/final

run() {
  local rel="$1" name="$2"
  "$V" tools/standardize_pair_v7.py --src "$B/$rel" --out "/tmp/final/$name" --no-vlm 2>&1 | tail -2
}

run "景田店/董彦琦/30d3021690de42a92336410c18745261_compress.jpg" "dong_side"
run "景田店/董彦琦/8dec5a34fc8e82e7b14984bc44c19abb_compress.jpg"   "dong_front"
run "宝安店/任胜男-candy/4333be434f4b55425495ee1860774d38(1).jpg"    "ren_front"
ls -la /tmp/final

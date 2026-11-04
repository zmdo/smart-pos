#!/bin/bash
set -uo pipefail
cd /root/apps/case-studio
B=/root/autodl-fs/case-studio/batches/287a8a82df2f2fca2c22299b/input/私教会员案例项目
V=/root/apps/portrait-studio/.venv/bin/python
rm -rf /tmp/v8 && mkdir -p /tmp/v8

run() {
  "$V" tools/standardize_pair_v8.py --src "$B/$1" --out "/tmp/v8/$2" --no-vlm 2>&1 | tail -4
}

run "景田店/董彦琦/30d3021690de42a92336410c18745261_compress.jpg" "dong_side"
run "景田店/董彦琦/8dec5a34fc8e82e7b14984bc44c19abb_compress.jpg"   "dong_front"
run "宝安店/任胜男-candy/4333be434f4b55425495ee1860774d38(1).jpg"    "ren_front"
ls -la /tmp/v8

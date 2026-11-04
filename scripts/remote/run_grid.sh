#!/bin/bash
set -uo pipefail
cd /root/apps/case-studio
B=/root/autodl-fs/case-studio/batches/287a8a82df2f2fca2c22299b/input/私教会员案例项目
V=/root/apps/portrait-studio/.venv/bin/python
rm -rf /tmp/grid && mkdir -p /tmp/grid

run() {
  echo "=== $2 ==="
  "$V" tools/grid_rectify.py --src "$B/$1" --out "/tmp/grid/$2" 2>&1 | tail -30
}

run "景田店/董彦琦/30d3021690de42a92336410c18745261_compress.jpg" "dong_side"
run "景田店/关文博/$(ls "$B/景田店/关文博" | head -1)" "guan_1"
run "宝安店/任胜男-candy/4333be434f4b55425495ee1860774d38(1).jpg" "ren_front"
ls /tmp/grid

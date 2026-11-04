#!/bin/bash
set -uo pipefail
SRC="/root/autodl-fs/case-studio/batches/287a8a82df2f2fca2c22299b/input/私教会员案例项目/参考模板/宝安店-曾繁治（输出成品）"
rm -rf /tmp/tpl && mkdir -p /tmp/tpl
i=0
while IFS= read -r f; do
  i=$((i+1))
  cp "$f" "/tmp/tpl/t$i.jpg"
  echo "t$i <= $(basename "$f")"
  [ "$i" -ge 6 ] && break
done < <(find "$SRC" -maxdepth 1 -name '*.jpg' | sort)
ls -la /tmp/tpl

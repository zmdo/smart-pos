#!/bin/bash
set -uo pipefail
SRC=/root/autodl-fs/qa/pexels
STAGE=/root/autodl-fs/qa/stage
rm -rf "$STAGE"; mkdir -p "$STAGE/组A-人像" "$STAGE/组B-街拍" "$STAGE/组B-街拍/子目录"
i=0
for f in "$SRC"/*.jpg; do
  i=$((i+1))
  if [ $((i % 2)) -eq 0 ]; then
    cp "$f" "$STAGE/组A-人像/$(printf 'a%02d.jpg' $i)"
  else
    cp "$f" "$STAGE/组B-街拍/$(printf 'b%02d.jpg' $i)"
  fi
done
# no-person image must be skipped
cp /root/autodl-fs/portrait-studio/jobs/3ed065998c7dd3c2bab4f1aa/input/人物测试/no-person.png "$STAGE/组B-街拍/" 2>/dev/null || true
# a non-image file must be ignored
echo "not an image" > "$STAGE/组B-街拍/说明.txt"
cd "$STAGE" && rm -f /root/autodl-fs/qa/pexels-test.zip && zip -qr /root/autodl-fs/qa/pexels-test.zip .
ls -la /root/autodl-fs/qa/pexels-test.zip
unzip -l /root/autodl-fs/qa/pexels-test.zip | tail -5

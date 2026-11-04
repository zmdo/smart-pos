#!/bin/bash
set -uo pipefail
WORK=/root/autodl-fs/qa/sample
RAW="$WORK/raw"
mkdir -p "$WORK" "$RAW"

ok=0
for i in $(seq 1 120); do
  id=$(printf '%012d' "$i")
  url="http://images.cocodataset.org/val2017/$id.jpg"
  code=$(curl -s -m 15 -o "$RAW/$id.jpg" -w '%{http_code}' "$url")
  if [ "$code" = "200" ] && [ -s "$RAW/$id.jpg" ]; then
    ok=$((ok+1))
  else
    rm -f "$RAW/$id.jpg"
  fi
done
echo "downloaded ok: $ok"
ls "$RAW" | wc -l

cd /root/apps/portrait-studio
.venv/bin/python /root/autodl-fs/qa/sample/pick_people.py

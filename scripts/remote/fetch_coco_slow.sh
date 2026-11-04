#!/bin/bash
set -uo pipefail
# Slow, polite probe: find valid COCO val2017 ids and keep images that contain people.
WORK=/root/autodl-fs/qa/sample
RAW="$WORK/raw"
mkdir -p "$RAW"

curl -s -m 15 -o "$RAW/check.jpg" -w 'probe %{http_code}\n' "http://images.cocodataset.org/val2017/000000000285.jpg"
sleep 1

ok=0
for i in $(seq 1 400); do
  id=$(printf '%012d' "$i")
  [ -f "$RAW/$id.jpg" ] && continue
  code=$(curl -s -m 12 -o "$RAW/$id.jpg" -w '%{http_code}' "http://images.cocodataset.org/val2017/$id.jpg")
  if [ "$code" = "200" ] && [ -s "$RAW/$id.jpg" ]; then
    ok=$((ok+1))
  else
    rm -f "$RAW/$id.jpg"
  fi
  if [ $((i % 25)) -eq 0 ]; then echo "scanned $i ok=$ok"; fi
  sleep 1.2
done
echo "TOTAL ok=$ok"
ls "$RAW" | wc -l

#!/bin/bash
set -uo pipefail
for u in http://images.cocodataset.org/val2017/000000000139.jpg https://images.cocodataset.org/val2017/000000000139.jpg https://huggingface.co https://hf-mirror.com; do
  printf '%s -> ' "$u"
  timeout 15 curl -s -o /dev/null -w '%{http_code} %{size_download}\n' "$u" || echo FAIL
done
echo '--- try a few coco ids ---'
mkdir -p /tmp/coco && cd /tmp/coco
for id in 000000000139 000000000285 000000000632 000000000724 000000000776; do
  timeout 20 curl -s -o "$id.jpg" -w "$id %{http_code} %{size_download}\n" "http://images.cocodataset.org/val2017/$id.jpg" || echo "fail $id"
done
ls -la /tmp/coco | head

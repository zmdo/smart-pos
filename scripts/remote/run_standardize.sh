#!/bin/bash
set -uo pipefail
V=/root/apps/portrait-studio/.venv/bin
B=/root/autodl-fs/case-studio/batches/287a8a82df2f2fca2c22299b
OUT=/tmp/std
rm -rf "$OUT"; mkdir -p "$OUT"
export HF_ENDPOINT=https://hf-mirror.com

# 挑 3 张"前后同框"的体测图（生产目录）
"$V/python" - <<'PY' > /tmp/std/pick.txt
import json
from pathlib import Path
base = Path('/root/autodl-fs/case-studio/batches/287a8a82df2f2fca2c22299b')
job = json.loads((base / 'job.json').read_text())
picked = []
for a in job['assets']:
    if a.get('split') and not a['store'].startswith('（') and len(picked) < 3:
        picked.append((a['id'], a['member'], a['class']['view'], a['path']))
for p in picked:
    print('\t'.join(map(str, p)))
PY
cat /tmp/std/pick.txt

while IFS=$'\t' read -r id member view path; do
  name="${id}_${member}_${view}"
  echo "=== $name ==="
  cd /root/apps/case-studio
  "$V/python" tools/standardize_pair.py --src "$B/input/$path" --out "$OUT/$name" --canvas 1080x1440 2>&1 | tail -12
done < /tmp/std/pick.txt
ls -R "$OUT" | head -30

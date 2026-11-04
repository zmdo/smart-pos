#!/bin/bash
set -uo pipefail
B=/root/autodl-fs/case-studio/batches
ID=$(ls -t $B | head -1)
echo "batch $ID"
# 找几张被丢弃的素材缩略图拷出来
/root/apps/portrait-studio/.venv/bin/python - "$ID" <<'PY'
import json, sys, shutil
from pathlib import Path
bid = sys.argv[1]
base = Path('/root/autodl-fs/case-studio/batches') / bid
job = json.loads((base / 'job.json').read_text())
picked = 0
out = Path('/tmp/dropped')
out.mkdir(exist_ok=True)
for a in job.get('assets', []):
    q = a.get('quality') or {}
    if q.get('drop_reasons') and a.get('thumb') and picked < 6:
        src = base / 'work' / a['thumb']
        if src.exists():
            shutil.copy(src, out / f"{a['id']}.jpg")
            print(a['id'], q['drop_reasons'], 'sharp', q.get('sharpness'), '->', out / f"{a['id']}.jpg")
            picked += 1
PY
ls -la /tmp/dropped

#!/bin/bash
set -uo pipefail
cd /tmp
curl -s -b cj.txt http://127.0.0.1:6008/api/batches -o list2.json
ID=$(/root/apps/portrait-studio/.venv/bin/python -c "import json;print(json.load(open('list2.json'))[0]['id'])")
echo "batch=$ID"
rm -rf /tmp/thumbs && mkdir -p /tmp/thumbs
/root/apps/portrait-studio/.venv/bin/python - "$ID" > /tmp/thumbs/ids.txt <<'PY'
import json, sys
bid = sys.argv[1]
j = json.load(open('/tmp/job.json')) if False else None
PY
curl -s -b cj.txt "http://127.0.0.1:6008/api/batches/$ID" -o /tmp/job.json
/root/apps/portrait-studio/.venv/bin/python - <<'PY'
import json, subprocess, os
j = json.load(open('/tmp/job.json'))
bid = j['id']
picked = []
for a in j.get('assets', []):
    if a.get('thumb') and len(picked) < 4:
        picked.append((a['id'], (a.get('class') or {}).get('kind'), (a.get('quality') or {}).get('drop_reasons')))
for aid, kind, drop in picked:
    out = f'/tmp/thumbs/{aid}.jpg'
    code = subprocess.run(['curl', '-s', '-b', '/tmp/cj.txt', '-o', out,
                           '-w', '%{http_code}',
                           f'http://127.0.0.1:6008/api/batches/{bid}/thumb/{aid}'],
                          capture_output=True, text=True).stdout
    print(aid, kind, 'drop=', drop, 'http', code, 'bytes', os.path.getsize(out) if os.path.exists(out) else 0)
PY
ls -la /tmp/thumbs

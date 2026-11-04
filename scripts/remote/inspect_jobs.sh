#!/bin/bash
set -uo pipefail
D=/root/autodl-fs/portrait-studio
ls -la "$D/jobs/"
for jd in "$D"/jobs/*/; do
  echo "-- $jd"
  ls -la "$jd" 2>/dev/null | head -20
  echo "   output:"; ls "$jd/output" 2>/dev/null | head -20
done
echo "=== job summary ==="
/root/apps/portrait-studio/.venv/bin/python - <<'PY'
import json, glob
for p in sorted(glob.glob('/root/autodl-fs/portrait-studio/jobs/*/job.json')):
    j = json.load(open(p))
    print(p)
    print('  status=%s total=%s stats=%s stage=%s records=%d' % (j.get('status'), j.get('total'), j.get('stats'), j.get('stage'), len(j.get('records') or [])))
    for r in (j.get('records') or []):
        print('   -', r.get('source'), '|', r.get('status'), '|', r.get('orientation'), '| face=', r.get('face_bbox'), '|', (r.get('reason') or '')[:70])
    print('  sheets=', j.get('sheets'))
PY

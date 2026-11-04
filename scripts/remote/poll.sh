#!/bin/bash
set -uo pipefail
cd /tmp
ID=${1:-}
if [ -z "$ID" ]; then
  curl -s -b cj.txt http://127.0.0.1:6008/api/batches -o /tmp/list.json
  ID=$(/root/apps/portrait-studio/.venv/bin/python -c "import json;print(json.load(open('/tmp/list.json'))[0]['id'])")
fi
curl -s -b cj.txt "http://127.0.0.1:6008/api/batches/$ID" -o /tmp/job.json
/root/apps/portrait-studio/.venv/bin/python /tmp/show_job.py
echo '--- run.log ---'
tail -6 "/root/autodl-fs/case-studio/batches/${ID}/run.log" 2>/dev/null || true
echo '--- app err ---'
tail -5 /root/autodl-fs/case-studio/logs/error.log 2>/dev/null || true

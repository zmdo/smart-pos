#!/bin/bash
set -uo pipefail
cd /tmp
TOKEN=$(/root/apps/portrait-studio/.venv/bin/python -c "import json;print(json.load(open('/root/autodl-fs/case-studio/settings.json'))['access_token'])")
echo "{\"token\":\"$TOKEN\"}" > login.json
rm -f cj.txt
echo '--- login ---'
curl -s -c cj.txt -H 'Content-Type: application/json' --data-binary @login.json http://127.0.0.1:6008/api/login
echo
echo '--- submit ---'
time curl -s -b cj.txt -F 'archive=@/root/autodl-fs/qa/demo-cases.zip' -F 'mode=dryrun' http://127.0.0.1:6008/api/batches
echo

#!/bin/bash
set -uo pipefail
cd /root/apps/portrait-studio
echo "=== access code ==="
/root/apps/portrait-studio/.venv/bin/python -c "import json;print(json.load(open('/root/autodl-fs/portrait-studio/settings.json'))['access_code'])"
echo "=== settings (masked) ==="
/root/apps/portrait-studio/.venv/bin/python -c "import json;s=json.load(open('/root/autodl-fs/portrait-studio/settings.json'));s['api_key']=s['api_key'][:6]+'...';print(json.dumps(s,ensure_ascii=False))"
echo "=== pytest ==="
.venv/bin/python -m pytest tests -q 2>&1 | tail -15
echo "=== gpu ==="
nvidia-smi --query-gpu=name,memory.used,memory.total,utilization.gpu --format=csv
echo "=== health ==="
curl -s http://127.0.0.1:6006/api/health
echo
echo "=== models dir ==="
ls -la /root/autodl-fs/portrait-studio/models

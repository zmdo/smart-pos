#!/bin/bash
set -uo pipefail
V=/root/apps/portrait-studio/.venv/bin
echo '--- install transformers ---'
"$V/pip" install -q -i https://pypi.tuna.tsinghua.edu.cn/simple transformers 2>&1 | tail -3
export HF_ENDPOINT=https://hf-mirror.com
"$V/python" - <<'PY'
import os
os.environ.setdefault('HF_ENDPOINT', 'https://hf-mirror.com')
try:
    from transformers import pipeline
    print('transformers ok')
except Exception as e:
    print('transformers fail', e)
PY

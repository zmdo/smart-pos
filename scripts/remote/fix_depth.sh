#!/bin/bash
set -uo pipefail
V=/root/apps/portrait-studio/.venv/bin
export HF_ENDPOINT=https://hf-mirror.com
"$V/pip" install -q -i https://pypi.tuna.tsinghua.edu.cn/simple 'transformers==4.46.3' 2>&1 | tail -2
"$V/python" - <<'PY'
import os
os.environ['HF_ENDPOINT'] = 'https://hf-mirror.com'
from transformers import pipeline
from PIL import Image
import numpy as np
try:
    p = pipeline('depth-estimation', model='LiheYoung/depth-anything-small-hf', device=-1)
    img = Image.fromarray((np.random.rand(256, 256, 3) * 255).astype('uint8'))
    out = p(img)
    print('depth ok', type(out), list(out)[:3])
except Exception as e:
    print('depth fail:', type(e).__name__, str(e)[:300])
PY

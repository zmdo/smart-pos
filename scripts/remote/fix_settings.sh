#!/bin/bash
set -uo pipefail
/root/apps/portrait-studio/.venv/bin/python - <<'PY'
import json
p = '/root/autodl-fs/case-studio/settings.json'
j = json.load(open(p))
j['quality'] = {"sharpness": 20, "mean_dark": 30, "mean_bright": 245,
                "clip_ratio": 0.8, "subject_ratio": 0.02, "min_side": 640}
json.dump(j, open(p, 'w'), ensure_ascii=False, indent=2)
print(json.dumps(j['quality'], ensure_ascii=False))
PY

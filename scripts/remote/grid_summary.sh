#!/bin/bash
set -uo pipefail
cd /tmp/grid
for d in */; do
  n=${d%/}
  echo "=== $n"
  /root/apps/portrait-studio/.venv/bin/python - "$n" <<'PY'
import json, sys
n = sys.argv[1]
d = json.load(open(f'/tmp/grid/{n}/meta.json'))
def fmt(x):
    return '-' if not x else f"中位 {x['median']}° p90 {x['p90']}° max {x['max']}° (n={x['n']})"
print('  校正前 竖:', fmt(d['before']['vertical']), ' 横:', fmt(d['before']['horizontal']))
print('  校正后 竖:', fmt(d['final']['vertical']), ' 横:', fmt(d['final']['horizontal']))
print('  rotate:', d.get('rotate_deg'), ' affine:', d.get('affine_rectified'), d.get('skipped', ''))
PY
done

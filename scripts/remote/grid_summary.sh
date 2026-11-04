#!/bin/bash
set -euo pipefail
: "${1:?Usage: grid_summary.sh /absolute/experiment/directory}"
/root/apps/portrait-studio/.venv/bin/python - "$1/summary.json" <<'PY'
import json, sys
from collections import Counter
rows = json.load(open(sys.argv[1]))
print(dict(Counter(row['status'] for row in rows)))
for row in rows:
    print(row['asset_id'], row['status'], row.get('reason', ''))
    if row['status'] == 'corrected':
        for axis in ('vertical', 'horizontal'):
            b, a = row['before'][axis], row['after'][axis]
            print(f"  {axis}: median {b['median_deg']:.3f} -> {a['median_deg']:.3f}; "
                  f"p90 {b['p90_deg']:.3f} -> {a['p90_deg']:.3f} degrees")
PY

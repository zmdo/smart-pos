import json, glob, sys
from pathlib import Path
import numpy as np
import cv2

B = Path('/root/autodl-fs/case-studio/batches/456566d18e169e6e165c4dcc')
job = json.loads((B / 'job.json').read_text())
rows = []
for a in job['assets']:
    if a['kind'] != 'image' or not a.get('thumb'):
        continue
    p = B / a['thumb']
    if not p.exists():
        continue
    img = cv2.imread(str(p), cv2.IMREAD_GRAYSCALE)
    if img is None:
        continue
    h, w = img.shape
    scale = 512 / max(h, w)
    small = cv2.resize(img, (max(1, int(w * scale)), max(1, int(h * scale))))
    lap_var = float(cv2.Laplacian(small, cv2.CV_64F).var())
    mean = float(small.mean())
    hi = float((small > 245).mean())
    lo = float((small < 12).mean())
    rows.append((lap_var, mean, hi, lo, a['id'], (a.get('class') or {}).get('kind'),
                 (a.get('quality') or {}).get('drop_reasons'), a['path'].split('/')[-1][:28]))

rows.sort()
print('n =', len(rows))
vals = [r[0] for r in rows]
for q in (0, 5, 10, 25, 50, 75, 90, 100):
    print('sharp p%-3d = %.1f' % (q, vals[min(len(vals)-1, int(len(vals)*q/100))]))
print('\n-- 最低 12 张 --')
for r in rows[:12]:
    print('var=%7.1f mean=%5.1f hi=%.2f lo=%.2f %-9s %-14s %s' % (r[0], r[1], r[2], r[3], r[5], r[6], r[4]))
print('\n-- 被标 blurry 的分布 --')
bl = [r[0] for r in rows if r[6] and 'blurry' in r[6]]
print('count', len(bl), 'min/max', (min(bl), max(bl)) if bl else None)
print('\n-- 被标 bad_exposure 的 mean/hi/lo --')
bx = [(r[1], r[2], r[3]) for r in rows if r[6] and 'bad_exposure' in r[6]]
for t in bx[:10]:
    print('mean=%.1f hi=%.2f lo=%.2f' % t)

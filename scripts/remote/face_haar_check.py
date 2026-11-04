import json, os, glob
import numpy as np
import cv2
from PIL import Image

BASE = '/root/autodl-fs/portrait-studio/jobs'
jobs = sorted(glob.glob(BASE + '/*/job.json'), key=os.path.getmtime, reverse=True)
job = next(p for p in jobs if (json.load(open(p)).get('stats') or {}).get('done', 0) >= 30)
data = json.load(open(job))
cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')
rows = [r for r in data['records'] if r.get('face_bbox') and r.get('orientation') in ('front', 'left', 'right')]

hits = []
for r in rows:
    path = os.path.join(os.path.dirname(job), 'input', r['source'])
    img = cv2.imread(path)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    dets = cascade.detectMultiScale(gray, scaleFactor=1.08, minNeighbors=6,
                                    minSize=(max(24, img.shape[0]//25),) * 2)
    if len(dets) == 0:
        continue
    v = r['face_bbox_model']
    # keep the Haar hit closest to the model box
    def dist(d):
        cx, cy = d[0] + d[2] / 2, d[1] + d[3] / 2
        return abs(cx - (v[0] + v[2]) / 2) + abs(cy - (v[1] + v[3]) / 2)
    d = min(dets, key=dist)
    hx1, hy1, hw, hh = d
    cx, cy = hx1 + hw / 2, hy1 + hh / 2
    inside = v[0] <= cx <= v[2] and v[1] <= cy <= v[3]
    cover = (v[0] <= hx1 and v[1] <= hy1 and v[2] >= hx1 + hw and v[3] >= hy1 + hh)
    off = ((cx - (v[0] + v[2]) / 2) / (v[2] - v[0]), (cy - (v[1] + v[3]) / 2) / (v[3] - v[1]))
    hits.append((r['source'], inside, cover, round(off[0], 3), round(off[1], 3),
                 round(hw / (v[2] - v[0]), 2), round(hh / (v[3] - v[1]), 2)))

print('frontal-detector hits: %d / %d frontal-ish images' % (len(hits), len(rows)))
if hits:
    print('center inside VLM box:', sum(h[1] for h in hits), '/', len(hits))
    print('VLM box covers Haar box:', sum(h[2] for h in hits), '/', len(hits))
    print('median |dx|,|dy| (face widths): %.3f %.3f' % (
        np.median([abs(h[3]) for h in hits]), np.median([abs(h[4]) for h in hits])))
    print('median HaarSize/VLMbox: w=%.2f h=%.2f' % (
        np.median([h[5] for h in hits]), np.median([h[6] for h in hits])))
    for h in hits[:10]:
        print('  %-18s inside=%s cover=%s dx=%.3f dy=%.3f w=%.2f h=%.2f' % h)

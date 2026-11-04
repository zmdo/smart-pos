import json, os, glob
import numpy as np
from PIL import Image, ImageDraw

BASE = '/root/autodl-fs/portrait-studio/jobs'
jobs = sorted(glob.glob(BASE + '/*/job.json'), key=os.path.getmtime, reverse=True)
job = None
for p in jobs:
    j = json.load(open(p))
    if (j.get('stats') or {}).get('done', 0) >= 30:
        job = p
        break
print('job', job)
data = json.load(open(job))
rows = [r for r in data['records'] if r.get('face_bbox') and r.get('face_bbox_model')]

def iou(a, b):
    x1, y1 = max(a[0], b[0]), max(a[1], b[1])
    x2, y2 = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, x2-x1)*max(0.0, y2-y1)
    union = (a[2]-a[0])*(a[3]-a[1]) + (b[2]-b[0])*(b[3]-b[1]) - inter
    return inter/union if union else 0.0

vals = []
for r in rows:
    m, s = r['face_bbox_model'], r['face_bbox']
    ma = (m[2]-m[0])*(m[3]-m[1])
    sa = (s[2]-s[0])*(s[3]-s[1])
    cx_m, cy_m = (m[0]+m[2])/2, (m[1]+m[3])/2
    cx_s, cy_s = (s[0]+s[2])/2, (s[1]+s[3])/2
    # center offset in units of the SAM face size
    off = (((cx_m-cx_s)/(s[2]-s[0]))**2 + ((cy_m-cy_s)/(s[3]-s[1]))**2) ** .5
    vals.append((r['source'], round(iou(m, s), 3), round(ma/sa, 3), round(off, 3),
                 round(m[2]-m[0]), round(m[3]-m[1]), round(s[2]-s[0]), round(s[3]-s[1])))

print('n =', len(vals))
arr = np.array([[v[1], v[2], v[3]] for v in vals])
print('IoU(VLM,SAM2)  mean=%.3f median=%.3f min=%.3f' % (arr[:,0].mean(), np.median(arr[:,0]), arr[:,0].min()))
print('area ratio     mean=%.2f median=%.2f max=%.2f min=%.2f' % (arr[:,1].mean(), np.median(arr[:,1]), arr[:,1].max(), arr[:,1].min()))
print('center offset  mean=%.2f median=%.2f max=%.2f (in face widths)' % (arr[:,2].mean(), np.median(arr[:,2]), arr[:,2].max()))
print('VLM area > 1.5x SAM2: %d / %d' % (int((arr[:,1] > 1.5).sum()), len(arr)))
print('VLM area > 2.0x SAM2: %d / %d' % (int((arr[:,1] > 2.0).sum()), len(arr)))
for v in vals[:12]:
    print('  %-18s iou=%.2f ratio=%.2f off=%.2f vlm=%dx%d sam=%dx%d' % v)

# overlay proofs: pick varied cases
out = '/tmp/overlay'
os.makedirs(out, exist_ok=True)
picked = sorted(vals, key=lambda v: v[2])[:2] + sorted(vals, key=lambda v: -v[2])[:2]
for src, i, ratio, off, *_ in picked:
    path = os.path.join(os.path.dirname(job), 'input', src)
    im = Image.open(path).convert('RGB')
    d = ImageDraw.Draw(im)
    r = next(x for x in rows if x['source'] == src)
    m, s = r['face_bbox_model'], r['face_bbox']
    d.rectangle(m, outline=(220, 60, 40), width=max(3, im.width//160))
    d.rectangle(s, outline=(30, 170, 80), width=max(3, im.width//160))
    # crop around the union for legibility
    x1 = int(min(m[0], s[0])) - 60; y1 = int(min(m[1], s[1])) - 60
    x2 = int(max(m[2], s[2])) + 60; y2 = int(max(m[3], s[3])) + 60
    im = im.crop((max(0, x1), max(0, y1), min(im.width, x2), min(im.height, y2)))
    im.thumbnail((700, 700))
    name = os.path.basename(src).replace('.jpg', '') + ('_big' if ratio > 1 else '_small') + '.png'
    im.save(os.path.join(out, name))
    print('saved', name, 'ratio', ratio, 'iou', i)

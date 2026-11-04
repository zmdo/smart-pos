import sys, os, json, math
import numpy as np
from PIL import Image
import engine
from imaging import open_image, validate_box

JOB = sys.argv[1]
NAMES = sys.argv[2:]
base = f'/root/autodl-fs/portrait-studio/jobs/{JOB}/input'
cfg = engine.load()
print('model', cfg.get('model'), 'key', bool(cfg.get('api_key')))


def iou(a, b):
    x1, y1 = max(a[0], b[0]), max(a[1], b[1])
    x2, y2 = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, x2-x1)*max(0.0, y2-y1)
    union = (a[2]-a[0])*(a[3]-a[1]) + (b[2]-b[0])*(b[3]-b[1]) - inter
    return inter/union if union > 0 else 0.0


import torch
for name in NAMES:
    path = os.path.join(base, name)
    print('='*70)
    print(name)
    img = open_image(path)
    sel, cand, ctx = engine.detect(img, 0.35, '/tmp/dbg_seg.png')
    if sel is None:
        print('  no person')
        continue
    x1, y1, x2, y2 = sel['bbox']
    bw, bh = x2-x1, y2-y1
    cb = [max(0, math.floor(x1-bw*.05)), max(0, math.floor(y1-bh*.03)),
          min(img.width, math.ceil(x2+bw*.05)), min(img.height, math.ceil(y2+bh*.03))]
    crop = img.crop(cb)
    print('  image', img.size, 'person', [round(v) for v in sel['bbox']], 'crop', cb)
    face = engine.locate_face(crop, cfg)
    if not face:
        print('  VLM: no visible face')
        continue
    box = [face[0]+cb[0], face[1]+cb[1], face[2]+cb[0], face[3]+cb[1]]
    print('  VLM face px', [round(v) for v in box], 'size', round(box[2]-box[0]), 'x', round(box[3]-box[1]))
    work, sx, sy = ctx['work'], ctx['sx'], ctx['sy']
    person = ctx['mask']
    parea = int(person.sum())
    wb = [box[0]/sx, box[1]/sy, box[2]/sx, box[3]/sy]
    cent = [[(wb[0]+wb[2])/2, (wb[1]+wb[3])/2]]
    modes = {
        'box+point': dict(box=np.asarray(wb, dtype=np.float32), point_coords=np.asarray(cent, dtype=np.float32),
                          point_labels=np.asarray([1], dtype=np.int64)),
        'point': dict(point_coords=np.asarray(cent, dtype=np.float32), point_labels=np.asarray([1], dtype=np.int64)),
        'box': dict(box=np.asarray(wb, dtype=np.float32)),
    }
    for label, kw in modes.items():
        with engine.INFER_LOCK, torch.inference_mode(), torch.autocast('cuda', dtype=torch.bfloat16):
            masks, scores, _ = ctx['sam'].predict(multimask_output=False, **kw)
        m = masks[0].astype(bool)
        a = int(m.sum())
        if a == 0:
            print(f'  {label:10s} empty')
            continue
        yy, xx = np.where(m)
        bb = [float(xx.min())*sx, float(yy.min())*sy, float(xx.max()+1)*sx, float(yy.max()+1)*sy]
        inside = float((m & person).sum())/a
        ratio = a/parea
        print('  %-10s area=%6d ratio=%.3f inside=%.3f iou_box=%.3f bbox=%s %dx%d' % (
            label, a, ratio, inside, iou(bb, box),
            [round(v) for v in bb], round(bb[2]-bb[0]), round(bb[3]-bb[1])))

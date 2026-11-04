import json, os, glob, time
import numpy as np
import cv2

JOB = '/root/autodl-fs/portrait-studio/jobs/29ac6d3588e83b2b8e679995'
MODEL = '/root/autodl-fs/portrait-studio/models/yunet3.onnx'
data = json.load(open(os.path.join(JOB, 'job.json')))
rows = [r for r in data['records'] if r.get('face_bbox')]

det = cv2.FaceDetectorYN.create(MODEL, '', (320, 320), 0.5, 0.3, 5000)


def detect_faces(img):
    h, w = img.shape[:2]
    scale = 1.0
    if max(h, w) > 1600:
        scale = 1600 / max(h, w)
        img = cv2.resize(img, (int(w * scale), int(h * scale)))
    hh, ww = img.shape[:2]
    det.setInputSize((ww, hh))
    _, faces = det.detect(img)
    if faces is None:
        return []
    out = []
    for f in faces:
        x, y, bw, bh, score = f[0], f[1], f[2], f[3], f[-1]
        lm = f[4:14].reshape(5, 2)
        out.append({'box': [x / scale, y / scale, (x + bw) / scale, (y + bh) / scale],
                    'score': float(score), 'lm': lm / scale, 'landmark_box': landmark_box(lm / scale)})
    return out


def landmark_box(lm):
    # lm order: right eye, left eye, nose, right mouth, left mouth (YuNet)
    re, le, nose, rm, lmo = lm
    eye_d = np.linalg.norm(le - re)
    cx = (re[0] + le[0]) / 2
    top = min(re[1], le[1]) - 0.85 * eye_d
    bottom = max(rm[1], lmo[1]) + 0.75 * eye_d
    half = 0.95 * eye_d
    return [cx - half, top, cx + half, bottom]


def iou(a, b):
    x1, y1 = max(a[0], b[0]), max(a[1], b[1])
    x2, y2 = min(a[2], b[2]), min(a[3], b[3])
    i = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    u = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - i
    return i / u if u > 0 else 0.0


rows_stat = []
t0 = time.time()
for r in rows:
    path = os.path.join(JOB, 'input', r['source'])
    img = cv2.imread(path)
    pb = r['person']['bbox']
    faces = detect_faces(img)
    vlm = r['face_bbox_model']
    sam = r['face_bbox']
    if not faces:
        rows_stat.append((r['source'], r['orientation'], None, None, None, None, 0))
        print('%-18s %-6s yunet: none                                   (vlm %dx%d)' % (
            r['source'], r['orientation'], vlm[2] - vlm[0], vlm[3] - vlm[1]))
        continue
    # keep the highest-scoring face whose centre lies in the upper part of the person box
    def near(f):
        cx, cy = (f['box'][0] + f['box'][2]) / 2, (f['box'][1] + f['box'][3]) / 2
        inside = pb[0] - 40 <= cx <= pb[2] + 40 and pb[1] - 40 <= cy <= pb[1] + 0.65 * (pb[3] - pb[1])
        return (0 if inside else 1, -f['score'])
    best = sorted(faces, key=near)[0]
    ib = iou(best['box'], vlm)
    isam = iou(best['box'], sam)
    rows_stat.append((r['source'], r['orientation'], best['score'], ib, isam, len(faces),
                      round((best['box'][2] - best['box'][0]) / (vlm[2] - vlm[0]), 2)))
    print('%-18s %-6s score=%.2f n=%d yunet=%dx%d vlm=%dx%d iou_vlm=%.2f iou_sam=%.2f w_ratio=%.2f lm_box=%dx%d' % (
        r['source'], r['orientation'], best['score'], len(faces),
        best['box'][2] - best['box'][0], best['box'][3] - best['box'][1],
        vlm[2] - vlm[0], vlm[3] - vlm[1], ib, isam,
        (best['box'][2] - best['box'][0]) / (vlm[2] - vlm[0]),
        best['landmark_box'][2] - best['landmark_box'][0], best['landmark_box'][3] - best['landmark_box'][1]))

found = [r for r in rows_stat if r[2] is not None]
print('\nYuNet found a face in %d / %d images (%.1f s for the batch, CPU)' % (len(found), len(rows_stat), time.time() - t0))
if found:
    print('median score %.2f, IoU vs VLM %.2f, IoU vs SAM2 %.2f' % (
        np.median([f[2] for f in found]), np.median([f[3] for f in found]), np.median([f[4] for f in found])))
    by_dir = {}
    for f in found:
        by_dir.setdefault(f[1], []).append(f)
    for d, v in sorted(by_dir.items()):
        print('  %-6s %d found, median iou_vlm %.2f' % (d, len(v), np.median([x[3] for x in v])))

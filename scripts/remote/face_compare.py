import json, os, glob

BASE = '/root/autodl-fs/portrait-studio/jobs'
jobs = sorted(glob.glob(BASE + '/*/job.json'), key=os.path.getmtime, reverse=True)


def load(tag):
    for p in jobs:
        j = json.load(open(p))
        if tag in p:
            return p, j
    return p, j


def stats(path):
    j = json.load(open(path))
    out = []
    for r in j['records']:
        if r.get('face_bbox') and r.get('image_size'):
            w, h = r['image_size']
            b = r['face_bbox']
            out.append(((b[2]-b[0])*(b[3]-b[1]))/(w*h))
    return j, out


old_path = [p for p in jobs if '29ac6d' in p][0]
new_path = [p for p in jobs if 'b996cc' in p][0]
_, old = stats(old_path)
jn, new = stats(new_path)
import statistics
print('old (vision box + SAM2): n=%d  median face/img area = %.4f  mean %.4f' % (
    len(old), statistics.median(old), sum(old)/len(old)))
print('new (YuNet + SAM2)      : n=%d  median face/img area = %.4f  mean %.4f' % (
    len(new), statistics.median(new), sum(new)/len(new)))
print('ratio of medians: %.2f' % (statistics.median(new)/statistics.median(old)))

src = {}
for r in jn['records']:
    if r.get('face_source'):
        src[r['face_source']] = src.get(r['face_source'], 0) + 1
print('face source counts:', src)
notes = [r.get('face_segmentation_note') for r in jn['records'] if r.get('face_segmentation_note')]
print('rejection notes:', notes)

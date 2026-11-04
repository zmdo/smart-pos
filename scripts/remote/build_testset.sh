#!/bin/bash
set -uo pipefail
# Build a realistic person-photo test set from COCO val2017 (annotations give person boxes).
WORK=/root/autodl-fs/qa/testset
mkdir -p "$WORK"
cd "$WORK"

if [ ! -f instances_val2017.json ]; then
  timeout 300 curl -s -o instances_val2017.json "http://images.cocodataset.org/annotations/annotations_trainval2017.zip" -w 'zip %{http_code} %{size_download}\n'
  unzip -o -q annotations_trainval2017.zip annotations/instances_val2017.json
  mv annotations/instances_val2017.json .
  rm -rf annotations annotations_trainval2017.zip
fi
ls -la instances_val2017.json

/root/apps/portrait-studio/.venv/bin/python - <<'PY'
import json, collections
ann = json.load(open('/root/autodl-fs/qa/testset/instances_val2017.json'))
person = [a for a in ann['annotations'] if a['category_id'] == 1]
by_img = collections.defaultdict(list)
for a in person:
    by_img[a['image_id']].append(a)
imgs = {i['id']: i for i in ann['images']}
picked = []
for iid, anns in by_img.items():
    im = imgs[iid]
    area = im['width'] * im['height']
    big = [a for a in anns if a['area'] > 0.08 * area and not a['iscrowd']]
    if big:
        picked.append((iid, im['file_name'], im['width'], im['height'], len(anns)))
picked.sort()
print('candidates', len(picked))
with open('/root/autodl-fs/qa/testset/pick.txt', 'w') as f:
    for p in picked[:40]:
        f.write('%s %s\n' % (p[1], p[4]))
PY
head -5 pick.txt

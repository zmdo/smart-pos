import os, json
from PIL import Image
from ultralytics import YOLO

RAW = '/root/autodl-fs/qa/sample/raw'
WEIGHTS = '/root/autodl-fs/portrait-studio/models/yolo11n.pt'

model = YOLO(WEIGHTS)
rows = []
for name in sorted(os.listdir(RAW)):
    p = os.path.join(RAW, name)
    try:
        with Image.open(p) as probe:
            probe.verify()
        with Image.open(p) as im:
            im = im.convert('RGB')
            w, h = im.size
    except Exception:
        continue
    res = model.predict(im, classes=[0], conf=0.5, imgsz=640, verbose=False, device=0)[0]
    if not len(res.boxes):
        continue
    area = w * h
    boxes = res.boxes.xyxy.cpu().numpy()
    ratios = [((b[2] - b[0]) * (b[3] - b[1])) / area for b in boxes]
    rows.append([round(float(max(ratios)), 4), name, int(len(boxes)), w, h])

rows.sort(reverse=True)
print('images with person:', len(rows))
for r in rows[:30]:
    print('%.3f %s n=%d %dx%d' % tuple(r))
json.dump(rows[:30], open('/root/autodl-fs/qa/sample/picked.json', 'w'))

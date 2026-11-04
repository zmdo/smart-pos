import json, sys
import cv2, numpy as np
sys.path.insert(0, '/root/apps/case-studio/tools')
from ultralytics import YOLO

model = YOLO('/root/autodl-fs/portrait-studio/models/yolo11n.pt')


def measure(path):
    img = cv2.imread(path)
    if img is None:
        return None
    h, w = img.shape[:2]
    res = model.predict(img, classes=[0], conf=0.35, imgsz=1024, verbose=False, device=0)[0]
    boxes = res.boxes.xyxy.cpu().numpy().tolist() if len(res.boxes) else []
    if not boxes:
        return {"path": path, "persons": 0}
    b = max(boxes, key=lambda b: (b[2] - b[0]) * (b[3] - b[1]))
    x1, y1, x2, y2 = b
    return {"path": path.split('/')[-1], "persons": len(boxes),
            "height_frac": round((y2 - y1) / h, 3),
            "feet_y": round(y2 / h, 3),
            "center_x": round((x1 + x2) / 2 / w, 3),
            "width_frac": round((x2 - x1) / w, 3)}


groups = {
    "v1 直接对半切": ["/tmp/std/a0018_董彦琦_side/before.jpg", "/tmp/std/a0018_董彦琦_side/after.jpg"],
    "v9 领地取景": ["/tmp/v9/dong_side/before.jpg", "/tmp/v9/dong_side/after.jpg"],
}
for name, paths in groups.items():
    print('==', name)
    for p in paths:
        m = measure(p)
        print('  ', json.dumps(m, ensure_ascii=False))

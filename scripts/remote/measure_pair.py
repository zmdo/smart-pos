import sys
import cv2
from ultralytics import YOLO

model = YOLO('/root/autodl-fs/portrait-studio/models/yolo11n.pt')

for tag, p in [('BEFORE', '/tmp/v9/dong_side/before.jpg'), ('AFTER', '/tmp/v9/dong_side/after.jpg')]:
    img = cv2.imread(p)
    h, w = img.shape[:2]
    res = model.predict(img, classes=[0], conf=0.35, imgsz=1024, verbose=False, device=0)[0]
    b = res.boxes.xyxy.cpu().numpy()[0]
    x1, y1, x2, y2 = b
    print(f'{tag}: 画布 {w}x{h} 人物高 {(y2-y1):.0f}px = {(y2-y1)/h:.3f}H  '
          f'宽 {(x2-x1):.0f}px = {(x2-x1)/w:.3f}W  '
          f'头顶 y={y1:.0f} 脚底 y={y2:.0f} 中心x={(x1+x2)/2:.0f}')

import sys, cv2, numpy as np
sys.path.insert(0, '/root/apps/case-studio/tools')
from standardize_pair_v2 import load, detect_persons, segment_persons

src = '/root/autodl-fs/case-studio/batches/287a8a82df2f2fca2c22299b/input/私教会员案例项目/景田店/董彦琦/30d3021690de42a92336410c18745261_compress.jpg'
img = load(src)
boxes = detect_persons(img)
print('boxes', [[round(v) for v in b] for b in boxes])
masks = segment_persons(img, [boxes[0], boxes[-1]])
for i, (m, b) in enumerate(zip(masks, [boxes[0], boxes[-1]])):
    area = int(m.sum())
    x1, y1, x2, y2 = [int(v) for v in b]
    bbox_area = (x2 - x1) * (y2 - y1)
    print(f'mask{i}: area={area} bbox_area={bbox_area} ratio={area/max(1,bbox_area):.3f} dtype={m.dtype} unique={np.unique(m.astype(np.uint8))[:5]}')
    vis = (m.astype(np.uint8) * 255)
    cv2.imwrite(f'/tmp/mask{i}.png', vis)
print('wrote /tmp/mask0.png /tmp/mask1.png')

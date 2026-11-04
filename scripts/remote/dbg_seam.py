import sys
sys.path.insert(0, '/root/apps/case-studio/tools')
import cv2, numpy as np
from standardize_pair_v2 import load, detect_persons
from standardize_pair_v9 import detect_seam

paths = {
 'dong_side': '/root/autodl-fs/case-studio/batches/287a8a82df2f2fca2c22299b/input/私教会员案例项目/景田店/董彦琦/30d3021690de42a92336410c18745261_compress.jpg',
 'dong_front': '/root/autodl-fs/case-studio/batches/287a8a82df2f2fca2c22299b/input/私教会员案例项目/景田店/董彦琦/8dec5a34fc8e82e7b14984bc44c19abb_compress.jpg',
 'ren_front': '/root/autodl-fs/case-studio/batches/287a8a82df2f2fca2c22299b/input/私教会员案例项目/宝安店/任胜男-candy/4333be434f4b55425495ee1860774d38(1).jpg',
}
for name, p in paths.items():
    img = load(p)
    boxes = detect_persons(img)
    seam = detect_seam(img, boxes)
    print(f'{name}: size={img.shape[1]}x{img.shape[0]} boxes={[[round(v) for v in b] for b in boxes]} seam={seam}')
    band = img[:img.shape[0]//8].astype(np.float32).mean(axis=0).mean(axis=1)
    k = np.ones(9)/9
    sm = np.convolve(band, k, mode='same')
    idx = range(max(0, boxes[0][2]-20), min(len(sm), int(boxes[1][0])+20), 20)
    print('   profile:', {int(i): round(float(sm[i]), 1) for i in idx})

import sys, glob
sys.path.insert(0, '/root/apps/case-studio')
from pathlib import Path
import preprocess

paths = sorted(glob.glob('/root/autodl-fs/case-studio/batches/*/input/**/*.jpg', recursive=True))[:8]
vals = []
for p in paths:
    try:
        from PIL import Image
        img = preprocess.load_image(Path(p))
        h = preprocess.phash(img)
        vals.append((Path(p).name[:24], img.size, h))
    except Exception as e:
        print('ERR', p, e)
for name, size, h in vals:
    print(name, size, hex(h), bin(h).count('1'))
print('--- pairwise hamming ---')
for i in range(len(vals)):
    for j in range(i + 1, len(vals)):
        print(vals[i][0][:12], vals[j][0][:12], preprocess.hamming(vals[i][2], vals[j][2]))

import json, io, sys
sys.path.insert(0, '/root/apps/case-studio')
from pathlib import Path
import preprocess

j = json.load(io.open('/tmp/job.json', encoding='utf-8'))
batch = Path('/root/autodl-fs/case-studio/batches') / j['id']
assets = {a['id']: a for a in j['assets']}
ids = ['a0006', 'a0011', 'a0027', 'a0030', 'a0061', 'a0049', 'a0051']
for aid in ids:
    a = assets.get(aid)
    if not a:
        continue
    p = batch / 'input' / a['path']
    try:
        img = preprocess.load_image(p)
        ph = preprocess.phash(img)
        print(aid, img.size, hex(ph), bin(ph).count('1'), a.get('status'))
    except Exception as e:
        print(aid, 'ERR', e)
base = assets['a0006']
img = preprocess.load_image(batch / 'input' / base['path'])
bph = preprocess.phash(img)
print('--- distances to a0006 ---')
for aid in ids:
    a = assets.get(aid)
    if not a or aid == 'a0006':
        continue
    try:
        im = preprocess.load_image(batch / 'input' / a['path'])
        print(aid, preprocess.hamming(bph, preprocess.phash(im)))
    except Exception as e:
        print(aid, 'ERR', e)

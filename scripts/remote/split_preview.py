import json, io
from pathlib import Path
from PIL import Image

base = Path('/root/autodl-fs/case-studio/batches/287a8a82df2f2fca2c22299b')
j = json.loads((base / 'job.json').read_text())
out = Path('/tmp/split_preview'); out.mkdir(exist_ok=True)
picked = 0
for a in j['assets']:
    sp = a.get('split')
    if not sp or a['store'].startswith('（'):
        continue
    src = base / 'work' / (a['id'] + '.jpg')
    if not src.exists():
        continue
    im = Image.open(src)
    x = sp['x']
    im.crop((0, 0, x, im.height)).save(out / f"{a['id']}_before.jpg", quality=85)
    im.crop((x, 0, im.width, im.height)).save(out / f"{a['id']}_after.jpg", quality=85)
    print(a['id'], a['member'], a['class']['view'], 'x=', x, im.size)
    picked += 1
    if picked >= 2:
        break

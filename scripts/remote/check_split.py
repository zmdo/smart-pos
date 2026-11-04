import json, io

j = json.load(io.open('/tmp/job.json', encoding='utf-8'))
assets = j.get('assets') or []
print('split_images:', (j.get('summary') or {}).get('split_images'))
n = 0
for a in assets:
    sp = a.get('split')
    if not sp:
        continue
    n += 1
    w = a.get('width') or 0
    frac = (sp.get('x', 0) / w) if w else 0
    print('%-6s %-10s %-12s view=%-10s x=%5d/%5d (%.2f) method=%-7s persons=%s' % (
        a['id'], a['store'], a['member'], (a.get('class') or {}).get('view'),
        sp.get('x', 0), w, frac, sp.get('method'), (a.get('quality') or {}).get('persons')))
print('total split', n)

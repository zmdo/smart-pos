import json, io, collections

j = json.load(io.open('/tmp/job.json', encoding='utf-8'))
assets = j.get('assets') or []
views = collections.Counter()
bgs = collections.Counter()
combo = collections.Counter()
for a in assets:
    c = a.get('class') or {}
    if c.get('kind') != 'body_scan':
        continue
    v = c.get('view') or 'unknown'
    views[v] += 1
    bgs[c.get('background') or 'unknown'] += 1
    combo[(v, c.get('background'))] += 1
print('views:', dict(views))
print('backgrounds:', dict(bgs))
print('combos:')
for k, v in sorted(combo.items()):
    print('   ', k, v)

print('\n-- 每个会员的体测视图 --')
for m in j.get('members', []):
    sl = m.get('slots') or {}
    parts = []
    for key in ('front', 'side', 'back'):
        s = sl.get(key) or {}
        if s.get('before') or s.get('after'):
            bg = s.get('background') or {}
            parts.append('%s[%s|%s]' % (s.get('label'), bg.get('before'), bg.get('after')))
    print('%-8s %-14s %s' % (m['store'], m['name'], '  '.join(parts)))

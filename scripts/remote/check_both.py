import json, io, collections

j = json.load(io.open('/tmp/job.json', encoding='utf-8'))
assets = j.get('assets') or []
both = [a for a in assets if (a.get('class') or {}).get('phase') == 'both']
print('phase=both:', len(both))
by_member = collections.Counter((a['store'], a['member']) for a in both)
for k, v in by_member.most_common():
    print('  ', k, v)
print('\n-- detail --')
for a in both:
    c = a['class']
    print('%-6s %-10s %-10s view=%-11s bg=%-11s conf=%.2f  %s' % (
        a['id'], a['store'], a['member'], c.get('view'), c.get('background'),
        c.get('confidence', 0), a['path'][-40:]))

print('\n-- 该会员的 slots 使用情况 --')
for m in j.get('members', []):
    sl = m['slots']
    for k in ('front', 'side', 'back'):
        s = sl.get(k) or {}
        if s.get('before') and s.get('after'):
            pass
    print('%-14s %s' % (m['name'], {k: (v['before'], v['after']) for k, v in sl.items()}))

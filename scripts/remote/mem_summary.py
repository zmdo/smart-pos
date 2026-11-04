import statistics
rows = [l.strip().split(',') for l in open('/tmp/mem.log') if l.strip()]
vals = [(int(r[0]), int(r[1]), int(r[2])) for r in rows if len(r) >= 3]
if not vals:
    raise SystemExit('no data')
mem = [v[1] for v in vals]
t0 = vals[0][0]
print('samples', len(vals), 'span', vals[-1][0] - t0, 's')
print('idle first samples:', mem[:3])
print('peak MiB', max(mem), 'median', statistics.median(mem))
busy = [v for v in vals if v[1] > 200]
print('busy samples', len(busy), 'busy median MiB', statistics.median([v[1] for v in busy]) if busy else None)
print('gpu util peak %', max(v[2] for v in vals))
for v in vals[::15]:
    print('  t+%3ds %6d MiB util %3d%%' % (v[0] - t0, v[1], v[2]))

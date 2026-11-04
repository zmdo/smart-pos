import json, io, collections

j = json.load(io.open('/tmp/job.json', encoding='utf-8'))
assets = j.get("assets") or []
print("assets", len(assets))

reasons = collections.Counter()
for a in assets:
    for r in (a.get("quality") or {}).get("drop_reasons", []):
        reasons[r] += 1
print("drop reasons:", dict(reasons))

kinds = collections.Counter((a.get("class") or {}).get("kind") for a in assets if (a.get("class") or {}).get("kind"))
print("kinds:", dict(kinds))

views = collections.Counter(((a.get("class") or {}).get("view"), (a.get("class") or {}).get("phase"))
                            for a in assets if (a.get("class") or {}).get("kind") == "body_scan")
print("views:", dict(views))

conf = [ (a.get("class") or {}).get("confidence", 0) for a in assets if (a.get("class") or {}).get("kind")]
conf.sort()
print("conf p10/50/90:", conf[len(conf)//10], conf[len(conf)//2], conf[-len(conf)//10] if conf else None)

dups = collections.Counter(a.get("duplicate_of") for a in assets if a.get("status") == "duplicate")
print("dup groups:", len(dups), "top:", dups.most_common(5))

print("\n-- sample per member --")
seen = set()
for a in assets:
    key = (a.get("store"), a.get("member"))
    if key in seen or not a.get("class"):
        continue
    seen.add(key)
    print("%-28s %-22s %-14s view=%-6s phase=%-7s q=%s" % (
        key[0], key[1], a["class"].get("kind"), a["class"].get("view"),
        a["class"].get("phase"), a["class"].get("confidence")))

print("\n-- dropped examples --")
for a in assets:
    q = a.get("quality") or {}
    if q.get("drop_reasons"):
        print("%-60s %s sharp=%.3f subj=%s min_side=%s" % (
            a["path"][-58:], q["drop_reasons"], q.get("sharpness", 0),
            q.get("subject_ratio"), q.get("min_side")))

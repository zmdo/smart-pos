import json, io, collections

j = json.load(io.open('/tmp/job.json', encoding='utf-8'))
assets = j.get("assets") or []
dups = [a for a in assets if a.get("status") == "duplicate"]
print("total dup", len(dups))
for a in dups[:50]:
    print("%-8s <- %-8s %-70s %s" % (a["id"], a.get("duplicate_of"), a["path"][-68:], a.get("kind")))
print("--- originals ---")
for a in assets:
    if a["id"] in {d.get("duplicate_of") for d in dups}:
        print(a["id"], a["path"][-70:], a.get("status"))
print("--- status count ---", collections.Counter(a.get("status") for a in assets))

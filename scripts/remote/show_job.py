import json, sys, io

j = json.load(io.open('/tmp/job.json', encoding='utf-8'))
s = j.get("summary") or {}
print("id", j["id"], "status", j["status"], "stage", j.get("stage"))
print("files", j.get("total_files"), "images", j.get("total_images"),
      "processed", j.get("processed"), "classified", j.get("classified"))
if s:
    print("summary", json.dumps(s, ensure_ascii=False))
if j.get("error"):
    print("error", j["error"])
for m in (j.get("members") or []):
    c = m["counts"]
    print("  %s/%s: scan=%s report=%s tr=%s daily=%s life=%s testi=%s video=%s -> %s 张, 缺 %s, 待确认 %s" % (
        m["store"], m["name"], c["body_scan"], c["body_report"], c["training_report"],
        c["daily_training"], c["life_photo"], c["testimonial"], c["video_deferred"],
        m["produced_count"], len(m["gaps"]), len(m["review"])))

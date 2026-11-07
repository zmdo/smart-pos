"""Exercise isolated QA data only; never run against the production namespace."""

import argparse, copy, json, sys
from pathlib import Path
import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from studio import config, store
from studio.common import WEB_DATA, save


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job", required=True)
    parser.add_argument("--model", action="store_true")
    args = parser.parse_args()
    assert WEB_DATA.name.endswith("-qa"), "isolated QA namespace is required"
    c = httpx.Client(
        base_url="http://127.0.0.1:6010",
        headers={"Origin": "http://127.0.0.1:6010"},
        timeout=180,
        trust_env=False,
    )

    def request(method, path, **kw):
        r = c.request(method, "/api" + path, **kw)
        r.raise_for_status()
        return r.json()

    request("POST", "/session", json={"code": config.load()["access_token"]})
    root = "/jobs/" + args.job
    data = request("GET", root + "/review")
    member = data["members"][0]
    mid = member["id"]
    version = data["version"]
    checks = {}

    def preview(section):
        return request(
            "POST",
            root + "/preview/" + mid,
            json={"version": version, "section": section},
        )

    def patch(fields):
        nonlocal version
        r = request(
            "PATCH",
            root + "/members/" + mid,
            json={"version": version, "member": fields},
        )
        version = r["version"]
        return next(m for m in r["members"] if m["id"] == mid)

    before = {s: preview(s) for s in ("vs", "cover", "table")}
    assert {p["kind"] for p in before["vs"]["products"]} == {"vs"}
    assert len(before["vs"]["products"]) == 3
    assert {p["kind"] for p in before["cover"]["products"]} == {"cover"}
    assert {p["kind"] for p in before["table"]["products"]} == {"report"}
    checks["renders_only_selected_section"] = True
    cover = copy.deepcopy(member["cover"])
    cover["title"] = "记录每次坚持"
    patch({"cover": cover})
    status = request("GET", root + "/previews/" + mid)
    assert status["sections"]["cover"]["fingerprint"] != status["keys"]["cover"]
    assert status["sections"]["vs"]["fingerprint"] == status["keys"]["vs"]
    checks["edit_saves_without_rendering"] = True
    vs = preview("vs")
    assert vs["cached"] and vs["products"] == before["vs"]["products"]
    table = preview("table")
    assert table["cached"] and table["products"] == before["table"]["products"]
    updated = preview("cover")
    assert updated["products"][0]["sha256"] != before["cover"]["products"][0]["sha256"]
    checks["cover_edit_reuses_vs_and_report"] = True
    comparison = copy.deepcopy(member["vs"])
    comparison["titles"]["front"] = "正面成果对比"
    patch({"vs": comparison})
    updated_vs = preview("vs")
    assert updated_vs["fingerprint"] != before["vs"]["fingerprint"]
    assert preview("cover")["cached"]
    checks["vs_edit_isolates_cover"] = True
    template = request(
        "POST",
        "/cover-ai/templates",
        json={
            "name": "QA 临时模板",
            "prompt": "真诚简短，不使用数字。不要把增重写成减重，不编造经历。",
            "fields": ["title", "story"],
            "injections": ["measurements", "name", "member", "coach", "outcomes"],
        },
    )
    assert any(
        t["id"] == template["id"]
        for t in request("GET", "/cover-ai/templates")["templates"]
    )
    if args.model:
        answer = request(
            "POST",
            root + "/members/" + mid + "/cover-ai",
            json={**template, "version": version},
        )
        assert set(answer["fields"]) == {"title", "story"}
        assert (
            len(answer["fields"]["title"]) <= 10
            and len(answer["fields"]["story"]) <= 280
        )
        assert store.review(args.job)["version"] == version
        cover.update(answer["fields"])
        changed = patch({"cover": cover})
        assert changed["cover"]["subtitle"] == member["cover"]["subtitle"]
        assert changed["cover"]["headline"] == member["cover"]["headline"]
        generated = preview("cover")
        assert generated["products"] and preview("vs")["cached"]
        checks["real_ai_selected_fields_rendered"] = True
        checks["model_usage"] = answer["trace"].get("usage")
    request("DELETE", "/cover-ai/templates/" + template["id"])
    checks["template_persistence_and_delete"] = True
    patch({"cover": member["cover"], "vs": member["vs"]})
    restored = {s: preview(s) for s in ("vs", "cover", "table")}
    assert all(
        restored[s]["cached"] and restored[s]["products"] == before[s]["products"]
        for s in before
    )
    checks["restored_values_reuse_original_images"] = True
    full = request("POST", root + "/preview/" + mid, json={"version": version})
    for section in restored.values():
        for p in section["products"]:
            reference = next(q for q in full["products"] if q["name"] == p["name"])
            assert p["sha256"] == reference["sha256"]
    checks["section_and_full_delivery_pixels_match"] = True
    checks["review_renders_model_calls"] = full["model_calls"]
    save(
        WEB_DATA / "e2e-review-v2.json",
        {"job": args.job, "review_version": version, "checks": checks},
    )
    print(json.dumps(checks, ensure_ascii=False))


if __name__ == "__main__":
    main()

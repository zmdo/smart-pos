"""Run only against a disposable validation batch; restores initial public review."""

import argparse, copy, io, json, sys, time, zipfile
from pathlib import Path
import httpx
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from studio import config, store
from studio.common import save, sha


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--job", required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--base-url", default="http://127.0.0.1:6010")
    p.add_argument("--allow-test-edits", action="store_true", required=True)
    a = p.parse_args()
    c = httpx.Client(
        base_url=a.base_url,
        headers={"Origin": a.base_url},
        timeout=180,
        trust_env=False,
    )

    def request(method, path, **kw):
        r = c.request(method, "/api" + path, **kw)
        r.raise_for_status()
        return r

    request("POST", "/session", json={"code": config.load()["access_token"]})
    prefix = "/jobs/" + a.job
    checks = {}
    initial = store.review(a.job, 1)
    current = request("GET", prefix + "/review").json()
    mid = current["members"][0]["id"]
    original = next(m for m in initial["members"] if m["id"] == mid)
    before = request(
        "POST", prefix + "/preview/" + mid, json={"version": current["version"]}
    ).json()
    selected = next(
        p
        for p in before["products"]
        if p["kind"] == "vs"
        and p["asset_ids"] == [r["asset_id"] for r in before["cover_sources"]]
    )["asset_ids"]
    m = copy.deepcopy(current["members"][0])
    m["profile"] = dict(name="欧阳验收", gender="女", coach="验收教练")
    for photo in m["photos"]:
        photo.update(
            phase="after" if photo["phase"] == "before" else "before", confirmed=True
        )
    m["vs"]["before_text"] = "起点"
    m["vs"]["after_text"] = "现在"
    m["vs"]["titles"]["front"] = "正面变化"
    m["cover"].update(title="记录每次改变", badge="案例展示")
    for row in before["cover_sources"]:
        x, y, w, h = row["crop"]
        m["cover"]["crops"][row["asset_id"]] = [
            x + w * 0.025,
            y + h * 0.025,
            w * 0.95,
            h * 0.95,
        ]
    m["table"]["rows"].append(
        dict(
            type="肩宽验收",
            key="custom_validation",
            before="40",
            after="41",
            delta="+1",
            unit="cm",
        )
    )

    def patch_member(m, version):
        fields = {k: copy.deepcopy(m[k]) for k in ("profile", "vs", "cover", "table")}
        fields["photos"] = [
            {
                k: photo[k]
                for k in ("asset_id", "phase", "view", "confirmed", "preferred")
            }
            for photo in m["photos"]
        ]
        return request(
            "PATCH",
            prefix + "/members/" + mid,
            json={"version": version, "member": fields},
        ).json()

    changed = patch_member(m, current["version"])
    saved = changed["members"][0]
    assert saved["vs"]["nickname"] == "欧阳女士"
    checks["identity_and_honorific"] = True
    conflict = c.patch(
        "/api" + prefix + "/members/" + mid,
        json={"version": current["version"], "member": {}},
    )
    assert conflict.status_code == 409
    checks["stale_review_rejected"] = True
    preview = request(
        "POST", prefix + "/preview/" + mid, json={"version": changed["version"]}
    ).json()
    assert [x["asset_id"] for x in preview["cover_sources"]] == selected[::-1]
    assert any(
        p["kind"] == "vs" and p["asset_ids"] == selected[::-1]
        for p in preview["products"]
    )
    checks["phase_changes_vs_and_cover_order"] = True
    assert (
        len(saved["table"]["rows"]) == len(current["members"][0]["table"]["rows"]) + 1
    )
    table_before = next(p for p in before["products"] if p["kind"] == "report")
    table_after = next(p for p in preview["products"] if p["kind"] == "report")
    assert (
        table_before["size"] == table_after["size"]
        and table_before["sha256"] != table_after["sha256"]
    )
    checks["custom_table_row_same_canvas"] = True
    grid = next(p for p in preview["products"] if p["kind"] == "three_views")
    image = Image.open(store.media_file(a.job, grid["media"])).convert("RGB")
    private = store.review(a.job, changed["version"])["members"][0]
    photo = Image.open(private["_engine"]["photos"][selected[1]]).convert("RGB")
    assert image.crop((0, 0, photo.width, photo.height)).tobytes() == photo.tobytes()
    checks["three_view_uses_reviewed_order_without_labels"] = True
    assert all(
        x["crop"] == saved["cover"]["crops"][x["asset_id"]]
        for x in preview["cover_sources"]
    )
    checks["independent_uniform_cover_crops"] = True
    bad = copy.deepcopy(saved["cover"])
    bad["crops"][selected[0]] = [-1, 0, 0.5, 0.5]
    r = c.patch(
        "/api" + prefix + "/members/" + mid,
        json={"version": changed["version"], "member": {"cover": bad}},
    )
    assert r.status_code == 400
    checks["outside_crop_rejected"] = True

    def generate(version):
        request("POST", prefix + "/generate", json={"version": version})
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            job = request("GET", prefix).json()
            if job["status"] == "failed":
                raise AssertionError(job["error"])
            if job["status"] == "complete":
                return request("GET", prefix + "/versions").json()[0]
            time.sleep(0.5)
        raise TimeoutError("generation did not finish")

    v1 = generate(changed["version"])
    url = prefix + "/download/" + v1["id"]
    download = request("GET", url, params={"member": mid})
    assert "zip" in download.headers["content-type"]
    with zipfile.ZipFile(io.BytesIO(download.content)) as z:
        assert any(name.endswith(".jpg") for name in z.namelist())
        assert all("/" not in name for name in z.namelist())
    all_zip = request("GET", url)
    with zipfile.ZipFile(io.BytesIO(all_zip.content)) as z:
        assert any("/验收教练-欧阳验收/" in n for n in z.namelist())
    checks["member_and_store_zip_layout"] = True
    restored = patch_member(original, changed["version"])
    assert request("GET", prefix).json()["status"] == "review"
    checks["return_to_review"] = True
    v2 = generate(restored["version"])
    assert v1["id"] != v2["id"]
    checks["new_immutable_version"] = True
    old = store.version(a.job, v1["id"])
    for person in old["members"]:
        for item in person["products"]:
            assert sha(store.media_file(a.job, item["media"])) == item["sha256"]
    checks["previous_version_remains_unchanged"] = True
    checks["generation_model_calls"] = sum(
        read_result.get("model_calls", 0) for read_result in v2["members"]
    )
    assert checks["generation_model_calls"] == 0
    save(
        a.out,
        dict(
            job=a.job,
            checks=checks,
            versions=[v1["id"], v2["id"]],
            product_count=sum(len(m["products"]) for m in v2["members"]),
            kinds=sorted({p["kind"] for m in v2["members"] for p in m["products"]}),
        ),
    )
    print(json.dumps({"passed": True, **checks}, ensure_ascii=False))


if __name__ == "__main__":
    main()

"""Website adapters around frozen renderers. No model calls during review/render."""

import copy, sys, shutil
from pathlib import Path
import cv2, numpy as np
from PIL import Image
from .common import REPO, FONT, read, save, sha, job_dir, clean_name
from . import store
from scripts.body_scan_delivery.render import plan, draw_product
from scripts.body_scan_delivery.presentation import nickname
from member_cover.copy import compose
from member_cover.render import draw_cover
from report_comparison.render import render as draw_report, HEADERS
from report_comparison.presentation import select_display_rows

sys.path.insert(0, str(REPO / "best-practices/body-scan-group-display-v3/scripts"))
from body_scan_cover_frames.geometry import plan_pair, measure, project
from body_scan_cover_frames.pipeline import render as render_frame


def table_report(table):
    if not table:
        return None
    pair = table.get("pair") or {}
    report = dict(
        report_id=table.get("case_id", "reviewed"),
        metrics={},
        before_date=pair.get("before_date"),
        after_date=pair.get("after_date"),
    )
    for r in table.get("rows", []):
        key = {"fat_percent": "fat"}.get(r.get("key"), r.get("key"))
        try:
            a, b = float(r["before"]), float(r["after"])
            report["metrics"][key] = dict(
                usable=True,
                before_values=[a],
                after_values=[b],
                computed_delta=[round(b - a, 4)],
                unit=r["unit"],
            )
        except (TypeError, ValueError, KeyError):
            pass
    try:
        from datetime import date

        report["stated_days"] = (
            date.fromisoformat(report["after_date"])
            - date.fromisoformat(report["before_date"])
        ).days
    except (TypeError, ValueError):
        pass
    return report


def editor(meta, dest):
    m = measure(meta)
    l, t, r, b = m["bounds"]
    # Include full pixel support, not the inset polygon used to plan safe crops.
    # Otherwise a valid edge-touching frame can fall a fraction beyond the editor.
    poly = project([[l, t], [r, t], [r, b], [l, b]], m["H"])
    lo = np.floor(poly.min(axis=0)) - 2
    hi = np.ceil(poly.max(axis=0)) + 2
    scale = min(1, 3000 / max(hi - lo))
    T = np.array([[scale, 0, -lo[0] * scale], [0, scale, -lo[1] * scale], [0, 0, 1]])
    size = np.ceil((hi - lo) * scale).astype(int).tolist()
    H = T @ m["H"]
    src = cv2.imread(meta["source"])
    if src is None:
        raise ValueError("封面原图不可读")
    l, t, r, b = map(int, m["bounds"])
    mask = np.zeros(src.shape[:2], np.uint8)
    mask[t:b, l:r] = 255
    warped = cv2.warpPerspective(src, H, tuple(size))
    valid = cv2.warpPerspective(mask, H, tuple(size), flags=cv2.INTER_NEAREST)
    rgba = cv2.cvtColor(warped, cv2.COLOR_BGR2BGRA)
    rgba[:, :, 3] = valid
    dest.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(dest), rgba)
    default = plan_pair([meta, meta])[0]
    rectangle = crop_from_plan(default, H, size)
    return dict(
        path=str(dest),
        H=H.tolist(),
        size=size,
        default_crop=rectangle,
        source=meta["source"],
        bounds=m["bounds"].tolist(),
    )


def crop_from_plan(frame, H, size):
    corners = project(
        [[0, 0], [500, 478]],
        np.asarray(H) @ np.linalg.inv(np.asarray(frame["H_source_to_cover"])),
    )
    a, b = corners
    return [
        a[0] / size[0],
        a[1] / size[1],
        (b[0] - a[0]) / size[0],
        (b[1] - a[1]) / size[1],
    ]


def manual_frame(meta, ed, rect):
    w, h = ed["size"]
    x, y, cw, ch = np.asarray(rect, float) * [w, h, w, h]
    if abs(cw / ch - 500 / 478) > 0.003:
        raise ValueError("封面取景比例必须固定为 500:478")
    H = np.array(
        [[500 / cw, 0, -x * 500 / cw], [0, 478 / ch, -y * 478 / ch], [0, 0, 1]]
    ) @ np.asarray(ed["H"])
    return render_frame(
        meta,
        dict(
            output_size=[500, 478],
            H_source_to_cover=H.tolist(),
            source_content_bounds_xyxy=ed["bounds"],
        ),
    )[0]


def prepare(jid, out):
    base = job_dir(jid)
    paths = read(base / "paths.json")
    cfg = read(base / "settings.json")
    job = read(paths["job"])
    audit = read(paths["audit"])
    combined = read(paths["combined"])
    assets = {a["id"]: a for a in combined["assets"]}
    original = {a["id"]: a for a in job["assets"]}
    labels = (
        read(Path(paths["phase"]) / "classification/labels.json", [])
        if paths["phase"]
        else []
    )
    photos = (
        read(Path(paths["phase"]) / "classification/inputs.json", {}).get("photos", {})
        if paths["phase"]
        else {}
    )
    metadata = (
        {
            r["asset_id"]: r
            for r in read(Path(paths["display"]) / "summary.json", [])
            if r.get("status") == "displayed"
        }
        if paths["display"]
        else {}
    )
    tables = read(Path(paths["tables"]) / "tables.json", [])
    identities = (
        read(Path(paths["identity"]) / "identity.json", {}).get("members", {})
        if paths.get("identity")
        else {}
    )
    report_records = {
        r["source_id"]: r for r in read(Path(paths["tables"]) / "records.json", [])
    }
    exclusions = {}
    for n in store.get(jid)["nodes"]:
        if n["key"] in ("split", "standardize") and n["status"] == "complete":
            for row in read(Path(n["path"]) / "summary.json", []):
                if row.get("reason") and row.get("reason") != "not_body_scan":
                    exclusions[row["asset_id"]] = str(row["reason"])
    product_groups = {
        k: (read(Path(p) / "results.json", []), Path(p))
        for k, p in paths["products"].items()
        if p
    }
    logo = cfg.get("logo_path")
    root = Path(paths["job"]).parent / "input/私教会员案例项目"
    logos = sorted(
        p
        for p in (root / "logo").rglob("*")
        if p.is_file()
        and p.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp", ".svg")
    )
    if logos:
        logo = str(
            sorted(
                logos, key=lambda p: ("白" not in p.name, "镂空" not in p.name, p.name)
            )[0]
        )
    members = []
    for index, group in enumerate(job["groups"], 1):
        mid = f"m{index:03d}"
        directory = group["directory"]
        selected = []
        for label in labels:
            asset = assets.get(label["asset_id"], {})
            belongs = asset.get("directory") == directory or (
                asset.get("store") == group["store"]
                and asset.get("member") == group["member"]
            )
            if belongs and label["asset_id"] in photos:
                selected.append(copy.deepcopy(label))
        table = next(
            (
                t
                for t in tables
                if t["store"] == group["store"] and t["member"] == group["member"]
            ),
            None,
        )
        identity = identities.get(directory, {})
        profile = {
            "name": (table or {}).get("display_member") or group["member"],
            "gender": identity.get("profile", {}).get("gender", ""),
            "coach": identity.get("profile", {}).get("coach") or group.get("coach", ""),
        }
        nick = nickname(profile["name"], profile)
        report = table_report(table)
        cover = compose(profile["name"], nick, report, profile["coach"])
        cover.update(
            badge="会员案例",
            store_text=group["store"],
            address=cfg["address"],
            brand_name=cfg["brand_name"],
            crops={},
        )
        cover = {
            k: v
            for k, v in cover.items()
            if k
            in (
                "title",
                "subtitle",
                "headline",
                "story",
                "badge",
                "store_text",
                "address",
                "brand_name",
                "crops",
            )
        }
        metrics = [
            {
                "text": r["type"] + "：" + str(r["delta"]) + r["unit"],
                "key": r.get("key"),
            }
            for r in (table or {}).get("rows", [])
            if r.get("key") in ("waist", "hip", "arm")
            and str(r.get("delta", "")).strip()
        ]
        vs = {
            k: copy.deepcopy(cfg[k])
            for k in (
                "brand_name",
                "address",
                "before_text",
                "after_text",
                "vs_text",
                "titles",
                "consent_text",
            )
        }
        vs.update(nickname=nick, metrics=metrics)
        published = []
        engine_photos = {}
        engine_meta = {}
        editors = {}
        source_list = []
        for row in selected:
            aid = row["asset_id"]
            row.update(group_id=mid, member=profile["name"])
            file = photos[aid]
            engine_photos[aid] = file
            data = {
                k: row.get(k)
                for k in (
                    "asset_id",
                    "view",
                    "phase",
                    "confidence",
                    "label_kind",
                    "requires_review",
                    "review_flags",
                    "source_sha256",
                )
            }
            data.update(
                media=store.media(jid, file),
                confirmed=not row.get("requires_review"),
                preferred=False,
            )
            if row["view"] == "front" and aid in metadata:
                try:
                    ed = editor(metadata[aid], out / "editors" / f"{aid}.png")
                    editors[aid] = ed
                    data.update(
                        cover_media=store.media(jid, ed["path"]),
                        cover_size=ed["size"],
                        default_crop=ed["default_crop"],
                    )
                except ValueError as e:
                    data["cover_issue"] = str(e)
            if aid in metadata:
                engine_meta[aid] = metadata[aid]
            published.append(data)
        extras = []
        gaps = []
        for kind, (results, folder) in product_groups.items():
            for result in results:
                if result.get("directory") != directory:
                    continue
                for i, p in enumerate(result.get("products", result.get("pages", []))):
                    extras.append(
                        dict(
                            kind=kind,
                            path=str(folder / p["file"]),
                            name=f'{dict(training="会员训练日常",testimonial="会员感言",life="会员生活照")[kind]}-{i+1}'
                            + Path(p["file"]).suffix,
                        )
                    )
                if result.get("reason"):
                    gaps.append(dict(product=kind, reason=result["reason"]))
        for a in audit:
            if original[a["asset_id"]]["directory"] == directory:
                reason = exclusions.get(a["asset_id"])
                source_list.append(
                    dict(
                        asset_id=a["asset_id"],
                        kind=a["qwen"]["kind"],
                        reason=(a["qwen"].get("reason") or "")
                        + ("；未输出：" + reason if reason else ""),
                        media=store.media(jid, a["source"]),
                    )
                )
                if reason:
                    gaps.append(
                        dict(product="体测素材 " + a["asset_id"], reason=reason)
                    )
        report_images = {}
        if table and paths.get("crops"):
            for side in ("before", "after"):
                p = (
                    Path(paths["crops"])
                    / str(table.get("pair", {}).get(side))
                    / "frame.png"
                )
                if p.exists():
                    report_images[side] = str(p)
        if len(report_images) != 2:
            report_images = {}
        reference = (
            [
                report_records.get((table.get("pair") or {}).get(side), {}).get(
                    "source_size", [1080]
                )[0]
                for side in ("before", "after")
            ]
            if table and report_images
            else [
                report_records.get((table or {}).get("table_source_id"), {}).get(
                    "source_size", [1080]
                )[0]
            ]
        )
        report_width = 2 * max(reference)
        table_ui = dict(
            headers=(table or {}).get("headers", HEADERS),
            rows=[
                {
                    k: str(r.get(k) or "")
                    for k in ("type", "key", "before", "after", "delta", "unit")
                }
                for r in select_display_rows((table or {}).get("rows", []))
            ],
            table_title="阶段性训练成果",
            report_title="体测数据 · 前后对比",
            before_label="训练前",
            after_label="训练后",
        )
        members.append(
            dict(
                id=mid,
                store=group["store"],
                directory=directory,
                profile=profile,
                identity={
                    "version": "member-identity-text-v1",
                    **identity.get("evidence", {}),
                    "issue": identity.get("issue"),
                },
                photos=published,
                vs=vs,
                cover=cover,
                table=table_ui,
                sources=source_list,
                gaps=gaps,
                _engine=dict(
                    rows=selected,
                    photos=engine_photos,
                    metadata=engine_meta,
                    editors=editors,
                    table=table,
                    report_images=report_images,
                    report_width=report_width,
                    extras=extras,
                    logo=logo,
                    width=cfg["width"],
                    initial_profile=profile.copy(),
                ),
            )
        )
    save(
        out / "review.json",
        dict(schema="case-studio-review-v1", members=members, excluded=job["excluded"]),
    )


def render(review_path, mid, out, section=None):
    if section not in (None, "vs", "cover", "table"):
        raise ValueError("预览区域无效")
    review = read(review_path)
    m = next(m for m in review["members"] if m["id"] == mid)
    eng = m["_engine"]
    out.mkdir(parents=True, exist_ok=False)
    rows = []
    public = {p["asset_id"]: p for p in m["photos"]}
    for raw in eng["rows"]:
        row = copy.deepcopy(raw)
        p = public[row["asset_id"]]
        row.update(
            phase=p["phase"], view=p["view"], member=m["profile"]["name"], group_id=mid
        )
        row.update(
            label="训练前" if p["phase"] == "before" else "训练后",
            requires_review=not p["confirmed"],
        )
        if p.get("preferred") or p["confirmed"]:
            row.update(
                label_kind="human", confidence=1.0 if p.get("preferred") else 0.99
            )
        rows.append(row)
    plans, gaps, selections = plan(rows)
    lookup = {r["asset_id"]: r for r in rows}
    products = []
    context = dict(m["vs"], width=eng["width"], logo_path=eng.get("logo"))

    def product(path, kind, name, **extra):
        with Image.open(path) as im:
            size = list(im.size)
        products.append(
            dict(
                kind=kind,
                name=name,
                file=str(path),
                size=size,
                sha256=sha(path),
                **extra,
            )
        )

    for p in plans:
        if section is not None and not (section == "vs" and p["kind"] == "vs"):
            continue
        selected = [lookup[a] for a in p["asset_ids"]]
        im = draw_product(p, selected, eng["photos"], FONT, context)
        labels = {"front": "正面", "side": "侧面", "back": "背面", "all": "完整三视图"}
        name = (
            "完整三视图.png"
            if p["kind"] == "three_views"
            else (
                labels[p["view"]] + "对比图.jpg"
                if p["kind"] == "vs"
                else selected[0]["label"]
                + "-"
                + labels[p["view"]]
                + "-"
                + selected[0]["asset_id"]
                + ".jpg"
            )
        )
        file = out / name
        im.save(file, **({"quality": 94} if file.suffix == ".jpg" else {}))
        product(file, p["kind"], name, asset_ids=p["asset_ids"], view=p["view"])
    fronts = next(
        (p for p in plans if p["kind"] == "vs" and p["view"] == "front"), None
    )
    cover_sources = []
    if section in (None, "cover"):
        if fronts and all(a in eng["editors"] for a in fronts["asset_ids"]):
            ids = fronts["asset_ids"]
            metas = [eng["metadata"][a] for a in ids]
            try:
                defaults = plan_pair(metas)
                ims = []
                for aid, meta, frame in zip(ids, metas, defaults):
                    ed = eng["editors"][aid]
                    rect = m["cover"]["crops"].get(aid)
                    image = (
                        manual_frame(meta, ed, rect)
                        if rect
                        else render_frame(meta, frame)[0]
                    )
                    ims.append(Image.fromarray(cv2.cvtColor(image, cv2.COLOR_BGR2RGB)))
                    cover_sources.append(
                        dict(
                            asset_id=aid,
                            crop=rect or crop_from_plan(frame, ed["H"], ed["size"]),
                        )
                    )
                c = m["cover"]
                c = dict(c, segments=[{"text": c["story"], "emphasis": False}])
                im, _ = draw_cover(
                    ims,
                    c,
                    dict(brand_name=c["brand_name"], logo_path=eng.get("logo")),
                    FONT,
                    m["store"],
                )
                file = out / "会员案例封面.jpg"
                im.save(file, quality=94)
                product(file, "cover", file.name, asset_ids=ids)
            except ValueError as e:
                if m["cover"]["crops"]:
                    raise ValueError(
                        "封面取景不可用，请调整到有效原图范围内：" + str(e)
                    )
                gaps.append(dict(product="cover", reason=str(e)))
        else:
            gaps.append(
                dict(
                    product="cover", reason="缺少可用的正面训练前后配对或可靠的肩胯标定"
                )
            )
    if section in (None, "table"):
        if m["table"]["rows"]:
            case = dict(
                eng.get("table") or {"rows": [], "pair": {}},
                **m["table"],
                reviewed_rows=m["table"]["rows"],
            )
            file = out / "体测报告对比.png"
            draw_report(
                case,
                eng["report_images"],
                eng.get("report_width", eng["width"]),
                FONT,
                file,
            )
            product(file, "report", file.name)
        else:
            gaps.append(dict(product="report", reason="没有可输出的表格数据"))
    for e in eng["extras"] if section is None else []:
        file = out / e["name"]
        shutil.copy2(e["path"], file)
        product(file, e["kind"], e["name"])
    result = dict(
        member_id=mid,
        profile=m["profile"],
        store=m["store"],
        products=products,
        gaps=gaps + m["gaps"],
        cover_sources=cover_sources,
        review_required=[p["asset_id"] for p in m["photos"] if not p["confirmed"]],
        model_calls=0,
    )
    save(out / "result.json", result)

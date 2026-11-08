"""Validated review revisions and immutable product versions."""

import copy, math, uuid, zipfile
from pathlib import Path
from .common import read, save, job_dir, cache_dir, clean_name, now, PYTHON, signature
from . import store, presentation, fonts
from .work_cache import lock_for, RENDER_SLOTS

PRODUCT_KINDS = frozenset(
    {
        "three_views",
        "vs",
        "single",
        "cover",
        "report",
        "training",
        "testimonial",
        "life",
    }
)
PROFILE_LIMITS = {"name": 40, "gender": 1, "coach": 40}
VS_LIMITS = {
    "brand_name": 35,
    "address": 70,
    "nickname": 45,
    "consent_text": 80,
    "before_text": 20,
    "after_text": 20,
    "vs_text": 4,
}
COVER_LIMITS = {
    "title": 10,
    "subtitle": 30,
    "headline": 32,
    "story": 280,
    "badge": 6,
    "store_text": 30,
    "address": 30,
    "brand_name": 35,
}


def public(data, preferences=None):
    preferences = preferences or presentation.settings()
    if isinstance(data, dict):
        result = {k: public(v, preferences) for k, v in data.items() if not k.startswith("_")}
        if "_engine" in data and "photos" in data:
            from .privacy import review_state
            result['privacy'] = review_state(data, preferences)
            result.setdefault('fonts', {})
            result['render_settings'] = preferences
            result["preview_keys"] = {
                section: preview_key(data, section, preferences)
                for section in ("vs", "cover", "table", "three_views")
            }
        return result
    if isinstance(data, list):
        return [public(v, preferences) for v in data]
    return data


def text(value, limit):
    if (
        not isinstance(value, str)
        or len(value) > limit
        or any(ord(c) < 32 and c not in "\n\t" for c in value)
    ):
        raise ValueError("文字格式不正确或过长")
    return value


def fields(value, limits):
    if not isinstance(value, dict) or set(value) != set(limits):
        raise ValueError("字段不完整或包含不支持的字段")
    return {k: text(value[k], n) for k, n in limits.items()}


def honorific(profile):
    name = profile["name"]
    surnames = (
        "欧阳",
        "司马",
        "上官",
        "诸葛",
        "夏侯",
        "东方",
        "皇甫",
        "尉迟",
        "公孙",
        "慕容",
        "司徒",
        "司空",
    )
    import re

    surname = (
        next((s for s in surnames if name.startswith(s)), name[:1])
        if re.fullmatch(r"[\u3400-\u9fff]+", name)
        else name
    )
    return surname + {"男": "先生", "女": "女士"}.get(profile["gender"], "会员")


def sync_profile(member, old):
    if old["profile"] != member["profile"]:
        before = honorific(old["profile"])
        after = honorific(member["profile"])
        # The nickname always follows member identity; custom surrounding copy is retained.
        member["vs"]["nickname"] = after
        for key in ("title", "subtitle", "headline", "story"):
            member["cover"][key] = member["cover"][key].replace(before, after)
        if (
            old["profile"]["coach"]
            and old["profile"]["coach"] != member["profile"]["coach"]
        ):
            member["cover"]["story"] = member["cover"]["story"].replace(
                old["profile"]["coach"] + " 教练",
                (
                    (member["profile"]["coach"] + " 教练")
                    if member["profile"]["coach"]
                    else "教练"
                ),
            )


def update(jid, mid, payload):
    expected = payload.get("version")
    data = store.review(jid)
    if data["version"] != expected:
        raise store.Conflict("审核内容已更新，请刷新后重试")
    member = next((m for m in data["members"] if m["id"] == mid), None)
    if not member:
        raise KeyError("会员不存在")
    incoming = payload.get("member", {})
    if set(incoming) - {"profile", "photos", "vs", "cover", "table", "privacy", "fonts"}:
        raise ValueError("不支持修改该字段")
    old = copy.deepcopy(member)
    if "profile" in incoming:
        p = fields(incoming["profile"], PROFILE_LIMITS)
        if not p["name"].strip() or p["gender"] not in ("", "男", "女"):
            raise ValueError("请填写会员名，性别请选择男、女或未设置")
        manual = member["_engine"].setdefault("manual_profile", {})
        for field in PROFILE_LIMITS:
            if old["profile"][field] != p[field]:
                manual[field] = True
                if field in member.get("identity", {}):
                    member["identity"][field]["status"] = "manual"
        member["profile"] = p
    if "photos" in incoming:
        values = incoming["photos"]
        lookup = {p["asset_id"]: p for p in member["photos"]}
        if (
            not isinstance(values, list)
            or len(values) != len(lookup)
            or {p.get("asset_id") for p in values} != set(lookup)
        ):
            raise ValueError("照片集合不能增加或删除")
        for p in values:
            if (
                set(p) != {"asset_id", "phase", "view", "confirmed", "preferred"}
                or p["phase"] not in ("before", "after")
                or p["view"] not in ("front", "side", "side_left", "side_right", "back")
                or type(p["confirmed"]) is not bool
                or type(p["preferred"]) is not bool
            ):
                raise ValueError("照片标记无效")
            lookup[p["asset_id"]].update(p)
        # Only one preferred photo per phase and view family.
        slots = set()
        for p in values:
            slot = (p["phase"], "side" if p["view"].startswith("side") else p["view"])
            if p["preferred"] and slot in slots:
                raise ValueError("同阶段同朝向只能有一张首选图")
            if p["preferred"]:
                slots.add(slot)
    if "vs" in incoming:
        v = incoming["vs"]
        result = fields({k: v[k] for k in VS_LIMITS}, VS_LIMITS)
        if set(v) != set(VS_LIMITS) | {"titles", "metrics"}:
            raise ValueError("对比图字段无效")
        result["titles"] = fields(v["titles"], dict(front=20, side=20, back=20))
        if not isinstance(v["metrics"], list) or len(v["metrics"]) > 6:
            raise ValueError("最多展示 6 项围度文字")
        result["metrics"] = [
            {"text": text(x["text"], 35), "key": text(x.get("key") or "", 30)}
            for x in v["metrics"]
        ]
        member["vs"] = result
    if "cover" in incoming:
        c = incoming["cover"]
        result = fields({k: c[k] for k in COVER_LIMITS}, COVER_LIMITS)
        if set(c) != set(COVER_LIMITS) | {"crops"}:
            raise ValueError("封面字段无效")
        crops = c["crops"]
        known = member["_engine"]["editors"]
        if not isinstance(crops, dict) or set(crops) - set(known):
            raise ValueError("封面照片无效")
        for aid, rect in crops.items():
            if (
                not isinstance(rect, list)
                or len(rect) != 4
                or any(
                    type(v) not in (float, int) or not math.isfinite(v) for v in rect
                )
            ):
                raise ValueError("取景框无效")
            x, y, w, h = rect
            if min(x, y) < 0 or min(w, h) <= 0 or x + w > 1.000001 or y + h > 1.000001:
                raise ValueError("取景框不能超出图片")
            sw, sh = known[aid]["size"]
            if abs(w * sw / (h * sh) - 500 / 478) > 0.003:
                raise ValueError("取景框比例必须为 500:478")
        result["crops"] = copy.deepcopy(crops)
        member["cover"] = result
    if "table" in incoming:
        t = incoming["table"]
        if set(t) != {
            "headers",
            "rows",
            "table_title",
            "report_title",
            "before_label",
            "after_label",
        }:
            raise ValueError("表格字段无效")
        if not isinstance(t["headers"], list) or len(t["headers"]) != 5:
            raise ValueError("表格必须有五列")
        if not isinstance(t["rows"], list) or len(t["rows"]) > 20:
            raise ValueError("固定高度表格最多展示 20 行")
        member["table"] = {
            k: text(t[k], 30)
            for k in ("table_title", "report_title", "before_label", "after_label")
        }
        member["table"]["headers"] = [text(v, 30) for v in t["headers"]]
        member["table"]["rows"] = [
            fields(r, dict(type=24, key=40, before=40, after=40, delta=40, unit=20))
            for r in t["rows"]
        ]
    if "privacy" in incoming:
        from .privacy import validate_update
        member["privacy"] = validate_update(member, incoming["privacy"])
    if "fonts" in incoming:
        member["fonts"] = fonts.validate_map(incoming["fonts"], member.get("fonts"))
    sync_profile(member, old)
    return store.save_review(jid, data, expected)


def output_public(jid, result, preview=False):
    result = copy.deepcopy(result)
    for p in result["products"]:
        path = Path(p.pop("file"))
        if preview:
            from PIL import Image
            thumb = path.with_name(path.name + '.preview.jpg')
            if not thumb.exists():
                with Image.open(path) as image:
                    image = image.convert('RGB')
                    image.thumbnail((1440, 1920), Image.Resampling.LANCZOS)
                    image.save(thumb, quality=88)
            path = thumb
        p["media"] = store.media(jid, path)
    return result


def preview_key(member, section, preferences=None):
    if section not in ("vs", "cover", "table", "three_views"):
        raise ValueError("预览区域无效")
    engine = member["_engine"]
    data = {
        "renderer": presentation.VERSION,
        "presentation": preferences or presentation.settings(),
        "fonts": {k:v for k,v in member.get('fonts', {}).items() if k.startswith(section+'.')},
        "section": section,
        "values": member.get(section, {}),
    }
    if section in ("vs", "cover", "three_views"):
        from .privacy import RENDER_VERSION
        data["privacy_renderer"] = RENDER_VERSION
        data["privacy"] = member.get("privacy", {"enabled": True})
        data["mask_edits"] = {k: v for k, v in member.get("mask_edits", {}).items() if k.split(":")[0] == section}
        data["face_evidence"] = engine.get("privacy", {})
        data["photos"] = [
            {
                k: p.get(k)
                for k in ("asset_id", "phase", "view", "confirmed", "preferred")
            }
            for p in member["photos"]
        ]
        data["sources"] = {k: engine.get(k) for k in ("rows", "photos", "logo")}
        if section in ("vs", "three_views"):
            data["width"] = engine.get("width")
        else:
            data["geometry"] = {k: engine.get(k) for k in ("metadata", "editors")}
            data["store"] = member.get("store")
    else:
        data["sources"] = {
            k: engine.get(k) for k in ("table", "report_images", "report_width")
        }
    return signature(data)


def preview_latest(jid, mid):
    data = store.review(jid)
    member = next((m for m in data["members"] if m["id"] == mid), None)
    if not member:
        raise KeyError("会员不存在")
    latest = store.latest_previews(jid, mid)
    return {
        "review_version": data["version"],
        "keys": {s: preview_key(member, s) for s in ("vs", "cover", "table", "three_views")},
        "sections": latest,
    }


def section_preview(jid, mid, version, section):
    from .workflow import command

    data = presentation.freeze(store.review(jid, version))
    member = next((m for m in data["members"] if m["id"] == mid), None)
    if not member:
        raise KeyError("会员不存在")
    key = preview_key(member, section, data['_render_settings'])
    root = cache_dir(jid) / "previews-v3" / mid
    base = root / section / key
    with lock_for(str(base)):
        base.mkdir(parents=True, exist_ok=True)
        dest = base / "output"
        cached = (dest / "result.json").exists()
        if not cached:
            if dest.exists():
                import shutil

                shutil.rmtree(dest)
            save(base / "review.json", data, True)
            with RENDER_SLOTS:
                command(
                    jid,
                    [PYTHON, "-m", "studio.bridge", "render", base / "review.json", mid, dest, section],
                    base / "render.log",
                )
        result = dict(
            output_public(jid, read(dest / "result.json"), preview=True),
            section=section,
            fingerprint=key,
            review_version=version,
            cached=cached,
        )
        # A slow render from an older tab must not replace the latest pointer.
        store.set_latest_preview(jid, mid, section, result, version)
        return result


def preview(jid, mid, version, section=None):
    if section is not None:
        return section_preview(jid, mid, version, section)
    from .workflow import command
    from .privacy import RENDER_VERSION

    with lock_for((jid, mid, version, 'full-preview')), RENDER_SLOTS:
        review = presentation.freeze(store.review(jid, version))
        if mid not in {m["id"] for m in review["members"]}:
            raise KeyError("会员不存在")
        style_key = signature({'settings': review['_render_settings'], 'renderer':presentation.VERSION})
        base = cache_dir(jid) / "previews" / str(version) / RENDER_VERSION / style_key / mid
        base.mkdir(parents=True, exist_ok=True)
        save(base / "review.json", review, True)
        dest = base / mid
        if not (dest / "result.json").exists():
            if dest.exists():
                import shutil

                shutil.rmtree(dest)
            command(
                jid,
                [
                    PYTHON,
                    "-m",
                    "studio.bridge",
                    "render",
                    base / "review.json",
                    mid,
                    dest,
                ],
                base / (mid + ".log"),
            )
        return dict(
            output_public(jid, read(dest / "result.json"), preview=True), review_version=version
        )


def render_version(jid, review_version):
    from .workflow import command

    review = presentation.freeze(store.review(jid, review_version))
    vid = now().replace(":", "").replace(".", "") + "-" + uuid.uuid4().hex[:6]
    base = job_dir(jid) / "versions" / vid
    base.mkdir(parents=True)
    save(base / "review.json", review, True)
    results = []
    for i, m in enumerate(review["members"]):
        dest = base / m["id"]
        command(
            jid,
            [
                PYTHON,
                "-m",
                "studio.bridge",
                "render",
                base / "review.json",
                m["id"],
                dest,
            ],
            base / (m["id"] + ".log"),
        )
        results.append(output_public(jid, read(dest / "result.json")))
        store.patch(jid, progress=round((i + 1) / len(review["members"]) * 100))
    result = dict(
        id=vid, review_version=review_version, created_at=now(), members=results,
        render_settings=review['_render_settings'], renderer=presentation.VERSION,
    )
    save(base / "result.json", result)
    return result


def archive(jid, vid, mid=None, kinds=None):
    if kinds is not None:
        if (
            not isinstance(kinds, (list, tuple))
            or not kinds
            or not all(isinstance(k, str) and k in PRODUCT_KINDS for k in kinds)
        ):
            raise ValueError("请选择至少一种有效的成品图类型")
        kinds = sorted(set(kinds))
    version = store.version(jid, vid)
    members = [m for m in version["members"] if not mid or m["member_id"] == mid]
    if not members:
        raise KeyError("会员不存在")
    if kinds is not None:
        members = [
            dict(m, products=[p for p in m["products"] if p.get("kind") in kinds])
            for m in members
        ]
        members = [m for m in members if m["products"]]
        if not members:
            raise ValueError("当前范围内没有所选类型的成品图，请调整选择")
    suffix = "-types-" + signature(kinds)[:20] if kinds is not None else ""
    path = job_dir(jid) / "downloads" / f'{vid}-{mid or "all"}{suffix}.zip'
    path.parent.mkdir(exist_ok=True)
    if not path.exists():
        used = set()
        temp = path.with_suffix("." + uuid.uuid4().hex + ".tmp")
        with zipfile.ZipFile(temp, "w", zipfile.ZIP_DEFLATED, compresslevel=2) as z:
            for m in members:
                directory = clean_name(
                    (m["profile"]["coach"] or "未填写教练") + "-" + m["profile"]["name"]
                )
                prefix = Path(clean_name(m["store"])) / directory
                if str(prefix) in used:
                    prefix = prefix.with_name(directory + "-" + m["member_id"])
                used.add(str(prefix))
                for p in m["products"]:
                    z.write(
                        store.media_file(jid, p["media"]),
                        str((Path() if mid else prefix) / clean_name(p["name"])),
                    )
                z.writestr(
                    str((Path() if mid else prefix) / "审核说明.json"),
                    __import__("json").dumps(
                        {
                            "needs_review": m["review_required"],
                            "gaps": m["gaps"],
                            "review_version": version["review_version"],
                            "face_privacy": m.get("privacy", {"status": "legacy_version"}),
                            "mask_edits": m.get("mask_edits", {}),
                        },
                        ensure_ascii=False,
                        indent=2,
                    ),
                )
                from .stickers import BUNDLED
                attribution = BUNDLED / "ATTRIBUTION.txt"
                if m.get("privacy", {}).get("enabled") and attribution.exists():
                    z.write(attribution, str((Path() if mid else prefix) / "贴纸素材说明.txt"))
        temp.replace(path)
    name = (
        clean_name(
            ((members[0]["profile"]["coach"] or "未填写教练") + "-")
            + members[0]["profile"]["name"]
        )
        if mid
        else "会员案例成品"
    )
    return path, name + ".zip"

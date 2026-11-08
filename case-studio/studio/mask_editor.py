"""Authenticated per-product sticker editing, bound to exact render geometry."""

import copy, math, shutil
from PIL import Image
from . import store, review, stickers
from .common import cache_dir, read, save, signature, PYTHON, clean_name
from .work_cache import lock_for, EDITOR_SLOTS

SECTIONS = ("three_views", "vs", "cover")


def capture(member, scope, panels, layout, out):
    folder = out / "mask-editor" / clean_name(scope)
    folder.mkdir(parents=True, exist_ok=True)
    photos = {p["asset_id"]: p for p in member["photos"]}
    records = []
    for index, (panel, info) in enumerate(zip(panels, layout["panels"])):
        file = folder / f"{index}.jpg"
        thumbnail = panel["image"].convert("RGB")
        thumbnail.thumbnail((640, 900), Image.Resampling.LANCZOS)
        thumbnail.save(file, quality=86)
        photo = photos[panel["asset_id"]]
        records.append(dict(info, file=str(file), phase=photo["phase"], view=photo["view"]))
    return dict(scope=scope, panels=records)


def capture_sticker(member, out):
    with Image.open(stickers.get(member["privacy"]["sticker_id"])["path"]) as im:
        im = im.convert("RGBA")
        im = im.crop(im.getchannel("A").getbbox())
        im.thumbnail((512, 512), Image.Resampling.LANCZOS)
        file = out / "mask-editor-sticker.png"
        im.save(file)
    return str(file)


def geometry_key(member, section):
    from .privacy import RENDER_VERSION
    engine = member['_engine']
    return signature({
        'editor': 'mask-editor-v2-thumbnails', 'renderer': RENDER_VERSION, 'section': section,
        'sticker': member['privacy']['sticker_id'],
        'photos': [{k:p.get(k) for k in ('asset_id','phase','view','confirmed','preferred')} for p in member['photos']],
        'sources': {k:engine.get(k) for k in ('rows','photos','privacy','metadata')},
        'width': engine.get('width') if section == 'vs' else None,
        'metrics': len(member['vs']['metrics']) if section == 'vs' else None,
        'cover': {'editors': engine.get('editors'), 'crops': member['cover']['crops']} if section == 'cover' else None,
    })


def context(jid, mid, version, section):
    if section not in SECTIONS:
        raise ValueError("不支持该遮罩审核区域")
    data = store.review(jid)
    if type(version) is not int or data["version"] != version:
        raise store.Conflict("审核内容已更新，请关闭弹窗后重新打开")
    member = next((m for m in data["members"] if m["id"] == mid), None)
    if not member:
        raise KeyError("会员不存在")
    p = member.get("privacy", {})
    if p.get("enabled") is False or not p.get("sticker_id") or p.get("status") != "ready":
        raise ValueError("请先开启并准备本会员的头部遮挡")
    key = geometry_key(member, section)
    base = cache_dir(jid) / "mask-editors" / mid / section / key
    return data, member, key, base


def load(jid, mid, version, section):
    from .workflow import command
    data, member, key, base = context(jid, mid, version, section)
    dest = base / "output"
    with lock_for(str(base)):
        if not (dest / "editor.json").exists():
            if dest.exists():
                shutil.rmtree(dest)
            neutral = copy.deepcopy(data)
            selected = next(m for m in neutral['members'] if m['id'] == mid)
            selected['mask_edits'] = {}
            selected['privacy']['mask_back'] = True
            save(base / "review.json", neutral, True)
            with EDITOR_SLOTS:
                command(jid, [PYTHON, "-m", "studio.bridge", "render", base / "review.json", mid,
                              dest, section, "edit"], base / "render.log")
        result = copy.deepcopy(read(dest / "editor.json"))
    # A render finishing after another reviewer saved cannot edit that old revision.
    context(jid, mid, version, section)
    for group in result["groups"]:
        for panel in group["panels"]:
            from .privacy_panels import apply_manual_layout
            for face in panel['faces']:
                apply_manual_layout(member, group['scope'], panel, face)
            panel["media"] = store.media(jid, panel.pop("file"))
    result["sticker_media"] = store.media(jid, result.pop("sticker_file"))
    return dict(result, version=version, section=section, fingerprint=key)


def update(jid, mid, payload):
    if not isinstance(payload, dict) or set(payload) != {"version", "section", "fingerprint", "edits"}:
        raise ValueError("遮罩修改参数无效")
    data, member, key, base = context(jid, mid, payload["version"], payload["section"])
    if payload["fingerprint"] != key or not (base / "output/editor.json").exists():
        raise store.Conflict("取景或遮罩设置已更新，请重新打开调整面板")
    manifest = read(base / "output/editor.json")
    known = {(g["scope"], p["asset_id"], f["source_face"]): (p, f)
             for g in manifest["groups"] for p in g["panels"] for f in p["faces"]}
    incoming = payload["edits"]
    if not isinstance(incoming, list) or len(incoming) != len(known):
        raise ValueError("遮罩集合不完整，请重新打开调整面板")
    updates, seen = {}, set()
    for edit in incoming:
        if not isinstance(edit, dict) or set(edit) != {"scope", "asset_id", "face", "position", "deleted"}:
            raise ValueError("遮罩字段无效")
        if (not isinstance(edit["scope"], str) or not isinstance(edit["asset_id"], str)
                or type(edit["face"]) is not int or type(edit["deleted"]) is not bool):
            raise ValueError("遮罩标识无效")
        target = (edit["scope"], edit["asset_id"], edit["face"])
        if target not in known or target in seen:
            raise ValueError("遮罩不属于当前照片或出现重复")
        seen.add(target)
        panel, face = known[target]
        pos = edit["position"]
        if pos is not None:
            if (not isinstance(pos, list) or len(pos) != 2 or
                    any(type(v) not in (int, float) or not math.isfinite(v) for v in pos)):
                raise ValueError("遮罩位置无效")
            w, h = panel["size"]
            sw, sh = face["sticker_size"]
            if not (0 <= pos[0] <= 1-sw/w+1e-6 and 0 <= pos[1] <= 1-sh/h+1e-6):
                raise ValueError("头像不能移出照片边界")
        if pos is not None or edit["deleted"]:
            record = updates.setdefault(edit["scope"], {}).setdefault(edit["asset_id"],
                       {"signature": panel["signature"], "faces": {}})
            record["faces"][str(edit["face"])] = {"position": pos, "deleted": edit["deleted"]}
    old = member.setdefault("mask_edits", {})
    for scope in list(old):
        if scope.split(":")[0] == payload["section"]:
            del old[scope]
    old.update(updates)
    return store.save_review(jid, data, payload["version"])

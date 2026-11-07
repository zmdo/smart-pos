"""Tagged bundled stickers and immutable member-specific API avatars."""

import re, secrets, shutil
from pathlib import Path
from .common import APP_ROOT, WEB_DATA, read, save, sha

BUNDLED = APP_ROOT / "assets/stickers"


def catalog():
    return read(BUNDLED / "catalog.json", [])


def get(sid):
    if not isinstance(sid, str) or not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,90}", sid):
        raise ValueError("贴纸编号无效")
    item = next((s for s in catalog() if s["id"] == sid), None)
    if item:
        return dict(item, path=str(BUNDLED / item["file"]))
    item = read(WEB_DATA / "stickers" / sid / "metadata.json", {})
    if not item or item.get("id") != sid:
        raise KeyError("贴纸不存在")
    return dict(item, path=str(WEB_DATA / "stickers" / sid / "avatar.png"))


def public(item):
    return {k: v for k, v in item.items() if k not in ("file", "path", "trace")}


def default(gender):
    return get({"男": "ai-standard-male", "女": "ai-standard-female"}.get(gender, "ai-standard-neutral"))


def random_sticker(gender):
    tag = {"男": "male", "女": "female"}.get(gender, "neutral")
    choices = [s for s in catalog() if s.get("gender", "neutral") in ("neutral", tag)]
    if not choices:
        raise RuntimeError("贴纸库尚未初始化")
    return get(secrets.choice(choices)["id"])


def register(path, trace, gender=""):
    sid = "ai-" + sha(path)[:40]
    folder = WEB_DATA / "stickers" / sid
    folder.mkdir(parents=True, exist_ok=True)
    if not (folder / "avatar.png").exists():
        shutil.copy2(path, folder / "avatar.png")
    item = {"id": sid, "name": "会员专属 AI 头像", "tags": ["AI头像", "3D卡通", "透明"],
            "gender": {"男": "male", "女": "female"}.get(gender, "neutral"),
            "source": "Qwen Image API", "license": "API generated", "trace": trace}
    save(folder / "metadata.json", item, True)
    return get(sid)

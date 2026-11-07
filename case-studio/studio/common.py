"""Filesystem and JSON primitives for the new application."""

import hashlib, json, os, re, uuid
from datetime import datetime, timezone
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[1]
REPO = Path(os.environ.get("STUDIO_REPO", APP_ROOT.parent)).resolve()
DATA = Path(os.environ.get("CASE_DATA", "/root/autodl-fs/case-studio")).resolve()
WEB_DATA = DATA / "website"
PYTHON = os.environ.get(
    "CASE_PYTHON", "/root/apps/non-grid-calibration/.venv/bin/python"
)
FONT = Path(os.environ.get("CASE_FONT", str(DATA / "fonts/NotoSansSC.ttf")))
PUBLIC_URL = os.environ.get(
    "STUDIO_PUBLIC_URL", "https://uu55868-793909b1c426.weste.seetacloud.com:8443"
)


def now():
    return datetime.now(timezone.utc).isoformat()


def read(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        if default is not None:
            return default
        raise


def save(path, value, private=False):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    tmp.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    if private:
        tmp.chmod(0o600)
    tmp.replace(path)


def sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def signature(value):
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, ensure_ascii=False, separators=(",", ":")
        ).encode()
    ).hexdigest()


def clean_name(value):
    return (
        re.sub(r'[\x00-\x1f/\\:"<>|?*]', "_", str(value))[:100].strip(" .") or "未命名"
    )


def job_dir(jid):
    if not re.fullmatch(r"[a-f0-9]{24}", jid):
        raise ValueError("任务不存在")
    return WEB_DATA / "jobs" / jid


def contained(path, root):
    path = Path(path).resolve()
    if not path.is_relative_to(Path(root).resolve()):
        raise ValueError("文件不属于当前数据目录")
    return path

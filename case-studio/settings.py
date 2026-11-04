import json, os, secrets
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = Path(os.environ.get("CASE_DATA", "/root/autodl-fs/case-studio"))
DATA.mkdir(parents=True, exist_ok=True)
SETTINGS = DATA / "settings.json"
BATCHES = DATA / "batches"
CACHE = DATA / "cache"
LOGS = DATA / "logs"
for p in (BATCHES, CACHE, LOGS):
    p.mkdir(parents=True, exist_ok=True)

DEFAULT = {
    "access_token": None,          # 首次启动自动生成
    "base_url": "https://api.deepseek.com",
    "model": "deepseek-flash",
    "api_key": "",
    "classify_concurrency": 3,
    "dedup_phash_distance": 6,
    "quality": {"sharpness": 20, "mean_dark": 30, "mean_bright": 245, "clip_ratio": 0.8,
                "subject_ratio": 0.02, "min_side": 640},
    "retain_days": 30,
}


def _load_portrait_vision() -> dict:
    """拉起服务时若是首次，从已有的 portrait-studio 配置里继承模型凭据，省一次手工配置。"""
    try:
        src = Path("/root/autodl-fs/portrait-studio/settings.json")
        if src.exists():
            j = json.loads(src.read_text())
            return {"base_url": j.get("base_url", DEFAULT["base_url"]),
                    "model": j.get("model", DEFAULT["model"]),
                    "api_key": j.get("api_key", "")}
    except Exception:
        pass
    return {}


def load() -> dict:
    if SETTINGS.exists():
        data = json.loads(SETTINGS.read_text())
    else:
        data = dict(DEFAULT)
        data.update(_load_portrait_vision())
        data["access_token"] = secrets.token_urlsafe(12)
        save(data)
    merged = dict(DEFAULT)
    merged.update(data)
    return merged


def save(data: dict) -> None:
    tmp = SETTINGS.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    os.chmod(tmp, 0o600)
    tmp.replace(SETTINGS)

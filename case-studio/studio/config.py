import copy, secrets, threading, re
from urllib.parse import urlparse
from .common import DATA, WEB_DATA, read, save

LOCK = threading.RLock()
DEFAULTS = {
    "brand_name": "UP 健身私教馆",
    "address": "UP 健身私教馆",
    "width": 1080,
    "output_width": 1080,
    "output_background": "#F3F0EA",
    "default_font": "noto-sans-sc",
    "font_overrides": {},
    "mask_lifestyle": False,
    "display_width": 768,
    "consent_text": "*案例真实有效，经会员本人同意使用",
    "before_text": "Before",
    "after_text": "After",
    "vs_text": "VS",
    "titles": {"front": "体测正视图", "side": "体测侧视图", "back": "体测后视图"},
    "logo_path": None,
    "model": {"base_url": "", "model": "", "api_key": ""},
    "image_model": {"base_url": "https://maas.qianwenaiapi.com/api/v1",
                    "model": "qwen-image-2.1-pro", "api_key": "", "reuse_model_key": True},
    "model_workers": 3,
    "gender_confidence_threshold": 0.90,
}


def load():
    with LOCK:
        path = WEB_DATA / "settings.json"
        if not path.exists():
            previous = read(DATA / "settings.json", {})
            provider = read(DATA / "private/qwen3.8-max-eval.json", {})
            result = copy.deepcopy(DEFAULTS)
            result["model"] = {
                k: provider.get(k, "") for k in ("base_url", "model", "api_key")
            }
            result["access_token"] = previous.get(
                "access_token"
            ) or secrets.token_urlsafe(18)
            result["session_secret"] = secrets.token_hex(32)
            save(path, result, True)
        result = read(path)
        for key, default in DEFAULTS.items():
            result.setdefault(key, copy.deepcopy(default))
        return result


def public(config=None):
    result = copy.deepcopy(config or load())
    result.pop("access_token", None)
    result.pop("session_secret", None)
    result["model"]["key_configured"] = bool(result["model"].pop("api_key", None))
    result["image_model"]["key_configured"] = bool(result["image_model"].pop("api_key", None))
    result["logo_configured"] = bool(result.pop("logo_path", None))
    return result


def update(values):
    with LOCK:
        cfg = load()
        allowed = set(DEFAULTS) - {"logo_path"}
        if set(values) - allowed - {"clear_api_key"}:
            raise ValueError("存在不支持的设置字段")
        for key, value in values.items():
            if key in (
                "brand_name",
                "address",
                "consent_text",
                "before_text",
                "after_text",
                "vs_text",
            ):
                if not isinstance(value, str) or len(value) > 120:
                    raise ValueError("设置文字过长")
                cfg[key] = value
            elif key == "output_width":
                if type(value) is not int or not 540 <= value <= 2160 or value % 3:
                    raise ValueError("成品宽度须为 540–2160 内的 3 的倍数，高度自动按 3:4 计算")
                cfg[key] = value
            elif key == "output_background":
                if not isinstance(value, str) or not re.fullmatch(r'#[0-9a-fA-F]{6}', value):
                    raise ValueError("背景色必须为 #RRGGBB 格式")
                cfg[key] = value.upper()
            elif key == "mask_lifestyle":
                if type(value) is not bool:
                    raise ValueError("生活照遮挡设置无效")
                cfg[key] = value
            elif key == "default_font":
                from . import fonts
                fonts.get(value, active=True)
                cfg[key] = value
            elif key == "font_overrides":
                from . import fonts
                cfg[key] = fonts.validate_map(value, cfg.get(key))
            elif key in ("width", "display_width", "model_workers"):
                bounds = {
                    "width": (540, 2160),
                    "display_width": (512, 1080),
                    "model_workers": (1, 4),
                }[key]
                if type(value) != int or not bounds[0] <= value <= bounds[1]:
                    raise ValueError("尺寸或并发数超出允许范围")
                cfg[key] = value
            elif key == "gender_confidence_threshold":
                if type(value) not in (int, float) or not 0.5 <= value <= 0.99:
                    raise ValueError("性别采用阈值应在 0.50 到 0.99 之间")
                cfg[key] = value
            elif key == "titles":
                if (
                    not isinstance(value, dict)
                    or set(value) != {"front", "side", "back"}
                    or any(
                        not isinstance(v, str) or len(v) > 40 for v in value.values()
                    )
                ):
                    raise ValueError("朝向标题格式错误")
                cfg[key] = value
            elif key == "model":
                if not isinstance(value, dict) or set(value) - {
                    "base_url",
                    "model",
                    "api_key",
                    "key_configured",
                }:
                    raise ValueError("模型设置格式错误")
                for k in ("base_url", "model", "api_key"):
                    if k in value:
                        if not isinstance(value[k], str) or len(value[k]) > 2048:
                            raise ValueError("模型设置格式错误")
                        if k != "api_key" or value[k].strip():
                            cfg["model"][k] = value[k].strip()
                u = urlparse(cfg["model"]["base_url"])
                if cfg["model"]["base_url"] and (
                    u.scheme not in ("https", "http")
                    or not u.hostname
                    or u.username
                    or u.password
                ):
                    raise ValueError("模型 Base URL 无效")
            elif key == "image_model":
                if not isinstance(value, dict) or set(value) - {"base_url", "model", "api_key", "reuse_model_key", "key_configured"}:
                    raise ValueError("生图模型设置格式错误")
                for k in ("base_url", "model", "api_key"):
                    if k in value:
                        if not isinstance(value[k], str) or len(value[k]) > 2048:
                            raise ValueError("生图模型设置格式错误")
                        if k != "api_key" or value[k].strip():
                            cfg["image_model"][k] = value[k].strip()
                if "reuse_model_key" in value:
                    if type(value["reuse_model_key"]) is not bool:
                        raise ValueError("共用 Key 设置无效")
                    cfg["image_model"]["reuse_model_key"] = value["reuse_model_key"]
                u = urlparse(cfg["image_model"]["base_url"])
                if u.scheme != "https" or not u.hostname or u.username or u.password or u.query or u.fragment:
                    raise ValueError("生图 Base URL 必须是有效 HTTPS API 地址")
                if cfg["image_model"]["model"] not in ("qwen-image-2.1-pro", "qwen-image-2.1-turbo"):
                    raise ValueError("请选择支持原生透明通道的 Qwen Image 2.1 模型")
        if values.get("clear_api_key"):
            cfg["model"]["api_key"] = ""
        save(WEB_DATA / "settings.json", cfg, True)
        return public(cfg)


def set_logo(path):
    with LOCK:
        cfg = load()
        cfg["logo_path"] = str(path) if path else None
        save(WEB_DATA / "settings.json", cfg, True)
    return public(cfg)


def snapshot():
    value = load()
    return {k: copy.deepcopy(value[k]) for k in DEFAULTS}

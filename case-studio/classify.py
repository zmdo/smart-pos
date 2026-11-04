"""素材分类：DeepSeek-V4.1-Flash 视觉，按 sha256 缓存，3–4 并发。"""
import base64, io, json, os, time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
from PIL import Image

from settings import CACHE

PROMPT_VERSION = "cls-v2"

SYSTEM = """你是健身门店会员案例素材的分类器。只看图片内容，不推测意图。
把图片归入下列一类（只输出 JSON）：

kind:
- body_scan      体测图：单人全身站立（或前后两人并排站立），地面/墙上常有网格、身高刻度尺；男会员多赤膊、女会员多穿运动内衣
- body_report    体测报告：InBody 等打印单的翻拍/截图，画面里有大量表格、条形图、人体成分分析字样
- training_report 训练成果报告：白纸文档页，标题含"UP健身会员阶段性训练成果报告"，正文是文字+数据表
- daily_training 日常训练图：健身房里做动作（器械、杠铃、哑铃、拉伸），背景是健身房
- life_photo     生活照：日常生活/旅游/聚餐/合影，背景不是健身房
- testimonial    会员感言：微信聊天截图（深色背景、聊天气泡、输入框、状态栏）
- other          以上都不是

字段：
kind             上面 7 个之一
view             仅 body_scan：front 正面 / side_left 左侧面（看到人物左侧身躯、左肩左耳朝镜头）/ side_right 右侧面 / side 侧面但分不清左右 / back 背面；其他类别给 null
background       仅 body_scan：拍摄背景，grid_board 网格板或身高刻度墙 / white_wall 白墙 / wood 木板或木纹墙 / mirror 镜面或玻璃 / outdoor 户外 / other 其他；其他类别给 null
phase            仅 body_scan：before 训练前 / after 训练后 / both 一张里前后两人同框；单人照判不出给 unknown；其他给 null
people           画面里"需要当作案例主体"的人数（0-5）
already_masked   脸是否已经被卡通贴纸/表情包遮住（true/false）
is_screenshot    是否是手机截图（状态栏/聊天气泡/纯色边）
confidence       0-1，你对 kind 判断的把握
reason           20 字以内中文说明依据

只输出 JSON，不要 markdown，不要解释。"""

USER = "判断这张图片。"


def _encode(img: Image.Image, max_side=768) -> str:
    im = img.copy()
    im.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, format="JPEG", quality=85)
    return base64.b64encode(buf.getvalue()).decode()


def _cache_path(sha: str) -> Path:
    return CACHE / "classify" / sha[:2] / f"{sha}.json"


def cached(sha: str):
    p = _cache_path(sha)
    if p.exists():
        try:
            j = json.loads(p.read_text())
            if j.get("prompt_version") == PROMPT_VERSION:
                return j
        except Exception:
            return None
    return None


def call_vlm(img_b64: str, cfg: dict) -> dict:
    payload = {
        "model": cfg["model"],
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": [
                {"type": "text", "text": USER},
                {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + img_b64}},
            ]},
        ],
        "response_format": {"type": "json_object"},
        "max_tokens": 500,
        "temperature": 0,
        "thinking": {"type": "disabled"},
    }
    last = None
    for attempt in range(3):
        try:
            with httpx.Client(timeout=httpx.Timeout(60, connect=15), trust_env=False) as c:
                r = c.post(cfg["base_url"].rstrip("/") + "/chat/completions",
                           headers={"Authorization": "Bearer " + cfg["api_key"]}, json=payload)
            if r.status_code in (401, 403):
                raise RuntimeError("鉴权失败，请检查 API Key")
            if r.status_code == 402:
                raise RuntimeError("余额不足")
            if r.status_code in (429, 500, 502, 503, 504):
                last = f"HTTP {r.status_code}"
                time.sleep(2 ** attempt)
                continue
            if r.status_code != 200:
                raise RuntimeError(f"HTTP {r.status_code}")
            raw = r.json()["choices"][0]["message"]["content"].strip()
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[1].rsplit("```", 1)[0]
            value = json.loads(raw)
            if not isinstance(value, dict):
                raise ValueError("not object")
            return value
        except (httpx.TimeoutException, httpx.NetworkError) as e:
            last = str(e)
            time.sleep(2 ** attempt)
    raise RuntimeError(last or "模型调用失败")


def normalize(value: dict) -> dict:
    kinds = {"body_scan", "body_report", "training_report", "daily_training",
             "life_photo", "testimonial", "other"}
    kind = value.get("kind")
    if kind not in kinds:
        kind = "other"
    view = value.get("view") if kind == "body_scan" else None
    if view not in (None, "front", "side", "side_left", "side_right", "back"):
        view = None
    background = value.get("background") if kind == "body_scan" else None
    if background not in (None, "grid_board", "white_wall", "wood", "mirror", "outdoor", "other"):
        background = None
    phase = value.get("phase") if kind == "body_scan" else None
    if phase not in (None, "before", "after", "both", "unknown"):
        phase = "unknown"
    try:
        conf = float(value.get("confidence", 0))
    except Exception:
        conf = 0.0
    return {
        "kind": kind,
        "view": view,
        "background": background,
        "phase": phase,
        "people": int(value.get("people") or 0),
        "already_masked": bool(value.get("already_masked")),
        "is_screenshot": bool(value.get("is_screenshot")),
        "confidence": round(max(0.0, min(1.0, conf)), 3),
        "reason": str(value.get("reason", ""))[:60],
    }


def classify_one(asset: dict, thumb_path: Path, cfg: dict) -> dict:
    sha = asset["sha256"]
    hit = cached(sha)
    if hit:
        return {**hit["result"], "cached": True}
    with Image.open(thumb_path) as im:
        b64 = _encode(im.convert("RGB"))
    value = normalize(call_vlm(b64, cfg))
    p = _cache_path(sha)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"prompt_version": PROMPT_VERSION, "result": value,
                             "at": time.time()}, ensure_ascii=False))
    return {**value, "cached": False}


def classify_all(items, cfg, concurrency=3, progress=None) -> dict:
    """items: [{sha256, thumb}] -> {sha256: result}"""
    out = {}
    errors = {}

    def work(item):
        try:
            return item["sha256"], classify_one(item, Path(item["thumb"]), cfg), None
        except Exception as e:
            return item["sha256"], None, str(e)[:200]

    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = [pool.submit(work, it) for it in items]
        for i, f in enumerate(futures, 1):
            sha, res, err = f.result()
            if res:
                out[sha] = res
            else:
                errors[sha] = err
            if progress:
                progress(i, len(futures))
    return {"results": out, "errors": errors}

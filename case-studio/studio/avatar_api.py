"""Durable Qwen image API calls. No diffusion model or GPU allocation here."""

import base64, hashlib, io, time, threading, fcntl
from pathlib import Path
from urllib.parse import urlsplit
import httpx
from PIL import Image, ImageOps
from .common import WEB_DATA, read, save, sha, signature
from . import config

CAPACITY = threading.BoundedSemaphore(2)
STYLE_VERSION = "memoji-accessories-expression-v2"
STYLE = """This is an RGBA image with transparency. 一枚成年人的正面3D卡通头部头像，
类似苹果Memoji的圆润简洁风格。五官简化但有神，眉眼和嘴角一起表达情绪，自然灵动而非呆板证件照，光滑哑光软胶材质，
不画真实皮肤、毛孔、皱纹、胡茬纹理，不画二维黑色描边。头发是圆润大块发束。
头部保持端正正面，加入下文指定的小巧帽子或发饰、耳饰；装饰贴合头部，额外高度不超过头部高度的12%，不遮住眉眼，不要夸张高帽、宽帽檐、长耳坠或漂浮装饰。
只画完整头部和耳朵，不要脖子、肩膀、身体、衣服、文字、商标、阴影、白底或棋盘格。发尾不得低于下巴。
头像居中，占画面高度80%，头发、装饰和下巴完整，四周留白。头像本身完全不透明，轮廓外完全透明。
The image has an alpha channel and the background is transparent. Clean antialiased edges."""


def build_prompt(gender, variant_key="", reference=False):
    """Stable choices keep retries identical while varying members' accessories."""
    choices = {
        "女": ["成年女性，小巧的奶油粉蝴蝶结发饰和珍珠耳钉，温柔甜美的笑眼、轻扬眉毛，嘴角自然上扬，可爱而成熟。",
               "成年女性，贴合发型的浅紫色蝴蝶结和小圆耳钉，俏皮可爱的轻眨眼，柔和开朗的微笑，保留成年人的气质。"],
        "男": ["成年男性，低帽冠的休闲棒球帽向后戴，帽子简洁且无商标，眉眼有神，嘴角微扬，阳光帅气、自信轻松。",
               "成年男性，一顶小巧的深蓝色休闲贝雷帽，眉毛轻扬，带一点俏皮的自然笑容，清爽帅气，避免严肃僵硬。"],
        "": ["成年中性人物，一顶贴合头部的奶油色小针织帽，明亮的笑眼和自然上扬的嘴角，温暖活泼。"]}
    options = choices.get(gender, choices[""])
    option = int(hashlib.sha256(variant_key.encode()).hexdigest()[:8],16) % len(options)
    reference_rule = ("参考图仅用于发型、眼镜、脸型等可见特征，保留这些特征并按上述要求增加装饰和表情，不照搬真人质感。"
                      if reference else "生成标准通用卡通头像，不参考任何真实人物。")
    return (STYLE + "\n" + options[option] + "\n" + reference_rule +
            "\n最重要的构图约束：这是悬浮的头部表情贴纸，下巴必须是贴纸最下端；下巴轮廓下方直接是透明区域，绝对不能出现一截脖子。"
            " Only a floating emoji head. The chin is the lowest opaque point. No neck, no bust. Hair ends above the chin.")


def settings():
    cfg = config.load()
    value = cfg["image_model"].copy()
    if value.get("reuse_model_key"):
        if urlsplit(value["base_url"]).hostname != urlsplit(cfg["model"]["base_url"]).hostname:
            raise RuntimeError("生图接口与视觉接口域名不同，请单独配置生图 Key")
        value["api_key"] = cfg["model"].get("api_key", "")
    if not value.get("api_key"):
        raise RuntimeError("请在设置中配置 Qwen 生图 API Key")
    return value


def data_url(path, box=None):
    with Image.open(path) as source:
        im = ImageOps.exif_transpose(source).convert("RGB")
        if box:
            w, h = im.size
            x1, y1, x2, y2 = box
            dx, height = (x2-x1)*.35, y2-y1
            # Include hair above the forehead; exclude the neck below the chin.
            # A neck in the reference encourages a bust instead of a head sticker.
            im = im.crop((max(0,(x1-dx)*w/1000), max(0,(y1-height*.6)*h/1000),
                          min(w,(x2+dx)*w/1000), min(h,(y2+height*.03)*h/1000)))
        im.thumbnail((1400, 1400))
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=92)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def clean_alpha(source, target):
    """Validate actual alpha; normalize VAE noise, never invent a transparent RGB image."""
    with Image.open(source) as im:
        if im.width * im.height > 8_500_000 or "A" not in im.getbands():
            raise RuntimeError("生图结果没有有效透明通道，请重试透明头像生成")
        im = im.convert("RGBA")
        alpha = im.getchannel("A")
        hist = alpha.histogram()
        total = im.width * im.height
        if sum(hist[:9]) < total * .05 or sum(hist[247:]) < total * .08:
            raise RuntimeError("生图结果的背景或头像透明度不符合贴纸要求")
        alpha = alpha.point([0 if a <= 8 else 255 if a >= 247 else round((a-8)*255/239) for a in range(256)])
        im.putalpha(alpha)
        box = alpha.getbbox()
        if not box:
            raise RuntimeError("头像为空")
        im = im.crop(box)
        im.thumbnail((1024, 1024))
        target = Path(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        im.save(target, "PNG")
        return {"size": list(im.size), "alpha_extrema": list(im.getchannel("A").getextrema())}


def generate(prompt, reference=None, box=None, nonce="", timeout=240):
    cfg = settings()
    identity = {"prompt": prompt, "reference": sha(reference) if reference else None,
                "box": box, "model": cfg["model"], "base_url": cfg["base_url"], "nonce": nonce}
    key = signature(identity)
    root = WEB_DATA / "avatar-api" / key
    root.mkdir(parents=True, exist_ok=True)
    target = root / "avatar.png"
    with CAPACITY, (root / "generation.lock").open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if target.exists():
            return target, {"cached": True, "key": key, "model": cfg["model"]}
        save(root / "request.json", identity, True)
        headers = {"Authorization": "Bearer " + cfg["api_key"]}
        endpoint = cfg["base_url"].rstrip("/")
        with httpx.Client(timeout=httpx.Timeout(60, connect=15), trust_env=False) as client:
            task = read(root / "task.json", {})
            if task.get("status") == "unknown":
                raise RuntimeError("上次生图提交结果不明；请主动重新生成，避免自动重复计费")
            if not task:
                content = ([{"image": data_url(reference, box)}] if reference else []) + [{"text": prompt}]
                payload = {"model": cfg["model"], "input": {"messages": [{"role": "user", "content": content}]},
                           "parameters": {"size": "1024*1024", "n": 1, "prompt_extend": False, "watermark": False}}
                # Persist uncertainty before POST; a crash cannot silently submit twice.
                save(root / "task.json", {"status": "unknown"}, True)
                try:
                    response = client.post(endpoint + "/services/aigc/image-generation/generation",
                                           headers={**headers, "X-DashScope-Async": "enable"}, json=payload)
                except httpx.RequestError:
                    raise RuntimeError("生图提交连接失败，结果尚不确定，请稍后主动重试") from None
                if response.status_code != 200:
                    if response.status_code < 500:
                        save(root / "task.json", {"status": "rejected", "http_status": response.status_code}, True)
                    raise RuntimeError(f"生图接口返回 {response.status_code}，请检查模型、Key 和额度")
                output = response.json().get("output", {})
                if not output.get("task_id"):
                    raise RuntimeError("生图接口没有返回任务编号")
                task = {"task_id": output["task_id"], "status": output.get("task_status")}
                save(root / "task.json", task, True)
            if not task.get("task_id"):
                raise RuntimeError("上次生图请求被拒绝，请检查设置后重新生成")
            started = time.monotonic()
            while time.monotonic()-started < timeout:
                try:
                    response = client.get(endpoint + "/tasks/" + task["task_id"], headers=headers)
                    response.raise_for_status()
                    result = response.json()
                except (httpx.HTTPError, ValueError):
                    raise RuntimeError("生图状态查询失败；已保留任务，下次继续查询") from None
                output = result.get("output", {})
                status = output.get("task_status")
                if status == "SUCCEEDED":
                    save(root / "result.json", result, True)
                    urls = [c["image"] for choice in output.get("choices", []) for c in choice.get("message", {}).get("content", []) if c.get("image")]
                    urls += [r["url"] for r in output.get("results", []) if r.get("url")]
                    if len(urls) != 1 or urlsplit(urls[0]).scheme != "https":
                        raise RuntimeError("生图结果地址无效")
                    # No API credentials are sent to the result storage URL.
                    with client.stream("GET", urls[0]) as download:
                        download.raise_for_status()
                        size = 0
                        with (root / "raw.png").open("wb") as file:
                            for block in download.iter_bytes():
                                size += len(block)
                                if size > 20*1024**2:
                                    raise RuntimeError("生图结果文件过大")
                                file.write(block)
                    info = clean_alpha(root / "raw.png", target)
                    save(root / "alpha.json", info)
                    return target, {"cached": False, "key": key, "model": cfg["model"], "usage": result.get("usage")}
                if status in ("FAILED", "CANCELED", "UNKNOWN"):
                    save(root / "result.json", result, True)
                    raise RuntimeError("生图任务失败，请检查模型设置后重新生成")
                time.sleep(3)
            raise RuntimeError("生图仍在处理中；任务已保存，可再次点击继续查询")

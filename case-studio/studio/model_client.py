"""Small JSON client for explicit identity transcription and user-triggered copy."""

import json, threading, time
import httpx
from . import config
from .common import WEB_DATA, read, save, signature

CAPACITY = threading.BoundedSemaphore(2)


def ask(system, prompt, images=(), cache=False, temperature=0):
    cfg = config.load()["model"]
    if not all(cfg.get(k) for k in ("base_url", "model", "api_key")):
        raise RuntimeError("请先在设置中配置模型接口、模型名与 API Key")
    content = [{"type": "text", "text": prompt}]
    content += [{"type": "image_url", "image_url": {"url": im}} for im in images]
    payload = dict(
        model=cfg["model"],
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": content},
        ],
        temperature=temperature,
        max_tokens=3200,
        response_format={"type": "json_object"},
    )
    if "qwen" in cfg["model"].lower():
        payload["enable_thinking"] = False
    key = signature({"base_url": cfg["base_url"], "payload": payload})
    path = WEB_DATA / "model-cache" / (key + ".json")
    if cache and path.exists():
        result = read(path)
        return result["value"], {"cached": True, "request_count": 0, "key": key}
    with CAPACITY:
        for attempt in range(2):
            try:
                with httpx.Client(
                    timeout=httpx.Timeout(120, connect=15), trust_env=False
                ) as client:
                    response = client.post(
                        cfg["base_url"].rstrip("/") + "/chat/completions",
                        headers={"Authorization": "Bearer " + cfg["api_key"]},
                        json=payload,
                    )
                if (
                    response.status_code in (408, 429, 500, 502, 503, 504)
                    and attempt == 0
                ):
                    time.sleep(1)
                    continue
                if response.status_code != 200:
                    raise RuntimeError(
                        f"模型接口返回 {response.status_code}，请检查设置后重试"
                    )
                body = response.json()
                choice = body["choices"][0]
                if choice.get("finish_reason") == "length":
                    raise ValueError("truncated")
                text = choice["message"]["content"].strip()
                if text.startswith("```"):
                    text = text.split("\n", 1)[1].rsplit("```", 1)[0]
                value = json.loads(text)
                if not isinstance(value, dict):
                    raise ValueError("not an object")
                trace = {
                    "key": key,
                    "cached": False,
                    "request_count": attempt + 1,
                    "model": cfg["model"],
                    "usage": body.get("usage", {}),
                }
                if cache:
                    save(path, {"value": value, "trace": trace}, True)
                return value, trace
            except httpx.RequestError:
                if attempt == 1:
                    raise RuntimeError("模型请求超时或连接失败，请稍后重试") from None
            except (ValueError, KeyError, IndexError, TypeError, AttributeError):
                if attempt == 1:
                    raise RuntimeError("模型未返回完整的有效内容，请重试") from None
        raise RuntimeError("模型请求未完成，请重试")

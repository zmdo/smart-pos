"""归一化 + 质量评分 + 去重指纹。

设计要点（对应方案 07）：
- 看字节不看扩展名（magic bytes）
- HEIC/RAW/TIFF/CMYK → JPEG
- EXIF 方向纠正；生成 thumb/work/full 三档
- pHash + sha256 去重
- 质量评分：清晰度 / 曝光 / 人物占比 / 最短边
"""
import hashlib, io, os, pathlib
import numpy as np
from PIL import Image, ImageOps

Image.MAX_IMAGE_PIXELS = 400_000_000

try:  # iPhone 原生格式
    import pillow_heif
    pillow_heif.register_heif_opener()
    HEIF = True
except Exception:
    HEIF = False

YOLO_MODEL = os.environ.get("CASE_YOLO", "/root/autodl-fs/portrait-studio/models/yolo11n.pt")
_yolo = None


def sniff(data: bytes) -> str:
    if data[:3] == b"\xff\xd8\xff":
        return "jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    if data[:2] == b"BM":
        return "bmp"
    if data[:4] in (b"II*\x00", b"MM\x00*"):
        return "tiff"
    if data[4:12] in (b"ftypheic", b"ftypheix", b"ftypmif1", b"ftypheif", b"ftypmsf1"):
        return "heif"
    if data[:5] == b"%PDF-":
        return "pdf"
    if data[:4] == b"PK\x03\x04":
        return "zip"
    if data[4:8] == b"ftyp":
        return "video"
    return "unknown"


def sha256_file(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def phash(img: Image.Image) -> int:
    """标准 pHash：32x32 灰度 → DCT → 取左上 8x8 → 与中位数比较得 64bit。"""
    import cv2
    small = cv2.resize(np.asarray(img.convert("L")), (32, 32), interpolation=cv2.INTER_AREA)
    dct = cv2.dct(small.astype(np.float32))
    low = dct[:8, :8].flatten()
    med = float(np.median(low[1:]))
    bits = 0
    for v in low:
        bits = (bits << 1) | (1 if float(v) > med else 0)
    return bits


def hamming(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


def _persons(img: Image.Image):
    """返回 (人数框, 最大人物面积占比)。框在 work 图坐标，调用方负责缩放。"""
    global _yolo
    try:
        if _yolo is None:
            from ultralytics import YOLO
            _yolo = YOLO(YOLO_MODEL)
        res = _yolo.predict(img, classes=[0], conf=0.35, imgsz=640, verbose=False, device=0)[0]
        if not len(res.boxes):
            return [], 0.0
        area = img.width * img.height
        boxes = res.boxes.xyxy.cpu().numpy().tolist()
        best = max(((b[2] - b[0]) * (b[3] - b[1])) / area for b in boxes)
        return boxes, round(float(best), 4)
    except Exception:
        return None, -1.0  # 模型不可用


def load_image(path) -> Image.Image:
    with Image.open(path) as im:
        im = ImageOps.exif_transpose(im)
        if im.mode in ("RGBA", "LA", "P"):
            bg = Image.new("RGB", im.size, (255, 255, 255))
            rgba = im.convert("RGBA")
            bg.paste(rgba, mask=rgba.split()[-1])
            im = bg
        return im.convert("RGB")


def process(src: pathlib.Path, out_dir: pathlib.Path, asset_id: str, thresholds: dict) -> dict:
    """产出 {ok, renditions, quality, phash, width, height, error}"""
    result = {"ok": False, "error": None, "renditions": {}, "quality": {}, "phash": None}
    try:
        with open(src, "rb") as f:
            head = f.read(32)
        mime = sniff(head)
        if mime not in ("jpeg", "png", "webp", "bmp", "tiff", "heif"):
            result["error"] = f"非图片格式: {mime}"
            return result
        img = load_image(src)
        w, h = img.size
        out_dir.mkdir(parents=True, exist_ok=True)

        full = out_dir / f"{asset_id}.jpg"
        img.save(full, "JPEG", quality=95, subsampling=1)
        work = img.copy()
        work.thumbnail((2048, 2048), Image.Resampling.LANCZOS)
        work_path = out_dir / f"{asset_id}.w.jpg"
        work.save(work_path, "JPEG", quality=90)
        thumb = img.copy()
        thumb.thumbnail((256, 256), Image.Resampling.LANCZOS)
        thumb_path = out_dir / f"{asset_id}.t.jpg"
        thumb.save(thumb_path, "JPEG", quality=82)

        import cv2
        height_scale = 512.0 / max(w, h)
        small = cv2.resize(np.asarray(img.convert("L")),
                           (max(1, int(w * height_scale)), max(1, int(h * height_scale))),
                           interpolation=cv2.INTER_AREA)
        sharp = float(cv2.Laplacian(small, cv2.CV_64F).var())
        mean_luma = float(small.mean())
        hi_ratio = float((small > 245).mean())
        lo_ratio = float((small < 12).mean())
        boxes, subject = _persons(work)
        persons = []
        if boxes:
            sx, sy = w / work.width, h / work.height
            persons = [[round(b[0] * sx), round(b[1] * sy), round(b[2] * sx), round(b[3] * sy)]
                       for b in boxes]

        q = {
            "sharpness": round(sharp, 1),
            "mean_luma": round(mean_luma, 1),
            "hi_ratio": round(hi_ratio, 3),
            "lo_ratio": round(lo_ratio, 3),
            "subject_ratio": subject,
            "persons": len(persons),
            "width": w, "height": h, "min_side": min(w, h),
        }
        q["status"] = "ok"
        q["drop_reasons"] = []

        result.update(ok=True, renditions={
            "full": str(full.relative_to(out_dir.parent)),
            "work": str(work_path.relative_to(out_dir.parent)),
            "thumb": str(thumb_path.relative_to(out_dir.parent)),
        }, quality=q, phash=phash(img), width=w, height=h, mime=mime, persons=persons)
    except Exception as e:
        result["error"] = f"{type(e).__name__}: {e}"[:200]
    return result


REASON_CN = {
    "blurry": "画面模糊（清晰度不足）",
    "bad_exposure": "曝光异常（过暗或过亮）",
    "subject_too_small": "人物太小",
    "low_res": "分辨率过低",
}

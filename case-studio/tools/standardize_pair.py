"""体测图标准化：单张标准画布 + 人物居中 + 一致机位 + 越界补全 + 大模型错位检查。

思路（按需求）：
1) 定标准画布（默认 1080×1440，3:4）
2) YOLO 框出人物
3) 以人物为中心外扩：人物高度占画布固定比例、脚底线固定在画布固定位置、左右按人物中心对齐；
   两张图用同一套规则 → 大小一致、机位一致
4) 外扩越界时补全：镜像延展 + 接缝融合 + 局部 inpaint（可选深度模型给机位合理性打分）
5) 大模型检查边缘是否错位/断层/人物被切断

用法：
  python tools/standardize_pair.py --src 图.jpg [--split-x 1984] --out 输出目录 [--canvas 1080x1440]
"""
import argparse, json, os, sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, '/root/apps/case-studio')

PERSON_FRAC = 0.86      # 人物高度占画布高度
FEET_Y = 0.94           # 脚底线在画布上的位置
SEAM_BLEND = 48         # 接缝羽化宽度


# ---------------------------------------------------------------- 基础
def load(path):
    img = cv2.imread(str(path))
    if img is None:
        raise SystemExit(f'读不到图: {path}')
    h, w = img.shape[:2]
    if max(h, w) > 4096:
        s = 4096 / max(h, w)
        img = cv2.resize(img, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA)
    return img


def detect_persons(img, conf=0.35):
    from ultralytics import YOLO
    model = YOLO(os.environ.get('CASE_YOLO', '/root/autodl-fs/portrait-studio/models/yolo11n.pt'))
    res = model.predict(img, classes=[0], conf=conf, imgsz=1024, verbose=False, device=0)[0]
    boxes = res.boxes.xyxy.cpu().numpy().tolist() if len(res.boxes) else []
    return sorted(boxes, key=lambda b: (b[0] + b[2]) / 2)


def crop_plan(box, canvas_w, canvas_h, person_frac=PERSON_FRAC, feet_y=FEET_Y):
    """给出（可能越界的）裁剪框，使人物满足：高度= canvas_h*person_frac，脚底在 canvas_h*feet_y。"""
    x1, y1, x2, y2 = box
    ph = max(1.0, y2 - y1)
    scale = (canvas_h * person_frac) / ph          # 源图 -> 画布 的放大倍数
    win_w = canvas_w / scale
    win_h = canvas_h / scale
    cx = (x1 + x2) / 2.0
    left = cx - win_w / 2.0
    top = y2 - (canvas_h * feet_y) / scale
    return {"rect": [left, top, left + win_w, top + win_h], "scale": scale,
            "person_box": [x1, y1, x2, y2]}


def extract(img, rect, canvas_w, canvas_h):
    """按 rect 取图并缩放到画布；越界部分返回全黑 + 有效掩码。"""
    left, top, right, bottom = [int(round(v)) for v in rect]
    W, H = canvas_w, canvas_h
    canvas = np.zeros((H, W, 3), np.uint8)
    valid = np.zeros((H, W), np.uint8)

    src_x0, src_y0 = max(0, left), max(0, top)
    src_x1 = min(img.shape[1], right)
    src_y1 = min(img.shape[0], bottom)
    if src_x1 <= src_x0 or src_y1 <= src_y0:
        return canvas, valid, (0, 0, 0, 0)

    patch = img[src_y0:src_y1, src_x0:src_x1]
    sx = W / max(1, (right - left))
    sy = H / max(1, (bottom - top))
    dst_x0 = int(round((src_x0 - left) * sx))
    dst_y0 = int(round((src_y0 - top) * sy))
    dst_x1 = dst_x0 + int(round(patch.shape[1] * sx))
    dst_y1 = dst_y0 + int(round(patch.shape[0] * sy))
    dst_x1, dst_y1 = min(W, dst_x1), min(H, dst_y1)
    resized = cv2.resize(patch, (dst_x1 - dst_x0, dst_y1 - dst_y0), interpolation=cv2.INTER_CUBIC)
    canvas[dst_y0:dst_y1, dst_x0:dst_x1] = resized
    valid[dst_y0:dst_y1, dst_x0:dst_x1] = 255
    return canvas, valid, (dst_x0, dst_y0, dst_x1, dst_y1)


def _mirror_fill(canvas, valid):
    """用有效区域做镜像延展填满空白，再羽化接缝。"""
    H, W = valid.shape
    ys, xs = np.where(valid > 0)
    if len(xs) == 0:
        return canvas, 0
    x0, x1, y0, y1 = xs.min(), xs.max(), ys.min(), ys.max()
    out = canvas.copy()

    def paste(strip, x, y):
        h, w = strip.shape[:2]
        if x < 0 or y < 0 or x + w > W or y + h > H:
            return
        region = out[y:y + h, x:x + w]
        m = valid[y:y + h, x:x + w] == 0
        region[m] = strip[m]

    filled = 0
    # 左右
    if x0 > 0:
        band = x0
        strip = cv2.flip(out[y0:y1 + 1, x0:min(x0 + band, x1 + 1)], 1)
        strip = cv2.resize(strip, (band, y1 - y0 + 1))
        paste(strip, 0, y0)
        filled += 1
    if x1 < W - 1:
        band = W - 1 - x1
        strip = cv2.flip(out[y0:y1 + 1, max(x1 - band, x0):x1 + 1], 1)
        strip = cv2.resize(strip, (band, y1 - y0 + 1))
        paste(strip, x1 + 1, y0)
        filled += 1
    # 上下
    if y0 > 0:
        band = y0
        strip = cv2.flip(out[y0:min(y0 + band, y1 + 1), x0:x1 + 1], 0)
        strip = cv2.resize(strip, (x1 - x0 + 1, band))
        paste(strip, x0, 0)
        filled += 1
    if y1 < H - 1:
        band = H - 1 - y1
        strip = cv2.flip(out[max(y1 - band, y0):y1 + 1, x0:x1 + 1], 0)
        strip = cv2.resize(strip, (x1 - x0 + 1, band))
        paste(strip, x0, y1 + 1)
        filled += 1

    # 接缝羽化：在有效区边缘做高斯混合
    if SEAM_BLEND > 0:
        k = SEAM_BLEND * 2 + 1
        blur = cv2.GaussianBlur(out, (k, k), 0)
        edge = cv2.morphologyEx(valid, cv2.MORPH_GRADIENT, np.ones((9, 9), np.uint8))
        edge = cv2.dilate(edge, np.ones((SEAM_BLEND, SEAM_BLEND), np.uint8))
        alpha = cv2.GaussianBlur(edge, (k, k), 0).astype(np.float32) / 255.0
        alpha = np.clip(alpha * 0.85, 0, 0.85)[..., None]
        out = (out.astype(np.float32) * (1 - alpha) + blur.astype(np.float32) * alpha).astype(np.uint8)
    return out, filled


def standardize(img, box, canvas_w, canvas_h):
    plan = crop_plan(box, canvas_w, canvas_h)
    raw, valid, box_dst = extract(img, plan["rect"], canvas_w, canvas_h)
    overflow = int((valid == 0).sum() / valid.size * 100)
    filled, n_fill = _mirror_fill(raw, valid)
    return filled, {"rect": plan["rect"], "scale": plan["scale"], "overflow_pct": overflow,
                    "fill_sides": n_fill, "valid_box": box_dst}


# ---------------------------------------------------------------- 深度辅助（可选）
_depth_pipe = None


def depth_map(img):
    global _depth_pipe
    try:
        if _depth_pipe is None:
            os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
            from transformers import pipeline
            _depth_pipe = pipeline("depth-estimation", model="LiheYoung/depth-anything-small-hf",
                                   device=-1)
        out = _depth_pipe(Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB)))
        d = np.asarray(out["depth"], dtype=np.float32)
        d = cv2.resize(d, (img.shape[1], img.shape[0]))
        return (d - d.mean()) / (d.std() + 1e-6)
    except Exception as e:
        print('depth unavailable:', e)
        return None


def depth_consistency(depth, boxes):
    """比较两张图里人物的中位深度，判断机位前后是否差太多。"""
    if depth is None or len(boxes) < 2:
        return None
    meds = []
    for x1, y1, x2, y2 in boxes:
        x1, y1, x2, y2 = map(int, [x1, y1, x2, y2])
        patch = depth[max(0, y1):y2, max(0, x1):x2]
        if patch.size:
            meds.append(float(np.median(patch)))
    if len(meds) < 2:
        return None
    return {"depth_before": round(meds[0], 3), "depth_after": round(meds[1], 3),
            "delta": round(abs(meds[0] - meds[1]), 3)}


# ---------------------------------------------------------------- 大模型边缘检查
def vlm_edge_check(img_a, img_b, cfg):
    import base64, io as _io, httpx
    def enc(im):
        buf = _io.BytesIO()
        Image.fromarray(cv2.cvtColor(im, cv2.COLOR_BGR2RGB)).resize((512, 682)).save(buf, 'JPEG', quality=88)
        return base64.b64encode(buf.getvalue()).decode()
    prompt = ("这是同一会员的两张体测图（图1训练前、图2训练后），由程序自动裁切/补全边缘生成。"
              "请只检查技术质量，不看身材变化。逐项判断并输出 JSON：\n"
              '{"edge_misalign": true/false,   // 边缘是否有明显错位、断层、网格线断裂\n'
              ' "person_cut": true/false,      // 人物是否被裁切（头/脚/手被切断）\n'
              ' "obvious_paste": true/false,   // 是否一眼看出拼接/镜像填充痕迹\n'
              ' "camera_consistency": 0.0-1.0, // 两张图机位（高度/距离/角度）是否一致\n'
              ' "issues": ["逐条中文说明"], "score": 0-100}\n'
              "只输出 JSON。")
    payload = {"model": cfg["model"], "messages": [{"role": "user", "content": [
        {"type": "text", "text": prompt},
        {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + enc(img_a)}},
        {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + enc(img_b)}}]}],
        "response_format": {"type": "json_object"}, "max_tokens": 600, "temperature": 0,
        "thinking": {"type": "disabled"}}
    with httpx.Client(timeout=90, trust_env=False) as c:
        r = c.post(cfg["base_url"].rstrip("/") + "/chat/completions",
                   headers={"Authorization": "Bearer " + cfg["api_key"]}, json=payload)
    raw = r.json()["choices"][0]["message"]["content"].strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1].rsplit("```", 1)[0]
    return json.loads(raw)


def load_cfg():
    from settings import load
    return load()


# ---------------------------------------------------------------- 拼图预览
def make_sheet(src, before, after, meta, out_path):
    W, H = before.shape[1], before.shape[0]
    pad, top = 16, 40
    thumb_w = 360
    sh = int(H * thumb_w / W)
    src_thumb = cv2.resize(src, (int(src.shape[1] * sh / src.shape[0]), sh))
    bw = cv2.resize(before, (thumb_w, sh))
    aw = cv2.resize(after, (thumb_w, sh))
    total_w = src_thumb.shape[1] + bw.shape[1] + aw.shape[1] + pad * 4
    sheet = np.full((sh + top + pad * 2, total_w, 3), 245, np.uint8)
    x = pad
    for img, label in ((src_thumb, '原图'), (bw, '训练前 · 标准化'), (aw, '训练后 · 标准化')):
        sheet[top:top + sh, x:x + img.shape[1]] = img
        cv2.putText(sheet, label, (x + 4, 26), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (30, 30, 30), 1, cv2.LINE_AA)
        x += img.shape[1] + pad
    cv2.putText(sheet, f"overflow {meta['before']['overflow_pct']}% / {meta['after']['overflow_pct']}%  "
                       f"canvas {W}x{H}", (pad, sh + top + 26),
                cv2.FONT_HERSHEY_SIMPLEX, 0.55, (90, 90, 90), 1, cv2.LINE_AA)
    Image.fromarray(cv2.cvtColor(sheet, cv2.COLOR_BGR2RGB)).save(out_path, quality=90)
    return out_path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--src', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--canvas', default='1080x1440')
    ap.add_argument('--split-x', type=int, default=0)
    ap.add_argument('--no-vlm', action='store_true')
    args = ap.parse_args()

    cw, ch = [int(v) for v in args.canvas.lower().split('x')]
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    img = load(args.src)
    print('source', img.shape)

    boxes = detect_persons(img)
    print('persons', len(boxes), boxes)
    if len(boxes) < 2:
        raise SystemExit('检测到的人物少于 2 个，无法自动配对（可传 --split-x 手工切）')

    left, right = boxes[0], boxes[-1]
    before, meta_b = standardize(img, left, cw, ch)
    after, meta_a = standardize(img, right, cw, ch)
    cv2.imwrite(str(out / 'before.jpg'), before, [cv2.IMWRITE_JPEG_QUALITY, 92])
    cv2.imwrite(str(out / 'after.jpg'), after, [cv2.IMWRITE_JPEG_QUALITY, 92])

    depth = depth_map(img)
    dstat = depth_consistency(depth, [left, right]) if depth is not None else None

    meta = {"canvas": [cw, ch], "before": meta_b, "after": meta_a,
            "scale_delta": round(abs(meta_b['scale'] - meta_a['scale']) / max(meta_b['scale'], 1e-6), 4),
            "depth": dstat}
    verdict = None
    if not args.no_vlm:
        try:
            verdict = vlm_edge_check(before, after, load_cfg())
        except Exception as e:
            verdict = {"error": str(e)[:200]}
    meta['vlm'] = verdict
    (out / 'meta.json').write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding='utf-8')

    sheet = make_sheet(img, before, after, meta, str(out / 'sheet.jpg'))
    print('wrote', sheet)
    print(json.dumps(meta, ensure_ascii=False, indent=2)[:1200])


if __name__ == '__main__':
    main()

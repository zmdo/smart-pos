"""体测图标准化 v2：人物居中 + 机位统一 + 网格背景智能补全 + 大模型边缘检查。

v1 的问题（已用 VLM 复现）：直接镜像会把旁边那个人镜像进来，网格线断裂。
v2 做法：
  1. 标准画布（默认 1080×1440）
  2. YOLO + SAM2 拿到每个人的人物掩码
  3. 每张图只保留"自己"那个人；另一个人用背景补掉
  4. 背景补全优先"重建网格"：估计网格周期/相位/线宽/墙色，按同样的相位继续画，
     网格线天然连续；木纹墙等无网格背景则用干净墙块平铺 + 羽化
  5. 越界区域用同一套背景重建逻辑补
  6. 两张图人物高度占比、脚底线位置、水平居中都一致
  7. VLM 检查边缘错位/人物切断/拼接痕迹
"""
import argparse, json, os, sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

sys.path.insert(0, '/root/apps/case-studio')

PERSON_FRAC = 0.86
FEET_Y = 0.94
SAM_CKPT = '/root/autodl-fs/portrait-studio/models/sam2.1_hiera_base_plus.pt'
SAM_CFG = 'configs/sam2.1/sam2.1_hiera_b+.yaml'

_sam = None


# ---------------------------------------------------------------- 检测 / 分割
def load(path):
    img = cv2.imread(str(path))
    if img is None:
        raise SystemExit(f'读不到图: {path}')
    h, w = img.shape[:2]
    if max(h, w) > 4096:
        s = 4096 / max(h, w)
        img = cv2.resize(img, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA)
    return img


def detect_persons(img):
    from ultralytics import YOLO
    model = YOLO(os.environ.get('CASE_YOLO', '/root/autodl-fs/portrait-studio/models/yolo11n.pt'))
    res = model.predict(img, classes=[0], conf=0.35, imgsz=1024, verbose=False, device=0)[0]
    boxes = res.boxes.xyxy.cpu().numpy().tolist() if len(res.boxes) else []
    return sorted(boxes, key=lambda b: (b[0] + b[2]) / 2)


def segment_persons(img, boxes):
    """SAM2 按框出掩码；失败则退回矩形掩码。"""
    global _sam
    masks = []
    try:
        if _sam is None:
            import torch
            from sam2.build_sam import build_sam2
            from sam2.sam2_image_predictor import SAM2ImagePredictor
            _sam = SAM2ImagePredictor(build_sam2(SAM_CFG, SAM_CKPT, device='cuda'))
        import torch
        with torch.inference_mode():
            _sam.set_image(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
            for b in boxes:
                # 多掩码取面积最大的那个：单掩码时 SAM 有时只切出身体的一部分（如只出露肤区域）
                cand, scores, _ = _sam.predict(box=np.array(b, dtype=np.float32), multimask_output=True)
                areas = [int(c.sum()) for c in cand]
                pick = int(np.argmax(areas))
                m = cand[pick].astype(bool)
                m = cv2.morphologyEx(m.astype(np.uint8), cv2.MORPH_CLOSE,
                                     np.ones((7, 7), np.uint8)).astype(bool)
                masks.append(m)
    except Exception as e:
        print('SAM2 unavailable, fallback to boxes:', str(e)[:120])
        masks = []
        for x1, y1, x2, y2 in boxes:
            m = np.zeros(img.shape[:2], bool)
            m[int(y1):int(y2), int(x1):int(x2)] = True
            masks.append(m)
    return masks


# ---------------------------------------------------------------- 背景重建
def estimate_grid(gray, wall_mask, bgr):
    """估计墙面网格：周期、相位、线宽、墙色/线色。失败返回 None。"""
    ys, xs = np.where(wall_mask)
    if len(xs) < 5000:
        return None
    x0, x1, y0, y1 = xs.min(), xs.max(), ys.min(), ys.max()
    roi = gray[y0:y1 + 1, x0:x1 + 1].astype(np.float32)
    m = wall_mask[y0:y1 + 1, x0:x1 + 1]
    if roi.size < 20000:
        return None

    dark = 255 - roi
    col_profile = np.where(m, dark, 0).sum(0) / np.maximum(m.sum(0), 1)
    row_profile = np.where(m, dark, 0).sum(1) / np.maximum(m.sum(1), 1)

    def period_phase(profile, lo=24, hi=200):
        p = profile - profile.mean()
        ac = np.correlate(p, p, 'full')[len(p) - 1:]
        ac[:lo] = 0
        k = int(np.argmax(ac[lo:hi]) + lo)
        if ac[k] < 0.30 * ac[0] or k < lo:
            return None, None
        # 相位：在周期内的折叠平均，找峰值位置
        idx = np.arange(len(p))
        fold = np.zeros(k)
        cnt = np.zeros(k)
        np.add.at(fold, idx % k, p)
        np.add.at(cnt, idx % k, 1)
        fold = fold / np.maximum(cnt, 1)
        phase = int(np.argmax(fold))
        strength = float(fold.max() / (np.abs(fold).mean() + 1e-6))
        return k, (phase, strength)

    pv, vinfo = period_phase(col_profile)
    ph, hinfo = period_phase(row_profile)
    if not vinfo or not hinfo:
        return None
    wall_px = bgr[wall_mask]
    dark_cut = np.percentile(roi[m], 12)
    line_mask = wall_mask.copy()
    line_mask[wall_mask] = roi[m] < dark_cut
    line_px = bgr[line_mask]
    return {
        "origin": [int(x0), int(y0)],
        "period_x": int(pv), "phase_x": int(vinfo[0]), "strength_x": float(round(vinfo[1], 2)),
        "period_y": int(ph), "phase_y": int(hinfo[0]), "strength_y": float(round(hinfo[1], 2)),
        "wall_color": [int(v) for v in np.median(wall_px, axis=0)],
        "line_color": [int(v) for v in (np.median(line_px, axis=0) if line_px.size else np.min(wall_px, axis=0))],
        "line_width": int(max(1, round(1 + (roi[m] < dark_cut).mean() * 3))),
    }


def synth_background(shape, grid, floor_y, sample_wall):
    """按估计的网格重建整张背景（墙 + 地面）。"""
    H, W = shape[:2]
    bg = np.full((H, W, 3), grid["wall_color"], np.uint8) if grid else np.full((H, W, 3), 235, np.uint8)
    if grid:
        ox, oy = grid["origin"]
        px, py = grid["period_x"], grid["period_y"]
        lw = max(1, grid["line_width"])
        color = tuple(int(v) for v in grid["line_color"])
        for x in range(ox + grid["phase_x"] % px, W, px):
            cv2.line(bg, (x, 0), (x, floor_y), color, lw)
        for y in range(oy + grid["phase_y"] % py, floor_y, py):
            cv2.line(bg, (0, y), (W, y), color, lw)
    # 地面：把原图脚底以下的干净区域平铺
    if floor_y < H:
        band = sample_wall[floor_y:H] if sample_wall.shape[0] >= H else None
        if band is not None and band.shape[0] > 3:
            reps = int(np.ceil((H - floor_y) / band.shape[0]))
            tiled = np.tile(band, (reps, 1, 1))[:H - floor_y, :W]
            bg[floor_y:H] = tiled
    return bg


def fill_background(canvas, valid, person_masks_canvas, grid, floor_y, sample):
    """用重建背景替换：越界区域 + 非本人的人物区域，接缝羽化。"""
    H, W = valid.shape
    bg = synth_background((H, W), grid, floor_y, sample)
    need = (valid == 0)
    for m in person_masks_canvas:
        need = need | m
    if not need.any():
        return canvas, 0
    out = canvas.copy()
    out[need] = bg[need]
    # 羽化接缝
    k = 31
    blur = cv2.GaussianBlur(out, (k, k), 0)
    edge = cv2.dilate(need.astype(np.uint8) * 255, np.ones((11, 11), np.uint8))
    alpha = cv2.GaussianBlur(edge, (k, k), 0).astype(np.float32) / 255.0
    alpha = np.clip(alpha, 0, 0.7)[..., None]
    out = (out.astype(np.float32) * (1 - alpha) + blur.astype(np.float32) * alpha).astype(np.uint8)
    return out, int(need.mean() * 100)


# ---------------------------------------------------------------- 标准化
def warp_mask(mask, rect, canvas_w, canvas_h):
    left, top, right, bottom = [int(round(v)) for v in rect]
    H, W = canvas_h, canvas_w
    out = np.zeros((H, W), bool)
    sx = W / max(1, (right - left))
    sy = H / max(1, (bottom - top))
    ys, xs = np.where(mask)
    if len(xs) == 0:
        return out
    mx = np.clip(((xs - left) * sx).astype(int), 0, W - 1)
    my = np.clip(((ys - top) * sy).astype(int), 0, H - 1)
    out[my, mx] = True
    return out


def standardize(img, box, masks, other_idx, canvas_w, canvas_h, grid, floor_y):
    x1, y1, x2, y2 = box
    ph = max(1.0, y2 - y1)
    scale = (canvas_h * PERSON_FRAC) / ph
    win_w, win_h = canvas_w / scale, canvas_h / scale
    cx = (x1 + x2) / 2.0
    left = cx - win_w / 2.0
    top = y2 - (canvas_h * FEET_Y) / scale
    rect = [left, top, left + win_w, top + win_h]

    W, H = canvas_w, canvas_h
    canvas = np.zeros((H, W, 3), np.uint8)
    valid = np.zeros((H, W), np.uint8)
    L, T, R, B = [int(round(v)) for v in rect]
    sx0, sy0, sx1, sy1 = max(0, L), max(0, T), min(img.shape[1], R), min(img.shape[0], B)
    if sx1 > sx0 and sy1 > sy0:
        patch = img[sy0:sy1, sx0:sx1]
        dx0 = int(round((sx0 - L) * W / (R - L)))
        dy0 = int(round((sy0 - T) * H / (B - T)))
        dx1 = min(W, dx0 + int(round(patch.shape[1] * W / (R - L))))
        dy1 = min(H, dy0 + int(round(patch.shape[0] * H / (B - T))))
        canvas[dy0:dy1, dx0:dx1] = cv2.resize(patch, (dx1 - dx0, dy1 - dy0), interpolation=cv2.INTER_CUBIC)
        valid[dy0:dy1, dx0:dx1] = 255

    other_canvas = [warp_mask(m, rect, W, H) for i, m in enumerate(masks) if i != other_idx]
    floor_c = int((floor_y - top) * H / (B - T))
    filled, pct = fill_background(canvas, valid, other_canvas, grid, floor_c, img)
    return filled, {"rect": [round(v, 1) for v in rect], "scale": round(scale, 4),
                    "filled_pct": pct, "person_frac": PERSON_FRAC, "feet_y": FEET_Y}


# ---------------------------------------------------------------- 深度 / VLM
_depth = None


def depth_of(img):
    global _depth
    try:
        if _depth is None:
            os.environ.setdefault('HF_ENDPOINT', 'https://hf-mirror.com')
            from transformers import pipeline
            _depth = pipeline('depth-estimation', model='LiheYoung/depth-anything-small-hf', device=-1)
        out = _depth(Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB)))
        d = np.asarray(out['depth'], np.float32)
        d = cv2.resize(d, (img.shape[1], img.shape[0]))
        return (d - d.mean()) / (d.std() + 1e-6)
    except Exception as e:
        print('depth unavailable:', str(e)[:120])
        return None


def depth_consistency(depth, boxes):
    if depth is None or len(boxes) < 2:
        return None
    vals = []
    for x1, y1, x2, y2 in boxes[:2]:
        patch = depth[max(0, int(y1)):int(y2), max(0, int(x1)):int(x2)]
        if patch.size:
            vals.append(float(np.median(patch)))
    if len(vals) < 2:
        return None
    return {"before": round(vals[0], 3), "after": round(vals[1], 3),
            "delta": round(abs(vals[0] - vals[1]), 3)}


def vlm_check(a, b, cfg):
    import base64, io as _io, httpx

    def enc(im):
        buf = _io.BytesIO()
        Image.fromarray(cv2.cvtColor(im, cv2.COLOR_BGR2RGB)).resize((512, 682)).save(buf, 'JPEG', quality=88)
        return base64.b64encode(buf.getvalue()).decode()

    prompt = ("这是同一会员体测图的两张标准化结果（图1训练前、图2训练后），由程序自动裁切并用"
              "重建背景补全边缘。只看技术质量，不看身材变化。输出 JSON：\n"
              '{"edge_misalign": true/false, "person_cut": true/false, "obvious_paste": true/false,'
              ' "camera_consistency": 0.0-1.0, "issues": ["中文说明"], "score": 0-100}\n只输出 JSON。')
    payload = {"model": cfg['model'], "messages": [{"role": "user", "content": [
        {"type": "text", "text": prompt},
        {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + enc(a)}},
        {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + enc(b)}}]}],
        "response_format": {"type": "json_object"}, "max_tokens": 600, "temperature": 0,
        "thinking": {"type": "disabled"}}
    with httpx.Client(timeout=90, trust_env=False) as c:
        r = c.post(cfg['base_url'].rstrip('/') + '/chat/completions',
                   headers={'Authorization': 'Bearer ' + cfg['api_key']}, json=payload)
    raw = r.json()['choices'][0]['message']['content'].strip()
    if raw.startswith('```'):
        raw = raw.split('\n', 1)[1].rsplit('```', 1)[0]
    return json.loads(raw)


def make_sheet(src, before, after, meta, out_path):
    W, H = before.shape[1], before.shape[0]
    tw = 360
    sh = int(H * tw / W)
    st = cv2.resize(src, (int(src.shape[1] * sh / src.shape[0]), sh))
    bt, at = cv2.resize(before, (tw, sh)), cv2.resize(after, (tw, sh))
    pad, top = 16, 40
    total = st.shape[1] + bt.shape[1] + at.shape[1] + pad * 4
    sheet = np.full((sh + top + pad * 2, total, 3), 245, np.uint8)
    x = pad
    for img, label in ((st, 'SRC'), (bt, 'BEFORE'), (at, 'AFTER')):
        sheet[top:top + sh, x:x + img.shape[1]] = img
        cv2.putText(sheet, label, (x + 4, 26), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (30, 30, 30), 1, cv2.LINE_AA)
        x += img.shape[1] + pad
    v = (meta.get('vlm') or {})
    fb = meta['before'].get('filled_pct', meta['before'].get('fill_px_pct'))
    fa = meta['after'].get('filled_pct', meta['after'].get('fill_px_pct'))
    txt = f"fill {fb}% / {fa}%  score {v.get('score','-')}"
    cv2.putText(sheet, txt, (pad, sh + top + 26), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (90, 90, 90), 1, cv2.LINE_AA)
    Image.fromarray(cv2.cvtColor(sheet, cv2.COLOR_BGR2RGB)).save(out_path, quality=90)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--src', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--canvas', default='1080x1440')
    ap.add_argument('--no-vlm', action='store_true')
    args = ap.parse_args()
    cw, ch = [int(v) for v in args.canvas.lower().split('x')]
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    img = load(args.src)
    boxes = detect_persons(img)
    if len(boxes) < 2:
        raise SystemExit(f'只检测到 {len(boxes)} 个人，无法配对')
    left, right = boxes[0], boxes[-1]
    masks = segment_persons(img, [left, right])

    # 墙面区域 = 两个人掩码之外、且偏亮的像素
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    person_any = masks[0] | masks[1]
    wall = (~cv2.dilate(person_any.astype(np.uint8), np.ones((25, 25), np.uint8)).astype(bool)) & (gray > 110)
    grid = estimate_grid(gray, wall, img)
    floor_y = int(max(left[3], right[3]))
    print('grid', json.dumps(grid, ensure_ascii=False) if grid else None, 'floor_y', floor_y)

    before, mb = standardize(img, left, masks, 1, cw, ch, grid, floor_y)
    after, ma = standardize(img, right, masks, 0, cw, ch, grid, floor_y)
    cv2.imwrite(str(out / 'before.jpg'), before, [cv2.IMWRITE_JPEG_QUALITY, 92])
    cv2.imwrite(str(out / 'after.jpg'), after, [cv2.IMWRITE_JPEG_QUALITY, 92])

    depth = depth_of(img)
    meta = {"canvas": [cw, ch], "grid": grid, "floor_y": floor_y,
            "before": mb, "after": ma,
            "scale_delta": round(abs(mb['scale'] - ma['scale']) / max(mb['scale'], 1e-9), 4),
            "depth": depth_consistency(depth, [left, right])}
    if not args.no_vlm:
        try:
            from settings import load as load_cfg
            meta['vlm'] = vlm_check(before, after, load_cfg())
        except Exception as e:
            meta['vlm'] = {"error": str(e)[:200]}
    (out / 'meta.json').write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding='utf-8')
    make_sheet(img, before, after, meta, str(out / 'sheet.jpg'))
    print(json.dumps({k: meta[k] for k in ('before', 'after', 'scale_delta', 'depth', 'vlm')},
                     ensure_ascii=False, indent=2)[:1500])


if __name__ == '__main__':
    main()

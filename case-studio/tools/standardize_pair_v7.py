"""v7：人物抠图 + 模板化背景（推荐方案）

为什么不再"补背景"：
- 对比图是两张独立照片拼的，**不可能**用几何/纹理补全伪装成同一场景；
- 成品里每张单图/每个 VS 面板本来就是独立画面，不需要背景连续；
- 所以把背景交给**设计层**：统一米色渐变 + 极淡网格暗纹 + 落地阴影，人物抠图贴上去。
  零生成、零补全、100% 一致，而且比"半张照片"更像成品卡片。

流程：
1) YOLO + SAM2 抠人（掩码腐蚀 1px + 羽化 2px，去绿边）
2) 统一取景：人物高度 86%、脚底 94%、水平居中（两张同一套规则）
3) 画布 1080×1440：米色渐变 + 淡网格 + 人物脚下柔和投影
4) 成对色调对齐（只对人物像素做 LAB 均值/方差匹配）
5) 规则质检 + VLM 复核
"""
import argparse, json, sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from standardize_pair_v2 import (load, detect_persons, segment_persons,
                                 depth_of, depth_consistency, vlm_check, make_sheet)

PERSON_FRAC = 0.84   # 人物高度占画布
FEET_Y = 0.88        # 脚底线位置（留出脚下阴影空间）

BG_TOP = (250, 246, 240)      # BGR，米白
BG_BOTTOM = (232, 226, 212)   # 略深，形成纵向渐变
GRID_COLOR = (238, 233, 224)
GRID_STEP = 72


def make_backdrop(cw, ch):
    bg = np.zeros((ch, cw, 3), np.uint8)
    for y in range(ch):
        t = y / max(1, ch - 1)
        bg[y, :] = [int(BG_TOP[i] + (BG_BOTTOM[i] - BG_TOP[i]) * t) for i in range(3)]
    for x in range(0, cw, GRID_STEP):
        cv2.line(bg, (x, 0), (x, ch), GRID_COLOR, 1)
    for y in range(0, ch, GRID_STEP):
        cv2.line(bg, (0, y), (cw, y), GRID_COLOR, 1)
    return bg


def cutout(img, mask, rect, cw, ch):
    """把人物按取景规则贴到透明画布上。"""
    L, T, R, B = rect
    out = np.zeros((ch, cw, 4), np.uint8)
    m = mask.astype(np.uint8)
    m = cv2.erode(m, np.ones((3, 3), np.uint8))          # 去一圈边缘杂色
    ys, xs = np.where(m > 0)
    if len(xs) == 0:
        return out
    x0, x1, y0, y1 = xs.min(), xs.max(), ys.min(), ys.max()
    pad = 6
    x0, y0 = max(0, x0 - pad), max(0, y0 - pad)
    x1, y1 = min(img.shape[1] - 1, x1 + pad), min(img.shape[0] - 1, y1 + pad)
    patch = img[y0:y1 + 1, x0:x1 + 1]
    alpha = (m[y0:y1 + 1, x0:x1 + 1] * 255).astype(np.uint8)
    alpha = cv2.GaussianBlur(alpha, (3, 3), 0)

    sx, sy = cw / (R - L), ch / (B - T)
    dx0 = int(round((x0 - L) * sx))
    dy0 = int(round((y0 - T) * sy))
    dw = max(1, int(round(patch.shape[1] * sx)))
    dh = max(1, int(round(patch.shape[0] * sy)))
    p = cv2.resize(patch, (dw, dh), interpolation=cv2.INTER_CUBIC)
    a = cv2.resize(alpha, (dw, dh), interpolation=cv2.INTER_CUBIC)

    cx0, cy0 = max(0, dx0), max(0, dy0)
    cx1, cy1 = min(cw, dx0 + dw), min(ch, dy0 + dh)
    if cx1 <= cx0 or cy1 <= cy0:
        return out
    px0, py0 = cx0 - dx0, cy0 - dy0
    out[cy0:cy1, cx0:cx1, :3] = p[py0:py0 + (cy1 - cy0), px0:px0 + (cx1 - cx0)]
    out[cy0:cy1, cx0:cx1, 3] = a[py0:py0 + (cy1 - cy0), px0:px0 + (cx1 - cx0)]
    return out


def add_shadow(bg, layer):
    a = layer[..., 3].astype(np.float32) / 255.0
    ys, xs = np.where(layer[..., 3] > 0)
    if len(xs) == 0:
        return bg
    foot_y = int(ys.max())
    cx = int((xs.min() + xs.max()) / 2)
    w = int((xs.max() - xs.min()) * 0.55)
    h = max(6, int(w * 0.12))
    alpha = np.zeros(layer.shape[:2], np.float32)
    cv2.ellipse(alpha, (cx, foot_y), (w, h), 0, 0, 360, 1.0, -1)
    alpha = cv2.GaussianBlur(alpha, (61, 61), 0)
    shade = (1.0 - 0.32 * alpha)[..., None]
    return (bg.astype(np.float32) * shade).astype(np.uint8)


def blend(bg, layer):
    a = layer[..., 3:4].astype(np.float32) / 255.0
    return (layer[..., :3].astype(np.float32) * a + bg.astype(np.float32) * (1 - a)).astype(np.uint8)


def person_tone_match(a, b):
    """把 b 的人物色调对齐到 a（LAB 均值/方差），只统计人物像素。"""
    ma = a[..., 3] > 200
    mb = b[..., 3] > 200
    if ma.sum() < 500 or mb.sum() < 500:
        return b
    la = cv2.cvtColor(a[..., :3], cv2.COLOR_BGR2LAB).astype(np.float32)
    lb = cv2.cvtColor(b[..., :3], cv2.COLOR_BGR2LAB).astype(np.float32)
    # 只对齐亮度，不动色相（否则粉色上衣会被拉成紫色）
    sa, sb = la[..., 0][ma], lb[..., 0][mb]
    if sb.std() > 1e-3:
        lb[..., 0][mb] = (sb - sb.mean()) / sb.std() * sa.std() + sa.mean()
    out = b.copy()
    out[..., :3][mb] = cv2.cvtColor(np.clip(lb, 0, 255).astype(np.uint8), cv2.COLOR_LAB2BGR)[mb]
    return out


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
        raise SystemExit('人物不足 2 个')
    left, right = boxes[0], boxes[-1]
    masks = segment_persons(img, [left, right])

    frames = []
    for idx, box in enumerate((left, right)):
        x1, y1, x2, y2 = box
        scale = (ch * PERSON_FRAC) / max(1.0, y2 - y1)
        win_w, win_h = cw / scale, ch / scale
        cx = (x1 + x2) / 2.0
        L = cx - win_w / 2.0
        T = y2 - (ch * FEET_Y) / scale
        layer = cutout(img, masks[idx], [L, T, L + win_w, T + win_h], cw, ch)
        frames.append(layer)

    before, after = frames[0], person_tone_match(frames[0], frames[1])
    bg = make_backdrop(cw, ch)
    img_b = blend(add_shadow(bg.copy(), before), before)
    img_a = blend(add_shadow(bg.copy(), after), after)

    cv2.imwrite(str(out / 'before.jpg'), img_b, [cv2.IMWRITE_JPEG_QUALITY, 92])
    cv2.imwrite(str(out / 'after.jpg'), img_a, [cv2.IMWRITE_JPEG_QUALITY, 92])

    meta = {"canvas": [cw, ch], "mode": "cutout+backdrop",
            "before": {"coverage_pct": round(float((before[..., 3] > 0).mean() * 100), 1)},
            "after": {"coverage_pct": round(float((after[..., 3] > 0).mean() * 100), 1)},
            "depth": depth_consistency(depth_of(img), [left, right])}
    if not args.no_vlm:
        try:
            from settings import load as load_cfg
            meta['vlm'] = vlm_check(img_b, img_a, load_cfg())
        except Exception as e:
            meta['vlm'] = {"error": str(e)[:200]}
    (out / 'meta.json').write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding='utf-8')
    make_sheet(img, img_b, img_a, meta, str(out / 'sheet.jpg'))
    print(json.dumps(meta, ensure_ascii=False, indent=2)[:1000])


if __name__ == '__main__':
    main()

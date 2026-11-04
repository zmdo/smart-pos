"""v3：周期平移补全（不打网格线，直接复用真实墙面纹理）+ 主体原样合成。

相对 v2 的改动：
- 不再"重画网格"，而是按估计的网格周期 p 平移真实像素填充 → 网格线天然连续
- 主体用 SAM 掩码原样贴回，不在主体边缘做任何羽化 → 不会有抠图毛边
- 地面用同样的周期平移（退化为镜像）
"""
import json, sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from standardize_pair_v2 import (PERSON_FRAC, FEET_Y, load, detect_persons, segment_persons,
                                 estimate_grid, depth_of, depth_consistency, vlm_check, make_sheet)


def periodic_fill(img, holes, clean, periods):
    """用真实像素按周期平移填洞：holes=True 需要填，clean=True 可作源。"""
    H, W = holes.shape
    out = img.copy()
    left = holes.copy()
    for period in periods:
        if period is None or period < 8:
            continue
        for k in (1, 2, 3, 4, 6):
            for dx, dy in ((k * period, 0), (-k * period, 0), (0, k * period), (0, -k * period)):
                if not left.any():
                    return out, int(holes.sum() - left.sum())
                src = np.roll(np.roll(img, dy, axis=0), dx, axis=1)
                ok = np.roll(np.roll(clean, dy, axis=0), dx, axis=1) & left
                if ok.any():
                    out[ok] = src[ok]
                    left &= ~ok
    return out, int(holes.sum() - left.sum())


def standardize_v3(img, box, masks, other_idx, canvas_w, canvas_h, grid, floor_y):
    x1, y1, x2, y2 = box
    ph = max(1.0, y2 - y1)
    scale = (canvas_h * PERSON_FRAC) / ph
    win_w, win_h = canvas_w / scale, canvas_h / scale
    cx = (x1 + x2) / 2.0
    left = cx - win_w / 2.0
    top = y2 - (canvas_h * FEET_Y) / scale
    rect = [left, top, left + win_w, top + win_h]
    W, H = canvas_w, canvas_h

    # 1) 取裁剪，越界留洞
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

    # 2) 主体掩码（画布坐标）
    def warp(mask):
        out = np.zeros((H, W), bool)
        ys, xs = np.where(mask)
        if len(xs) == 0:
            return out
        mx = np.clip(((xs - L) * W / (R - L)).astype(int), 0, W - 1)
        my = np.clip(((ys - T) * H / (B - T)).astype(int), 0, H - 1)
        out[my, mx] = True
        return out

    subject = warp(masks[other_idx])     # 本人
    others = [warp(m) for i, m in enumerate(masks) if i != other_idx]
    other_any = np.zeros((H, W), bool)
    for m in others:
        other_any |= m

    # 3) 需要补的洞 = 越界 + 别人 + 别人附近一圈
    holes = (valid == 0) | other_any
    holes = cv2.dilate(holes.astype(np.uint8), np.ones((9, 9), np.uint8)).astype(bool) & ~subject
    clean = (~holes) & (valid > 0) & (~subject)

    periods = [grid["period_x"], grid["period_y"]] if grid else [64]
    bg, filled = periodic_fill(canvas, holes, clean, periods)
    # 4) 主体原样贴回（只在主体掩码内，1px 羽化）
    m = subject.astype(np.float32)
    m = cv2.GaussianBlur(m, (3, 3), 0)[..., None]
    out = (bg.astype(np.float32) * (1 - m) + canvas.astype(np.float32) * m).astype(np.uint8)

    stat = {"rect": [round(v, 1) for v in rect], "scale": round(scale, 4),
            "fill_px_pct": round(float(holes.mean() * 100), 1),
            "filled_px_pct": round(float(filled / max(1, holes.sum()) * 100), 1)}
    return out, stat


def main():
    import argparse
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

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    person_any = masks[0] | masks[1]
    wall = (~cv2.dilate(person_any.astype(np.uint8), np.ones((25, 25), np.uint8)).astype(bool)) & (gray > 110)
    grid = estimate_grid(gray, wall, img)
    floor_y = int(max(left[3], right[3]))
    print('grid', grid)

    before, mb = standardize_v3(img, left, masks, 0, cw, ch, grid, floor_y)
    after, ma = standardize_v3(img, right, masks, 1, cw, ch, grid, floor_y)
    cv2.imwrite(str(out / 'before.jpg'), before, [cv2.IMWRITE_JPEG_QUALITY, 92])
    cv2.imwrite(str(out / 'after.jpg'), after, [cv2.IMWRITE_JPEG_QUALITY, 92])

    meta = {"canvas": [cw, ch], "grid": grid, "before": mb, "after": ma,
            "scale_delta": round(abs(mb['scale'] - ma['scale']) / max(mb['scale'], 1e-9), 4),
            "depth": depth_consistency(depth_of(img), [left, right])}
    if not args.no_vlm:
        try:
            from settings import load as load_cfg
            meta['vlm'] = vlm_check(before, after, load_cfg())
        except Exception as e:
            meta['vlm'] = {"error": str(e)[:200]}
    (out / 'meta.json').write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding='utf-8')
    make_sheet(img, before, after, meta, str(out / 'sheet.jpg'))
    print(json.dumps(meta, ensure_ascii=False, indent=2)[:1200])


if __name__ == '__main__':
    main()

"""v6：取景标准化 + 边界补墙（不生成）

与前几版的区别：
- 不做"纹理平移"、不调用任何生成模型
- 窗口越界 / 别的人物遮挡的地方，用两样**真实测量值**补：
  1) 逐行墙面颜色（取样自该行真实墙像素中位数 → 保留纵向明暗渐变）
  2) Hough 检出的网格线位置/线宽/线色（从同一张图测出来的，延长即可，天然对齐）
- 网格线只画在"补出来的区域"，并用羽化收边，不碰人物
- 成对色彩对齐（LAB 均值方差匹配，仅背景）
"""
import argparse, json, sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from standardize_pair_v2 import (PERSON_FRAC, FEET_Y, load, detect_persons, segment_persons,
                                 depth_of, depth_consistency, vlm_check, make_sheet)


def frame_plan(box, img_w, img_h, cw, ch, frac=PERSON_FRAC, feet=FEET_Y):
    x1, y1, x2, y2 = box
    ph = max(1.0, y2 - y1)
    scale = (ch * frac) / ph
    win_w, win_h = cw / scale, ch / scale
    cx = (x1 + x2) / 2.0
    left = cx - win_w / 2.0
    top = y2 - (ch * feet) / scale
    if win_w <= img_w:
        left = min(max(left, 0), img_w - win_w)
    if win_h <= img_h:
        top = min(max(top, 0), img_h - win_h)
    if win_w > img_w or win_h > img_h:
        k = max(win_w / img_w, win_h / img_h)
        return frame_plan(box, img_w, img_h, cw, ch, frac / k, feet)
    return {"rect": [left, top, left + win_w, top + win_h], "scale": scale, "frac": round(frac, 4)}


def detect_grid(img, persons):
    """Hough 提取垂直/水平网格线（只统计墙面区域）。"""
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    mask = (~cv2.dilate(persons.astype(np.uint8), np.ones((31, 31), np.uint8)).astype(bool)) & (gray > 90)
    edges = cv2.Canny(gray, 40, 120)
    edges = cv2.bitwise_and(edges, mask.astype(np.uint8) * 255)
    lines = cv2.HoughLinesP(edges, 1, np.pi / 360, threshold=80,
                            minLineLength=max(120, img.shape[0] // 6), maxLineGap=8)
    vx, hy = [], []
    if lines is not None:
        for x1, y1, x2, y2 in lines[:, 0]:
            if abs(x2 - x1) <= 3 and abs(y2 - y1) > 60:
                vx.append((x1 + x2) / 2)
            elif abs(y2 - y1) <= 3 and abs(x2 - x1) > 60:
                hy.append((y1 + y2) / 2)
    def cluster(vals):
        vals = sorted(vals)
        out = []
        for v in vals:
            if not out or v - out[-1][-1] > 6:
                out.append([v])
            else:
                out[-1].append(v)
        return [float(np.mean(c)) for c in out]
    vx, hy = cluster(vx), cluster(hy)
    dark = gray[mask] if mask.any() else gray
    return {"vx": vx, "hy": hy,
            "line_color": [int(v) for v in np.percentile(img[mask], 8, axis=0)] if mask.any() else [120, 120, 120],
            "line_w": 2}


def row_wall_colors(img, persons):
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    ok = ~cv2.dilate(persons.astype(np.uint8), np.ones((25, 25), np.uint8)).astype(bool)
    colors = np.zeros((img.shape[0], 3), np.float32)
    fb = np.median(img[ok & (gray > 100)], axis=0) if (ok & (gray > 100)).any() else np.array([235., 235., 235.])
    for y in range(img.shape[0]):
        m = ok[y] & (gray[y] > 100)
        colors[y] = np.median(img[y][m], axis=0) if m.sum() > 20 else fb
    k = 41
    pad = np.pad(colors, ((k, k), (0, 0)), mode='edge')
    for c in range(3):
        colors[:, c] = np.convolve(pad[:, c], np.ones(k) / k, mode='same')[k:k + img.shape[0]]
    return colors


def composite(img, rect, cw, ch, wall_rows, grid, subject, other):
    L, T, R, B = [int(round(v)) for v in rect]
    sx, sy = cw / max(1, R - L), ch / max(1, B - T)
    canvas = np.zeros((ch, cw, 3), np.uint8)
    real = np.zeros((ch, cw), bool)
    sx0, sy0 = max(0, L), max(0, T)
    sx1, sy1 = min(img.shape[1], R), min(img.shape[0], B)
    if sx1 > sx0 and sy1 > sy0:
        patch = img[sy0:sy1, sx0:sx1]
        dx0, dy0 = int(round((sx0 - L) * sx)), int(round((sy0 - T) * sy))
        dx1 = min(cw, dx0 + int(round(patch.shape[1] * sx)))
        dy1 = min(ch, dy0 + int(round(patch.shape[0] * sy)))
        canvas[dy0:dy1, dx0:dx1] = cv2.resize(patch, (dx1 - dx0, dy1 - dy0), interpolation=cv2.INTER_CUBIC)
        real[dy0:dy1, dx0:dx1] = True

    hole = (~real) | cv2.dilate(other.astype(np.uint8), np.ones((15, 15), np.uint8)).astype(bool)
    hole &= ~subject
    if not hole.any():
        return canvas, 0.0

    # 逐行墙色
    fill = np.zeros_like(canvas)
    for yc in range(ch):
        ys = int(np.clip(T + yc * (B - T) / ch, 0, img.shape[0] - 1))
        fill[yc, :] = wall_rows[ys]
    base = canvas.copy()
    base[hole] = fill[hole]

    # 延长网格线（只画在补出来的区域）
    layer = base.copy()
    col = tuple(int(v) for v in grid["line_color"])
    lw = int(grid["line_w"])
    for x in grid["vx"]:
        xc = int(round((x - L) * sx))
        if 0 <= xc < cw:
            cv2.line(layer, (xc, 0), (xc, ch), col, lw)
    for y in grid["hy"]:
        yc = int(round((y - T) * sy))
        if 0 <= yc < ch:
            cv2.line(layer, (0, yc), (cw, yc), col, lw)

    k = 21
    hard = hole.astype(np.uint8)
    soft = cv2.GaussianBlur(cv2.erode(hard, np.ones((5, 5), np.uint8)) * 255, (k, k), 0).astype(np.float32) / 255.0
    soft = np.clip(soft, 0, 1)[..., None]
    out = (canvas.astype(np.float32) * (1 - soft) + layer.astype(np.float32) * soft).astype(np.uint8)
    # 人物永远用原始像素
    out[subject] = canvas[subject]
    return out, round(float(hole.mean() * 100), 1)


def warp_mask(mask, rect, cw, ch):
    L, T, R, B = [int(round(v)) for v in rect]
    out = np.zeros((ch, cw), bool)
    ys, xs = np.where(mask)
    if len(xs) == 0:
        return out
    mx = np.clip(((xs - L) * cw / (R - L)).astype(int), 0, cw - 1)
    my = np.clip(((ys - T) * ch / (B - T)).astype(int), 0, ch - 1)
    out[my, mx] = True
    return out


def color_match(src, ref, bg_mask):
    a = cv2.cvtColor(src, cv2.COLOR_BGR2LAB).astype(np.float32)
    b = cv2.cvtColor(ref, cv2.COLOR_BGR2LAB).astype(np.float32)
    for c in range(3):
        sa, sb = a[..., c][bg_mask], b[..., c][bg_mask]
        if sa.size < 100 or sa.std() < 1e-3:
            continue
        a[..., c] = (a[..., c] - sa.mean()) / sa.std() * sb.std() + sb.mean()
    return cv2.cvtColor(np.clip(a, 0, 255).astype(np.uint8), cv2.COLOR_LAB2BGR)


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
    persons = masks[0] | masks[1]
    wall_rows = row_wall_colors(img, persons)
    grid = detect_grid(img, persons)
    print('grid vx', len(grid['vx']), 'hy', len(grid['hy']))

    frames, metas, subs = [], [], []
    for idx, box in enumerate((left, right)):
        plan = frame_plan(box, img.shape[1], img.shape[0], cw, ch)
        rect = plan["rect"]
        subj = warp_mask(masks[idx], rect, cw, ch)
        other = np.zeros((ch, cw), bool)
        for j, m in enumerate(masks):
            if j != idx:
                other |= warp_mask(m, rect, cw, ch)
        frame, hole_pct = composite(img, rect, cw, ch, wall_rows, grid, subj, other)
        frames.append(frame)
        subs.append(subj)
        metas.append({"scale": round(plan["scale"], 4), "frac": plan["frac"],
                      "rect": [int(round(v)) for v in rect], "hole_pct": hole_pct})

    before, after = frames
    bg = ~(subs[0] | subs[1])
    before = color_match(before, after, cv2.erode(bg.astype(np.uint8), np.ones((31, 31), np.uint8)).astype(bool))

    cv2.imwrite(str(out / 'before.jpg'), before, [cv2.IMWRITE_JPEG_QUALITY, 92])
    cv2.imwrite(str(out / 'after.jpg'), after, [cv2.IMWRITE_JPEG_QUALITY, 92])

    meta = {"canvas": [cw, ch], "before": metas[0], "after": metas[1],
            "scale_delta": round(abs(metas[0]['scale'] - metas[1]['scale']) / max(metas[0]['scale'], 1e-9), 4),
            "grid_lines": {"vx": len(grid['vx']), "hy": len(grid['hy'])},
            "depth": depth_consistency(depth_of(img), [left, right])}
    if not args.no_vlm:
        try:
            from settings import load as load_cfg
            meta['vlm'] = vlm_check(before, after, load_cfg())
        except Exception as e:
            meta['vlm'] = {"error": str(e)[:200]}
    (out / 'meta.json').write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding='utf-8')
    make_sheet(img, before, after, meta, str(out / 'sheet.jpg'))
    print(json.dumps(meta, ensure_ascii=False, indent=2)[:1000])


if __name__ == '__main__':
    main()

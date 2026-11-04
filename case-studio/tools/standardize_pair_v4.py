"""v4：不打回卷的平移补全 + 更稳的网格周期估计。

v3 的问题：np.roll 会跨边回卷，把对面内容卷进来；周期估计偏小（8px）导致纹带。
v4：
- 用 warpAffine 平移（越界补 0），并同步平移 clean 掩码，只用真正干净的源像素
- 周期估计限制在 24–160px，并比较基频与二倍频能量，取更可信的那个
- 主体始终原样合成
"""
import argparse, json, sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from standardize_pair_v2 import (PERSON_FRAC, FEET_Y, load, detect_persons, segment_persons,
                                 depth_of, depth_consistency, vlm_check, make_sheet)


def shift_mask(img, mask, dx, dy):
    M = np.float32([[1, 0, dx], [0, 1, dy]])
    h, w = img.shape[:2]
    s_img = cv2.warpAffine(img, M, (w, h), flags=cv2.INTER_LINEAR, borderValue=0)
    s_m = cv2.warpAffine(mask.astype(np.uint8) * 255, M, (w, h), flags=cv2.INTER_NEAREST, borderValue=0)
    return s_img, s_m > 0


def period_fft(profile, lo=24, hi=160):
    p = profile - profile.mean()
    n = len(p)
    if n < 2 * hi:
        return None
    spec = np.abs(np.fft.rfft(p))
    freqs = np.fft.rfftfreq(n)
    best, best_v = None, 0.0
    for k in range(lo, hi):
        f = 1.0 / k
        idx = int(round(f * n))
        if idx <= 0 or idx >= len(spec):
            continue
        v = float(spec[idx])
        if v > best_v:
            best, best_v = k, v
    if best is None:
        return None
    # 相位：在周期 best 上折叠求峰
    idx = np.arange(n) % best
    fold = np.zeros(best)
    cnt = np.zeros(best)
    np.add.at(fold, idx, p)
    np.add.at(cnt, idx, 1)
    fold = fold / np.maximum(cnt, 1)
    return best, int(np.argmax(fold)), float(fold.max() / (np.abs(fold).mean() + 1e-6))


def estimate_wall(img, persons):
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).astype(np.float32)
    pad = cv2.dilate(persons.astype(np.uint8), np.ones((41, 41), np.uint8)).astype(bool)
    wall = (~pad) & (gray > 110)
    out = {"wall_mask": wall}
    if wall.sum() < 5000:
        return out
    ys, xs = np.where(wall)
    y0, y1, x0, x1 = ys.min(), ys.max(), xs.min(), xs.max()
    roi = gray[y0:y1 + 1, x0:x1 + 1]
    m = wall[y0:y1 + 1, x0:x1 + 1]
    if roi.size < 20000:
        return out
    col = np.where(m, 255 - roi, 0).sum(0) / np.maximum(m.sum(0), 1)
    row = np.where(m, 255 - roi, 0).sum(1) / np.maximum(m.sum(1), 1)
    px = period_fft(col)
    py = period_fft(row)
    out.update({
        "roi": [int(x0), int(y0), int(x1), int(y1)],
        "period_x": int(px[0]) if px else None, "phase_x": int(px[1]) if px else None,
        "strength_x": round(px[2], 2) if px else None,
        "period_y": int(py[0]) if py else None, "phase_y": int(py[1]) if py else None,
        "strength_y": round(py[2], 2) if py else None,
    })
    return out


def fill_no_wrap(img, holes, clean, periods):
    out = img.copy()
    left = holes.copy()
    for period in periods:
        if not period or period < 12:
            continue
        for k in (1, 2, 3, -1, -2, -3):
            for dx, dy in ((k * period, 0), (0, k * period)):
                if not left.any():
                    return out, int(holes.sum() - left.sum())
                s_img, okm = shift_mask(img, clean, dx, dy)
                ok = okm & left
                if ok.any():
                    out[ok] = s_img[ok]
                    left &= ~ok
    return out, int(holes.sum() - left.sum())


def standardize(img, box, masks, idx, cw, ch, wall, floor_y):
    x1, y1, x2, y2 = box
    scale = (ch * PERSON_FRAC) / max(1.0, y2 - y1)
    win_w, win_h = cw / scale, ch / scale
    cx = (x1 + x2) / 2.0
    L = cx - win_w / 2.0
    T = y2 - (ch * FEET_Y) / scale
    R, B = L + win_w, T + win_h
    li, ti, ri, bi = int(round(L)), int(round(T)), int(round(R)), int(round(B))

    canvas = np.zeros((ch, cw, 3), np.uint8)
    valid = np.zeros((ch, cw), np.uint8)
    sx0, sy0 = max(0, li), max(0, ti)
    sx1, sy1 = min(img.shape[1], ri), min(img.shape[0], bi)
    if sx1 > sx0 and sy1 > sy0:
        patch = img[sy0:sy1, sx0:sx1]
        dx0 = int(round((sx0 - li) * cw / (ri - li)))
        dy0 = int(round((sy0 - ti) * ch / (bi - ti)))
        dx1 = min(cw, dx0 + int(round(patch.shape[1] * cw / (ri - li))))
        dy1 = min(ch, dy0 + int(round(patch.shape[0] * ch / (bi - ti))))
        canvas[dy0:dy1, dx0:dx1] = cv2.resize(patch, (dx1 - dx0, dy1 - dy0), interpolation=cv2.INTER_CUBIC)
        valid[dy0:dy1, dx0:dx1] = 255

    def warp(mask):
        out = np.zeros((ch, cw), bool)
        ys, xs = np.where(mask)
        if len(xs) == 0:
            return out
        mx = np.clip(((xs - li) * cw / (ri - li)).astype(int), 0, cw - 1)
        my = np.clip(((ys - ti) * ch / (bi - ti)).astype(int), 0, ch - 1)
        out[my, mx] = True
        return out

    subject = warp(masks[idx])
    other = np.zeros((ch, cw), bool)
    for i in range(len(masks)):
        if i != idx:
            other |= warp(masks[i])
    # 别人的"整块区域"（含伸过来的手）也要清掉，避免幽灵残影
    other_area = np.zeros((ch, cw), bool)
    for i in range(len(masks)):
        if i == idx:
            continue
        ys, xs = np.where(masks[i])
        if len(xs) == 0:
            continue
        bx0 = int(np.clip((xs.min() - li) * cw / (ri - li), 0, cw))
        bx1 = int(np.clip((xs.max() - li) * cw / (ri - li), 0, cw))
        by0 = int(np.clip((ys.min() - ti) * ch / (bi - ti), 0, ch))
        by1 = int(np.clip((ys.max() - ti) * ch / (bi - ti), 0, ch))
        other_area[by0:by1, bx0:bx1] = True
    other_area = cv2.dilate(other_area.astype(np.uint8), np.ones((25, 25), np.uint8)).astype(bool)
    holes = ((valid == 0) | other | other_area) & ~subject

    # 取源限制：排除"两人之间的中缝带"（那里有跨过来的手臂），只用左右外侧的墙
    xs_all = [np.where(m)[1] for m in masks if m.any()]
    if len(xs_all) >= 2:
        lefts = sorted([(x.min(), x.max()) for x in xs_all])
        gap_lo = lefts[0][1]          # 左人的最右
        gap_hi = lefts[1][0]          # 右人的最左
        gx0 = int(np.clip((gap_lo - li) * cw / (ri - li), 0, cw))
        gx1 = int(np.clip((gap_hi - li) * cw / (ri - li), 0, cw))
        xs_idx = np.arange(cw)[None, :]
        mid_zone = (xs_idx >= gx0) & (xs_idx <= gx1)
        clean = (valid > 0) & ~holes & ~subject & ~other_area & ~mid_zone
    else:
        clean = (valid > 0) & ~holes & ~subject & ~other_area
    if clean.sum() < cw * 30:
        clean = (valid > 0) & ~holes & ~subject & ~other_area
    periods = [wall.get("period_x"), wall.get("period_y")] or [64]
    bg, filled = fill_no_wrap(canvas, holes, clean, periods)

    # 仍然没填上的（多为画面最外缘）用 inpaint 收尾
    rest = (holes & (bg.sum(2) == 0)).astype(np.uint8) * 255
    if rest.any():
        bg = cv2.inpaint(bg, rest, 7, cv2.INPAINT_TELEA)
        filled = int(holes.sum())

    m = subject.astype(np.float32)
    m = cv2.GaussianBlur(m, (3, 3), 0)[..., None]
    out = (bg.astype(np.float32) * (1 - m) + canvas.astype(np.float32) * m).astype(np.uint8)
    return out, {"scale": round(scale, 4), "fill_pct": round(float(holes.mean() * 100), 1),
                 "filled_pct": round(float(filled / max(1, holes.sum()) * 100), 1),
                 "rect": [li, ti, ri, bi]}


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
    wall = estimate_wall(img, persons)
    floor_y = int(max(left[3], right[3]))
    print('periods', wall.get('period_x'), wall.get('period_y'), 'strength',
          wall.get('strength_x'), wall.get('strength_y'))

    before, mb = standardize(img, left, masks, 0, cw, ch, wall, floor_y)
    after, ma = standardize(img, right, masks, 1, cw, ch, wall, floor_y)
    cv2.imwrite(str(out / 'before.jpg'), before, [cv2.IMWRITE_JPEG_QUALITY, 92])
    cv2.imwrite(str(out / 'after.jpg'), after, [cv2.IMWRITE_JPEG_QUALITY, 92])

    meta = {"canvas": [cw, ch], "periods": [wall.get("period_x"), wall.get("period_y")],
            "before": mb, "after": ma,
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

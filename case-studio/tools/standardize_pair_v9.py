"""v9：取景边界不越界到"另一个人"（按最新反馈）

问题：v8 的 3:4 窗口比单人半幅宽，必然把隔壁的人切进来。
做法：
1) YOLO 出两个人物框
2) **每个人只在"自己的领地"里取景**：左人窗口右边界 ≤ 右人左边（留缝），右人窗口左边界 ≥ 左人右边
3) 画布比例按可用宽度反推（默认 9:16），保证窗口能装下整个人且不越界
4) 保留各自原背景，不抠图、不补全
5) 调色调 + 质检（含"是否越界框到别人"这一项）
"""
import argparse, json, sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from standardize_pair_v2 import (load, detect_persons, depth_of, depth_consistency, vlm_check, make_sheet)

PERSON_FRAC = 0.86
FEET_Y = 0.92
GAP = 0.04          # 两人之间留出的空隙占画面宽比例
TONE_STRENGTH = 0.7



def detect_seam(img, boxes):
    """找两张照片拼接的竖缝：在两人之间的空档里找列均值跳变最大的位置。"""
    left, right = boxes[0], boxes[-1]
    x_lo = int(max(1, min(left[2], right[0] - 1)))
    x_hi = int(max(x_lo + 2, min(right[0], img.shape[1] - 2)))
    if x_hi - x_lo < 4:
        return int((left[2] + right[0]) / 2)
    # 只用"人物头顶以上"的纯背景带，避免把人物边缘当成缝
    head_top = int(min(b[1] for b in boxes))
    band_h = max(0, head_top - 5)
    if band_h < 8:
        return int((left[2] + right[0]) / 2)
    band = img[:band_h, x_lo:x_hi].astype(np.float32)
    prof = band.mean(axis=0)                      # (n, 3)
    step = np.abs(np.diff(prof, axis=0)).sum(axis=1)
    k = np.ones(7) / 7
    step = np.convolve(step, k, mode='same')
    if step.size == 0:
        return int((left[2] + right[0]) / 2)
    return int(x_lo + int(np.argmax(step)) + 1)


def pair_plans(boxes, img_w, img_h, cw, ch, target=PERSON_FRAC, feet=FEET_Y, gap=GAP, seam=None):
    """核心：**一对图共用一个 frac**（两张人物一样大），窗口各自夹在自己的领地里。"""
    # 先算每个人的"领地"和"最少需要多大的 frac 才装得下"
    zones, need = [], []
    for i, (x1, y1, x2, y2) in enumerate(boxes):
        lo, hi = 0.0, float(img_w)
        if seam is not None:
            if i > 0:
                lo = max(lo, seam + 2)
            if i < len(boxes) - 1:
                hi = min(hi, seam - 2)
        if i > 0:
            lo = max(lo, boxes[i - 1][2])
        if i < len(boxes) - 1:
            hi = min(hi, boxes[i + 1][0])
        gap_px = (hi - lo) * gap * 0.5
        lo += gap_px if i > 0 else 0
        hi -= gap_px if i < len(boxes) - 1 else 0
        avail = max(40.0, hi - lo)
        ph = max(1.0, y2 - y1)
        zones.append((lo, hi, avail, ph))
        need.append(max(target, (cw / ch) * ph / avail, ph / img_h))

    frac = min(0.98, max(need))          # 共用同一个 frac
    plans = []
    for i, ((x1, y1, x2, y2), (lo, hi, avail, ph)) in enumerate(zip(boxes, zones)):
        scale = (ch * frac) / ph
        win_w, win_h = cw / scale, ch / scale
        if win_w > avail:                 # 理论上不会发生，兜底
            scale = (ch * frac) / ph * (avail / win_w)
            win_w, win_h = cw / scale, ch / scale
        cx = (x1 + x2) / 2.0
        left = min(max(cx - win_w / 2.0, lo), max(lo, hi - win_w))
        left = min(max(left, 0.0), max(0.0, img_w - win_w))
        top = y2 - (ch * feet) / scale
        top = min(max(top, 0.0), max(0.0, img_h - win_h))
        plans.append({"rect": [left, top, left + win_w, top + win_h], "scale": round(scale, 4),
                      "frac": round(frac, 4), "bounds": [round(lo, 1), round(hi, 1)],
                      "win": [round(win_w, 1), round(win_h, 1)]})
    return plans


def take(img, rect, cw, ch):
    L, T, R, B = [int(round(v)) for v in rect]
    patch = img[max(0, T):B, max(0, L):R]
    return cv2.resize(patch, (cw, ch), interpolation=cv2.INTER_CUBIC)


def tone_match(src, ref, strength=TONE_STRENGTH):
    a = cv2.cvtColor(src, cv2.COLOR_BGR2LAB).astype(np.float32)
    b = cv2.cvtColor(ref, cv2.COLOR_BGR2LAB).astype(np.float32)
    for c in range(3):
        sa, sb = a[..., c], b[..., c]
        if sa.std() < 1e-3:
            continue
        tgt = (sa - sa.mean()) / sa.std() * sb.std() + sb.mean()
        a[..., c] = sa * (1 - strength) + tgt * strength
    return cv2.cvtColor(np.clip(a, 0, 255).astype(np.uint8), cv2.COLOR_LAB2BGR)


def qa(plan, box, other, cw, ch):
    """规则质检：人物是否完整、是否框到别人。"""
    L, T, R, B = plan["rect"]
    sx, sy = cw / (R - L), ch / (B - T)
    x1, y1, x2, y2 = box
    mx1, my1, mx2, my2 = (x1 - L) * sx, (y1 - T) * sy, (x2 - L) * sx, (y2 - T) * sy
    inside = mx1 >= 0 and my1 >= 0 and mx2 <= cw and my2 <= ch
    margin = min(mx1, my1, cw - mx2, ch - my2) / max(cw, ch)
    ox1, oy1, ox2, oy2 = other
    if ox2 < L or ox1 > R:          # 隔壁完全在窗口外 → 干净
        intrude = 0.0
    else:
        overlap_w = max(0.0, min(R, ox2) - max(L, ox1))
        overlap_h = max(0.0, min(B, oy2) - max(T, oy1))
        intrude = round(overlap_w * overlap_h / max(1.0, (R - L) * (B - T)) * 100, 2)
    return {"person_inside": bool(inside), "min_margin": round(float(margin), 3),
            "person_frac": round(float((my2 - my1) / ch), 3),
            "neighbor_area_pct": intrude, "pass": bool(inside and margin >= 0.02 and intrude <= 1.0)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--src', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--canvas', default='960x1920')
    ap.add_argument('--no-vlm', action='store_true')
    ap.add_argument('--strength', type=float, default=TONE_STRENGTH)
    args = ap.parse_args()
    cw, ch = [int(v) for v in args.canvas.lower().split('x')]
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    img = load(args.src)
    boxes = detect_persons(img)
    if len(boxes) < 2:
        raise SystemExit('人物不足 2 个')
    left, right = boxes[0], boxes[-1]
    # 分界用两人之间的中线（v1 用的就是这个位置，实测不会把拼接缝带进画面）
    seam = int((left[2] + right[0]) / 2)
    plans = pair_plans([left, right], img.shape[1], img.shape[0], cw, ch, seam=seam)

    a = take(img, plans[0]["rect"], cw, ch)
    b = tone_match(take(img, plans[1]["rect"], cw, ch), a, args.strength)

    qa_a = qa(plans[0], left, right, cw, ch)
    qa_b = qa(plans[1], right, left, cw, ch)
    cv2.imwrite(str(out / 'before.jpg'), a, [cv2.IMWRITE_JPEG_QUALITY, 92])
    cv2.imwrite(str(out / 'after.jpg'), b, [cv2.IMWRITE_JPEG_QUALITY, 92])

    meta = {"canvas": [cw, ch], "frac": plans[0]["frac"], "seam_x": seam, "tone_strength": args.strength,
            "before": plans[0], "after": plans[1],
            "qa": {"before": qa_a, "after": qa_b,
                   "scale_delta": round(abs(plans[0]["scale"] - plans[1]["scale"]) / plans[0]["scale"], 4)},
            "depth": depth_consistency(depth_of(img), [left, right])}
    if not args.no_vlm:
        try:
            from settings import load as load_cfg
            meta['vlm'] = vlm_check(a, b, load_cfg())
        except Exception as e:
            meta['vlm'] = {"error": str(e)[:200]}
    (out / 'meta.json').write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding='utf-8')
    make_sheet(img, a, b, meta, str(out / 'sheet.jpg'))
    print(json.dumps(meta, ensure_ascii=False, indent=2)[:1200])


if __name__ == '__main__':
    main()

"""v5：取景标准化（不补全、不生成）

思路：
1) 标准画布 1080×1440
2) YOLO + SAM2 拿到每个人的人物掩码
3) 以人物为中心外扩：人物高度占画布固定比例、脚底线固定在画布固定位置、水平居中
   —— 两张图用同一套规则，所以大小/机位一致
4) 窗口越界时：优先平移窗口回图内（保持比例），实在不够的窄边用"逐行墙色"平涂 + 羽化
   （取样自该行真实墙面像素的中位数，保留纵向明暗渐变，不画纹理、不生成）
5) 成对色彩对齐：两张图在 LAB 空间做直方图/均值方差匹配（只统计背景像素）
6) 规则质检 + 大模型复核（只做检查，不参与生成）
"""
import argparse, json, sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from standardize_pair_v2 import (PERSON_FRAC, FEET_Y, load, detect_persons, segment_persons,
                                 depth_of, depth_consistency, vlm_check, make_sheet)


# ---------------------------------------------------------------- 取景
def frame_plan(box, img_w, img_h, cw, ch, frac=PERSON_FRAC, feet=FEET_Y):
    """算出裁剪窗；窗口尽量落在图内（越界就平移），返回 rect + 实际占用的比例。"""
    x1, y1, x2, y2 = box
    ph = max(1.0, y2 - y1)
    scale = (ch * frac) / ph
    win_w, win_h = cw / scale, ch / scale
    cx = (x1 + x2) / 2.0
    left = cx - win_w / 2.0
    top = y2 - (ch * feet) / scale

    # 先平移回图内（保持窗口尺寸不变，优先保住脚底线）
    if win_w <= img_w:
        left = min(max(left, 0), img_w - win_w)
    if win_h <= img_h:
        top = min(max(top, 0), img_h - win_h)

    # 窗口比原图还大：只能降低"人物占比"（画面里多留背景），保证窗口能装进原图
    if win_w > img_w or win_h > img_h:
        k = max(win_w / img_w, win_h / img_h)
        frac_eff = frac / k
        return frame_plan(box, img_w, img_h, cw, ch, frac_eff, feet)
    return {"rect": [left, top, left + win_w, top + win_h], "scale": scale,
            "frac": round(frac, 4), "person_box": [x1, y1, x2, y2]}


def row_wall_colors(img, persons):
    """逐行的墙面颜色（取样自该行非人物、偏亮像素的中位数），用于补窄边。"""
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    not_person = ~cv2.dilate(persons.astype(np.uint8), np.ones((31, 31), np.uint8)).astype(bool)
    colors = np.zeros((img.shape[0], 3), np.float32)
    fallback = np.median(img[not_person & (gray > 100)], axis=0) if (not_person & (gray > 100)).any() \
        else np.array([235, 235, 235], np.float32)
    for y in range(img.shape[0]):
        m = not_person[y] & (gray[y] > 100)
        colors[y] = np.median(img[y][m], axis=0) if m.sum() > 20 else fallback
    # 纵向平滑，避免行间跳变
    k = 31
    pad = np.pad(colors, ((k, k), (0, 0)), mode='edge')
    kernel = np.ones(k) / k
    for c in range(3):
        colors[:, c] = np.convolve(pad[:, c], kernel, mode='same')[k:k + img.shape[0]]
    return colors


def take_frame(img, rect, cw, ch, wall_rows, subject_mask, persons):
    """取窗：图内部分直接采样，图外部分用逐行墙色平涂，接缝羽化 24px。"""
    L, T, R, B = [int(round(v)) for v in rect]
    scale_x = cw / max(1, (R - L))
    scale_y = ch / max(1, (B - T))
    canvas = np.zeros((ch, cw, 3), np.uint8)
    real = np.zeros((ch, cw), bool)

    sx0, sy0 = max(0, L), max(0, T)
    sx1, sy1 = min(img.shape[1], R), min(img.shape[0], B)
    if sx1 > sx0 and sy1 > sy0:
        patch = img[sy0:sy1, sx0:sx1]
        dx0 = int(round((sx0 - L) * scale_x))
        dy0 = int(round((sy0 - T) * scale_y))
        dx1 = min(cw, dx0 + int(round(patch.shape[1] * scale_x)))
        dy1 = min(ch, dy0 + int(round(patch.shape[0] * scale_y)))
        canvas[dy0:dy1, dx0:dx1] = cv2.resize(patch, (dx1 - dx0, dy1 - dy0), interpolation=cv2.INTER_CUBIC)
        real[dy0:dy1, dx0:dx1] = True

    if real.all():
        return canvas, {"pad_pct": 0.0}

    # 逐行墙色：把源图行号映射到画布行
    fill = np.zeros_like(canvas)
    for yc in range(ch):
        ys = int(np.clip(T + yc * (B - T) / ch, 0, img.shape[0] - 1))
        fill[yc, :] = wall_rows[ys]
    out = canvas.copy()
    out[~real] = fill[~real]

    # 只在"真实/填充"交界处羽化，不碰人物
    k = 25
    edge = ((real.astype(np.uint8) * 255) ^ (cv2.erode(real.astype(np.uint8) * 255, np.ones((3, 3), np.uint8))))
    edge = cv2.dilate(edge, np.ones((k, k), np.uint8))
    edge = edge & (~subject_mask.astype(np.uint8) * 255)
    alpha = cv2.GaussianBlur(edge, (k, k), 0).astype(np.float32) / 255.0
    alpha = np.clip(alpha, 0, 0.8)[..., None]
    blurred = cv2.GaussianBlur(out, (k, k), 0)
    out = (out.astype(np.float32) * (1 - alpha) + blurred.astype(np.float32) * alpha).astype(np.uint8)
    return out, {"pad_pct": round(float((~real).mean() * 100), 1)}


# ---------------------------------------------------------------- 成对色彩对齐
def color_match(src, ref, mask_ignore):
    """把 src 的背景色调对齐到 ref（LAB 均值/方差匹配，忽略人物区域）。"""
    a = cv2.cvtColor(src, cv2.COLOR_BGR2LAB).astype(np.float32)
    b = cv2.cvtColor(ref, cv2.COLOR_BGR2LAB).astype(np.float32)
    for c in range(3):
        m = mask_ignore
        if m.sum() < 100:
            continue
        sa, sb = a[..., c][m], b[..., c][m]
        if sa.std() < 1e-3:
            continue
        a[..., c] = (a[..., c] - sa.mean()) / sa.std() * sb.std() + sb.mean()
    a = np.clip(a, 0, 255).astype(np.uint8)
    return cv2.cvtColor(a, cv2.COLOR_LAB2BGR)


def build_one(img, box, masks, idx, cw, ch, wall_rows, persons):
    plan = frame_plan(box, img.shape[1], img.shape[0], cw, ch)
    L, T, R, B = [int(round(v)) for v in plan["rect"]]
    subj = np.zeros((ch, cw), bool)
    ys, xs = np.where(masks[idx])
    if len(xs):
        mx = np.clip(((xs - L) * cw / (R - L)).astype(int), 0, cw - 1)
        my = np.clip(((ys - T) * ch / (B - T)).astype(int), 0, ch - 1)
        subj[my, mx] = True
    frame, stat = take_frame(img, plan["rect"], cw, ch, wall_rows, subj, persons)
    stat.update(scale=round(plan["scale"], 4), frac=plan["frac"], rect=[L, T, R, B])
    return frame, stat, subj


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

    before, mb, subj_b = build_one(img, left, masks, 0, cw, ch, wall_rows, persons)
    after, ma, subj_a = build_one(img, right, masks, 1, cw, ch, wall_rows, persons)

    # 以"训练后"为基准做色彩对齐（只统计背景）
    before = color_match(before, after, ~(subj_b | cv2.dilate(subj_b.astype(np.uint8),
                                                             np.ones((31, 31), np.uint8)).astype(bool)))

    cv2.imwrite(str(out / 'before.jpg'), before, [cv2.IMWRITE_JPEG_QUALITY, 92])
    cv2.imwrite(str(out / 'after.jpg'), after, [cv2.IMWRITE_JPEG_QUALITY, 92])

    meta = {"canvas": [cw, ch], "before": mb, "after": ma,
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

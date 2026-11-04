"""v8：只做取景统一，不换背景、不抠图、不补全。

按最新要求：
1) YOLO 出人物框
2) 统一取景：同一对图用**同一个"人物高度占比"**，保证两张人物一样大；窗口一律落在原图内
   （装不下就把这一对图的占比一起调小，绝不裁到人、绝不外扩补图）
3) 保留各自原来的背景（不做背景统一，不做抠图）
4) 调整色调：以训练前为基准，对训练后做 LAB 均值/方差匹配（可调强度）
5) 质检：规则优先（人物是否完整、占比是否达标、两张尺度/色调差），VLM 只做第二道

为什么不再"抠图+统一背景"：抠图会把鞋/袜边缘切坏（已复现），而取景统一已经能满足
"两张看起来同一机位"的诉求，且零伪影、零生成。
"""
import argparse, json, sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from standardize_pair_v2 import (load, detect_persons, segment_persons,
                                 depth_of, depth_consistency, vlm_check, make_sheet)

PERSON_FRAC = 0.86     # 目标：人物高度占画布
FEET_Y = 0.92          # 目标：脚底线位置
MARGIN = 0.02          # 质检要求人物四周留白
TONE_STRENGTH = 0.7    # 色调对齐强度（0=不调，1=完全对齐）


def pair_framing(boxes, img_w, img_h, cw, ch, target=PERSON_FRAC, feet=FEET_Y):
    """同一对图共用一个 frac：既保证两张人物一样大，又保证窗口完全落在原图内。"""
    frac = target
    for (x1, y1, x2, y2) in boxes:
        ph = max(1.0, y2 - y1)
        frac = max(frac, ph / img_h, (cw / ch) * ph / img_w)   # 窗口必须装得下
    frac = min(frac, 0.98)
    plans = []
    for i, (x1, y1, x2, y2) in enumerate(boxes):
        ph = max(1.0, y2 - y1)
        scale = (ch * frac) / ph
        win_w, win_h = cw / scale, ch / scale
        cx = (x1 + x2) / 2.0
        left = cx - win_w / 2.0
        # 尽量往外侧靠：左边的人贴左、右边的人贴右，少把隔壁那个人框进来
        if i == 0:
            left = min(left, x1 - win_w * 0.12)
        else:
            left = max(left, x2 + win_w * 0.12 - win_w)
        left = min(max(left, 0), max(0.0, img_w - win_w))
        top = min(max(y2 - (ch * feet) / scale, 0), max(0.0, img_h - win_h))
        plans.append({"rect": [left, top, left + win_w, top + win_h],
                      "scale": scale, "frac": round(frac, 4),
                      "win": [round(win_w, 1), round(win_h, 1)]})
    return plans


def take(img, rect, cw, ch):
    L, T, R, B = [int(round(v)) for v in rect]
    patch = img[T:B, L:R]
    if patch.size == 0:
        raise SystemExit('取景为空')
    return cv2.resize(patch, (cw, ch), interpolation=cv2.INTER_CUBIC)


def tone_match(src, ref, strength=TONE_STRENGTH):
    """把 src 的色调往 ref 对齐（LAB 均值/方差），strength 控制力度。"""
    a = cv2.cvtColor(src, cv2.COLOR_BGR2LAB).astype(np.float32)
    b = cv2.cvtColor(ref, cv2.COLOR_BGR2LAB).astype(np.float32)
    for c in range(3):
        sa, sb = a[..., c], b[..., c]
        if sa.std() < 1e-3:
            continue
        target = (sa - sa.mean()) / sa.std() * sb.std() + sb.mean()
        a[..., c] = sa * (1 - strength) + target * strength
    return cv2.cvtColor(np.clip(a, 0, 255).astype(np.uint8), cv2.COLOR_LAB2BGR)


def qa(frame, box, rect, cw, ch, label):
    """规则质检：人物是否完整、占比、边缘留白。"""
    L, T, R, B = rect
    sx, sy = cw / (R - L), ch / (B - T)
    x1, y1, x2, y2 = box
    mx1, my1 = (x1 - L) * sx, (y1 - T) * sy
    mx2, my2 = (x2 - L) * sx, (y2 - T) * sy
    inside = mx1 >= 0 and my1 >= 0 and mx2 <= cw and my2 <= ch
    margin = min(mx1, my1, cw - mx2, ch - my2) / max(cw, ch)
    ratio = (my2 - my1) / ch
    return {"label": label, "person_inside": bool(inside),
            "person_frac": round(float(ratio), 3),
            "min_margin": round(float(margin), 3),
            "cut": bool(not inside or margin < MARGIN)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--src', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--canvas', default='1080x1440')
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
    plans = pair_framing([left, right], img.shape[1], img.shape[0], cw, ch)

    a = take(img, plans[0]["rect"], cw, ch)
    b = take(img, plans[1]["rect"], cw, ch)
    b = tone_match(b, a, args.strength)

    qa_a = qa(a, left, plans[0]["rect"], cw, ch, "before")
    qa_b = qa(b, right, plans[1]["rect"], cw, ch, "after")
    la = float(cv2.cvtColor(a, cv2.COLOR_BGR2LAB)[..., 0].mean())
    lb = float(cv2.cvtColor(b, cv2.COLOR_BGR2LAB)[..., 0].mean())

    cv2.imwrite(str(out / 'before.jpg'), a, [cv2.IMWRITE_JPEG_QUALITY, 92])
    cv2.imwrite(str(out / 'after.jpg'), b, [cv2.IMWRITE_JPEG_QUALITY, 92])

    meta = {"canvas": [cw, ch], "frac": plans[0]["frac"], "tone_strength": args.strength,
            "before": plans[0], "after": plans[1],
            "qa": {"before": qa_a, "after": qa_b,
                   "scale_delta": round(abs(plans[0]["scale"] - plans[1]["scale"]) / plans[0]["scale"], 4),
                   "luma_delta": round(abs(la - lb), 2)},
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

"""历史实验（已弃用）：本脚本有角度符号丢失和横向剪切回归问题。
请使用 grid_rectify_single.py；对比图跳过，只处理单人方格背景。

网格背景校正：用墙面网格当标定物，把网格拉成"绝对竖直/水平"。

只做这件事，不裁切、不抠图、不改背景。
1) Canny + Hough 检直线（先排除人物区域，避免把人体边缘当网格线）
2) 分成"近垂直"和"近水平"两组
3) 用两组直线各自的灭点求出无穷远线 → 仿射矫正（把透视消除，两组线变成平行）
4) 残余旋转：矫正后再测一次竖直线的中位偏角，旋转回来
5) 输出对比：原图 / 校正图 / 残差角度统计

用法：python tools/grid_rectify.py --src 图.jpg --out 目录 [--mask-person]
"""
import argparse, json, sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))


# ---------------------------------------------------------------- 检测
def person_mask(img):
    try:
        from standardize_pair_v2 import detect_persons, segment_persons
        boxes = detect_persons(img)
        if not boxes:
            return None
        masks = segment_persons(img, boxes)
        m = np.zeros(img.shape[:2], bool)
        for x in masks:
            m |= x
        return cv2.dilate(m.astype(np.uint8), np.ones((25, 25), np.uint8)).astype(bool)
    except Exception as e:
        print('person mask skipped:', str(e)[:100])
        return None


def detect_lines(img, exclude=None):
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape
    edges = cv2.Canny(cv2.GaussianBlur(gray, (3, 3), 0), 40, 120)
    if exclude is not None:
        edges[exclude] = 0
    lines = cv2.HoughLinesP(edges, 1, np.pi / 720, threshold=60,
                            minLineLength=int(min(h, w) * 0.18), maxLineGap=14)
    return edges, ([] if lines is None else lines[:, 0].tolist())


def split_lines(lines, min_len=80):
    vert, horiz = [], []
    for x1, y1, x2, y2 in lines:
        dx, dy = x2 - x1, y2 - y1
        if abs(dy) < 20 and abs(dx) < min_len:
            continue
        if abs(dy) > 2.5 * abs(dx) and abs(dy) >= min_len:
            vert.append((x1, y1, x2, y2))
        elif abs(dx) > 2.5 * abs(dy) and abs(dx) >= min_len:
            horiz.append((x1, y1, x2, y2))
    return vert, horiz


def angle_of(line, axis='v'):
    """竖直线返回相对竖直的偏角，水平线返回相对水平的偏角，范围 (-90, 90]。"""
    x1, y1, x2, y2 = line
    if axis == 'v':
        a = float(np.degrees(np.arctan2(x2 - x1, y2 - y1)))
    else:
        a = float(np.degrees(np.arctan2(y2 - y1, x2 - x1)))
    while a > 90:
        a -= 180
    while a <= -90:
        a += 180
    return a


def vanishing_point(lines, axis='v'):
    """最小二乘求灭点。竖直线：x = a*y + b；水平线：y = c*x + d。"""
    if len(lines) < 2:
        return None
    rows, rhs = [], []
    for x1, y1, x2, y2 in lines:
        if axis == 'v':
            if abs(y2 - y1) < 1e-6:
                continue
            a = (x2 - x1) / (y2 - y1)
            b = x1 - a * y1
            rows.append([1.0, -a]); rhs.append(b)          # x - a*y = b
        else:
            if abs(x2 - x1) < 1e-6:
                continue
            c = (y2 - y1) / (x2 - x1)
            d = y1 - c * x1
            rows.append([-c, 1.0]); rhs.append(d)          # -c*x + y = d
    if len(rows) < 2:
        return None
    A = np.array(rows, np.float64)
    b = np.array(rhs, np.float64)
    try:
        sol, *_ = np.linalg.lstsq(A, b, rcond=None)
    except np.linalg.LinAlgError:
        return None
    return np.array([sol[0], sol[1], 1.0])


# ---------------------------------------------------------------- 校正
def _median_dir(lines, axis):
    """返回该线族的中位方向单位向量。"""
    if not lines:
        return None
    angs = [angle_of(l, axis) for l in lines]
    a = float(np.median(angs))
    if axis == 'v':          # 竖直线：方向 (dx, dy)，偏角相对 y 轴
        return np.array([np.sin(np.radians(a)), np.cos(np.radians(a))])
    return np.array([np.cos(np.radians(a)), np.sin(np.radians(a))])


def rectify(img, vert, horiz):
    """两步矫正：
    1) 用两组直线的灭点做仿射矫正 → 两组线各自变平行
    2) 用两组线的中位方向做一次线性变换 → 竖直=90°、水平=0°
    """
    h, w = img.shape[:2]
    info = {}
    vp_v = vanishing_point(vert, 'v')
    vp_h = vanishing_point(horiz, 'h')
    info["vp_v"] = None if vp_v is None else [round(float(v), 1) for v in vp_v[:2]]
    info["vp_h"] = None if vp_h is None else [round(float(v), 1) for v in vp_h[:2]]

    cur = img.copy()
    total = np.eye(3)
    if len(vert) >= 6 and len(horiz) >= 6 and vp_v is not None and vp_h is not None:
        l_inf = np.cross(vp_v, vp_h)
        if abs(l_inf[2]) > 1e-9:
            l_inf = l_inf / l_inf[2]
            if max(abs(l_inf[0]), abs(l_inf[1])) <= 0.01:
                H1 = np.array([[1, 0, 0], [0, 1, 0], [l_inf[0], l_inf[1], 1.0]], np.float64)
                cur = cv2.warpPerspective(img, H1, (w, h), flags=cv2.INTER_CUBIC,
                                          borderMode=cv2.BORDER_REPLICATE)
                total = H1
                info["affine_rectified"] = True

    info["H_total"] = [[round(float(v), 6) for v in row] for row in total]
    return cur, info


def residual_angles(img, exclude=None):
    _, lines = detect_lines(img, exclude)
    vert, horiz = split_lines(lines)
    av = [abs(angle_of(l, 'v')) for l in vert]
    ah = [abs(angle_of(l, 'h')) for l in horiz]
    def stat(a):
        return None if not a else {"n": len(a), "median": round(float(np.median(a)), 3),
                                   "p90": round(float(np.percentile(a, 90)), 3),
                                   "max": round(float(np.max(a)), 3)}
    return {"vertical": stat(av), "horizontal": stat(ah)}, vert, horiz


def rotate(img, deg):
    h, w = img.shape[:2]
    M = cv2.getRotationMatrix2D((w / 2, h / 2), deg, 1.0)
    return cv2.warpAffine(img, M, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)


def draw_lines(img, vert, horiz, color_v=(0, 0, 255), color_h=(255, 0, 0)):
    out = img.copy()
    for x1, y1, x2, y2 in vert:
        cv2.line(out, (x1, y1), (x2, y2), color_v, 2)
    for x1, y1, x2, y2 in horiz:
        cv2.line(out, (x1, y1), (x2, y2), color_h, 2)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--src', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--max-rotate', type=float, default=8.0)
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    img = cv2.imread(args.src)
    if img is None:
        raise SystemExit('读不到图')
    h, w = img.shape[:2]
    if max(h, w) > 2600:
        s = 2600 / max(h, w)
        img = cv2.resize(img, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA)
    h, w = img.shape[:2]

    excl = person_mask(img)
    before_stat, vert0, horiz0 = residual_angles(img, excl)
    cv2.imwrite(str(out / '0_lines_before.jpg'), draw_lines(img, vert0, horiz0), [cv2.IMWRITE_JPEG_QUALITY, 90])

    rect, info = rectify(img, vert0, horiz0)
    rect = rect  # 方向已在 rectify 内对齐
    excl_rect = None
    if excl is not None:
        if info.get("H_total"):
            H = np.array(info["H_total"], np.float64)
            excl_rect = cv2.warpPerspective(excl.astype(np.uint8) * 255, H, (w, h),
                                            flags=cv2.INTER_NEAREST) > 0
        else:
            excl_rect = excl
    after_stat, vert1, horiz1 = residual_angles(rect, excl_rect)
    cv2.imwrite(str(out / '1_rectified.jpg'), rect, [cv2.IMWRITE_JPEG_QUALITY, 92])
    cv2.imwrite(str(out / '2_lines_after.jpg'), draw_lines(rect, vert1, horiz1), [cv2.IMWRITE_JPEG_QUALITY, 90])

    # 残余旋转：按竖直线的中位偏角转回来（竖直线数量足够才转）
    rot_deg = 0.0
    if after_stat["vertical"] and after_stat["vertical"]["n"] >= 8:
        rot_deg = float(np.clip(after_stat["vertical"]["median"], -args.max_rotate, args.max_rotate))
    final = rotate(rect, -rot_deg) if abs(rot_deg) > 0.05 else rect
    excl_final = excl_rect
    if excl_final is not None and abs(rot_deg) > 0.05:
        M = cv2.getRotationMatrix2D((w / 2, h / 2), -rot_deg, 1.0)
        excl_final = cv2.warpAffine(excl_final.astype(np.uint8) * 255, M, (w, h),
                                    flags=cv2.INTER_NEAREST) > 0
    # 竖向剪切：把"横线"也拉平（竖向剪切不会破坏已经竖直的竖线）
    for _ in range(3):
        st = residual_angles(final, excl_final)[0]
        if not st["horizontal"] or st["horizontal"]["n"] < 4:
            break
        if abs(st["horizontal"]["median"]) < 0.25:
            break
        m = float(np.tan(np.radians(st["horizontal"]["median"])))
        if abs(m) < 1e-4:
            break
        k3 = np.float32([[1, 0, 0], [-m, 1, 0]])
        final = cv2.warpAffine(final, k3, (w, h), flags=cv2.INTER_CUBIC,
                               borderMode=cv2.BORDER_REPLICATE)
        if excl_final is not None:
            excl_final = cv2.warpAffine(excl_final.astype(np.uint8) * 255, k3, (w, h),
                                        flags=cv2.INTER_NEAREST) > 0
    final_stat, vert2, horiz2 = residual_angles(final, excl_final)
    cv2.imwrite(str(out / '3_final.jpg'), final, [cv2.IMWRITE_JPEG_QUALITY, 92])
    cv2.imwrite(str(out / '4_lines_final.jpg'), draw_lines(final, vert2, horiz2), [cv2.IMWRITE_JPEG_QUALITY, 90])

    meta = {"size": [w, h], "lines_before": {"v": len(vert0), "h": len(horiz0)},
            "lines_after": {"v": len(vert1), "h": len(horiz1)},
            "before": before_stat, "after_rectify": after_stat,
            "rotate_deg": round(rot_deg, 3), "final": final_stat, **info}
    (out / 'meta.json').write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(meta, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()

"""Approved two-axis square-grid calibration; no framing or CLI dependencies."""
import math
import cv2
import numpy as np

class UncertainGrid(ValueError):
    pass


def transform(points, H):
    p = np.c_[np.asarray(points).reshape(-1, 2), np.ones(np.asarray(points).size // 2)] @ H.T
    if np.any(np.abs(p[:, 2]) < 1e-8):
        raise UncertainGrid('transform_at_infinity')
    return p[:, :2] / p[:, 2:3]


def detect_segments(img, exclude, verification=False):
    h, w = img.shape[:2]
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(cv2.GaussianBlur(gray, (3, 3), 0), 45, 130)
    edges[exclude] = 0
    # Short exposed pieces beside the subject are valuable; old 0.18*size lost them.
    lines = cv2.HoughLinesP(edges, 1, np.pi / 1440, 35 if verification else 40,
                           minLineLength=max(35, int(min(h, w) * .055)), maxLineGap=8)
    if lines is None:
        raise UncertainGrid('no_lines')
    lines = lines[:, 0].astype(float)
    delta = lines[:, 2:] - lines[:, :2]
    length = np.linalg.norm(delta, axis=1)
    v = lines[(np.abs(delta[:, 0]) < .22 * np.abs(delta[:, 1])) & (length > 35)]
    u = lines[(np.abs(delta[:, 1]) < .22 * np.abs(delta[:, 0])) & (length > 35)]
    return v, u


def family_data(lines, axis, N):
    pts = transform(lines.reshape(-1, 2), N).reshape(-1, 4)
    if axis == 'v':
        pts = pts[:, [1, 0, 3, 2]]  # dependent = slope * independent + intercept
    dx = pts[:, 2] - pts[:, 0]
    slope = (pts[:, 3] - pts[:, 1]) / dx
    intercept = pts[:, 1] - slope * pts[:, 0]
    weights = np.minimum(np.abs(dx), .25)
    return intercept, slope, weights


def robust_family(lines, axis, N):
    if len(lines) < 12:
        raise UncertainGrid('too_few_' + axis + '_segments')
    b, m, weight = family_data(lines, axis, N)
    X = np.c_[np.ones(len(b)), b]
    rng = np.random.default_rng(17)
    best = None
    threshold = np.tan(np.radians(.32))
    # Fit slope = a + q*intercept. This includes parallel lines / infinite VPs.
    for _ in range(700):
        i, j = rng.choice(len(b), 2, replace=False)
        if abs(b[i] - b[j]) < .12:
            continue
        q = (m[i] - m[j]) / (b[i] - b[j])
        a = m[i] - q * b[i]
        if abs(q) > .65 or abs(a) > .22:
            continue
        err = np.abs(m - (a + q * b))
        score = np.sum(weight * np.maximum(0, 1 - (err / threshold) ** 2))
        if best is None or score > best[0]:
            best = score, np.array([a, q])
    if best is None:
        raise UncertainGrid('unstable_' + axis + '_vanishing_direction')
    beta = best[1]
    for _ in range(8):
        err = m - X @ beta
        robust = np.maximum(0, 1 - (err / threshold) ** 2) ** 2
        sw = np.sqrt(weight * robust)
        beta = np.linalg.lstsq(X * sw[:, None], m * sw, rcond=None)[0]
    keep = np.abs(m - X @ beta) < threshold
    if keep.sum() < 10 or np.ptp(b[keep]) < .2:
        raise UncertainGrid('insufficient_' + axis + '_spatial_support')
    return beta, keep


def lattice(lines, H, axis, size):
    """Merge duplicate edge detections, find a regularly spaced physical line family."""
    p = transform(lines.reshape(-1, 2), H).reshape(-1, 2, 2)
    coord = np.mean(p[:, :, 0 if axis == 'v' else 1], axis=1)
    order = np.argsort(coord)
    groups = []
    for idx in order:
        if not groups or coord[idx] - np.median(coord[groups[-1]]) > size * .0035:
            groups.append([int(idx)])
        else:
            groups[-1].append(int(idx))
    centers = np.array([np.median(coord[g]) for g in groups])
    if len(centers) < 7:
        raise UncertainGrid('too_few_distinct_' + axis + '_grid_lines')
    gaps = np.diff(centers)
    candidates = []
    for gap in gaps:
        for divisor in (1, 2, 3):
            pitch = gap / divisor
            if size * .012 < pitch < size * .095:
                candidates.append(pitch)
    best = None
    for pitch in candidates:
        for origin in centers:
            index = np.rint((centers - origin) / pitch)
            residual = np.abs(centers - origin - index * pitch)
            ok = residual < max(2., .13 * pitch)
            occupied = np.unique(index[ok])
            if len(occupied) < 7:
                continue
            occupancy = len(occupied) / (np.ptp(occupied) + 1)
            score = ok.sum() * (.45 + .55 * occupancy)
            if best is None or score > best[0]:
                best = score, pitch, origin, ok
    if best is None:
        raise UncertainGrid('no_regular_' + axis + '_lattice')
    _, pitch, origin, ok = best
    for _ in range(3):
        index = np.rint((centers - origin) / pitch)
        A = np.c_[np.ones(ok.sum()), index[ok]]
        origin, pitch = np.linalg.lstsq(A, centers[ok], rcond=None)[0]
        residual = np.abs(centers - origin - index * pitch)
        ok = residual < max(2., .13 * pitch)
    occupied = np.unique(index[ok])
    if ok.sum() < 7 or len(occupied) / (np.ptp(occupied) + 1) < .48:
        raise UncertainGrid('sparse_' + axis + '_lattice')
    selected = np.array([i for k, g in enumerate(groups) if ok[k] for i in g], dtype=int)
    return float(pitch), selected, {
        'distinct_lines': int(ok.sum()), 'pitch': float(pitch),
        'spacing_error_fraction': float(np.median(residual[ok]) / pitch),
        'range': [float(centers[ok].min()), float(centers[ok].max())],
    }


def solve_grid(vert, horiz, shape):
    h, w = shape[:2]
    size = max(h, w)
    N = np.array([[1 / size, 0, -w / (2 * size)], [0, 1 / size, -h / (2 * size)], [0, 0, 1.]])
    v, kv = robust_family(vert, 'v', N)
    u, ku = robust_family(horiz, 'h', N)

    def matrix(v, u):
        # Columns are homogeneous horizontal / vertical vanishing directions.
        inverse = np.array([[1, v[0], 0], [u[0], 1, 0], [-u[1], -v[1], 1.]])
        return np.linalg.inv(N) @ np.linalg.inv(inverse) @ N

    H = matrix(v, u)
    sv, sh = vert[kv], horiz[ku]
    _, iv, _ = lattice(sv, H, 'v', size)
    _, ih, _ = lattice(sh, H, 'h', size)
    # Refit only lines belonging to the repeated grid, excluding doors/poster edges.
    sv, sh = sv[iv], sh[ih]
    v, kv = robust_family(sv, 'v', N)
    u, ku = robust_family(sh, 'h', N)
    sv, sh = sv[kv], sh[ku]
    H = matrix(v, u)
    px, _, lv = lattice(sv, H, 'v', size)
    py, _, lh = lattice(sh, H, 'h', size)
    ratio = py / px
    if not .84 < ratio < 1.19:
        raise UncertainGrid('square_grid_scale_ambiguous')
    # Equal square-cell pitch; area-preserving scale, no arbitrary skinny/tall target.
    metric = np.diag([math.sqrt(ratio), 1 / math.sqrt(ratio), 1.])
    H = np.linalg.inv(N) @ metric @ N @ H
    return H / H[2, 2], sv, sh, {'vertical': lv, 'horizontal': lh, 'square_scale_ratio': ratio}


def angles(lines, axis):
    d = lines[:, 2:] - lines[:, :2]
    a = np.degrees(np.arctan2(d[:, 0], d[:, 1]) if axis == 'v' else np.arctan2(d[:, 1], d[:, 0]))
    return (a + 90) % 180 - 90


def stats(v, h):
    result = {}
    for axis, lines in [('vertical', v), ('horizontal', h)]:
        a = angles(lines, 'v' if axis == 'vertical' else 'h')
        length = np.linalg.norm(lines[:, 2:] - lines[:, :2], axis=1)
        order = np.argsort(np.abs(a))
        cumulative = (np.cumsum(length[order]) - .5 * length[order]) / length.sum()
        weighted = np.interp([.5, .9], cumulative, np.abs(a)[order])
        result[axis] = {'n': len(a), 'signed_median_deg': float(np.median(a)),
                        'median_deg': float(np.median(np.abs(a))),
                        'p90_deg': float(np.percentile(np.abs(a), 90)),
                        'length_weighted_median_deg': float(weighted[0]),
                        'length_weighted_p90_deg': float(weighted[1])}
    return result


def jacobian(H, point):
    x, y = point
    q = H @ np.array([x, y, 1.])
    return (H[:2, :2] * q[2] - q[:2, None] * H[2:3, :2]) / q[2] ** 2


def bounded_canvas(H, shape, box):
    h, w = shape[:2]
    center = ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2)
    # Keep the local area scale at the subject center unchanged.
    J = jacobian(H, center)
    if np.linalg.det(J) <= 0:
        raise UncertainGrid('flipped_transform')
    scale = 1 / math.sqrt(np.linalg.det(J))
    H = np.diag([scale, scale, 1.]) @ H
    corners = np.array([[0, 0], [w - 1, 0], [w - 1, h - 1], [0, h - 1]], dtype=float)
    denom = np.c_[corners, np.ones(4)] @ H[2]
    if denom.min() <= 0 or denom.max() / denom.min() > 1.65:
        raise UncertainGrid('excessive_perspective')
    singular = []
    for x in (box[0], center[0], box[2]):
        for y in (box[1], center[1], box[3]):
            singular.append(np.linalg.svd(jacobian(H, (x, y)), compute_uv=False))
    singular = np.array(singular)
    anisotropy = float(np.max(singular[:, 0] / singular[:, 1]))
    scale_variation = float(np.max(singular) / np.min(singular))
    # Perspective correction naturally changes scale from head to feet. A person
    # close to the reference board follows that plane approximately; scale spread
    # alone is not proof of a bad correction. Preserve diagnostics, reject extremes.
    if anisotropy > 2.0 or scale_variation > 2.5:
        raise UncertainGrid('extreme_transform_deformation')
    warnings = []
    if anisotropy > 1.18:
        warnings.append('local_anisotropy_notice')
    if scale_variation > 1.4:
        warnings.append('perspective_scale_variation_notice')
    mapped = transform(corners, H)
    low, high = np.floor(mapped.min(0)) - 2, np.ceil(mapped.max(0)) + 2
    ow, oh = np.ceil(high - low + 1).astype(int)
    if ow * oh > w * h * 1.65:
        raise UncertainGrid('excessive_canvas_growth')
    T = np.array([[1., 0, -low[0]], [0, 1, -low[1]], [0, 0, 1]])
    return T @ H, (int(ow), int(oh)), {'max_local_anisotropy': anisotropy,
                                    'local_scale_variation': scale_variation,
                                    'warnings': warnings}


def measure_grid(img, exclude, H, v, h):
    # Independent detection from the rendered pixels, restricted to the grid hull.
    vh = np.concatenate([v, h]).reshape(-1, 2)
    hull = cv2.convexHull(transform(vh, H).astype(np.float32)).astype(np.int32)
    region = np.zeros(img.shape[:2], np.uint8)
    cv2.fillConvexPoly(region, hull, 1)
    # A grid requires BOTH families in the same region. Isolated poster/door
    # lines may share a VP, but should not expand the QA region past the grid.
    vp = transform(v.reshape(-1, 2), H)
    hp = transform(h.reshape(-1, 2), H)
    xlo, xhi = np.percentile(hp[:, 0], [3, 97])
    ylo, yhi = np.percentile(vp[:, 1], [3, 97])
    yy, xx = np.indices(region.shape)
    region[(xx < xlo) | (xx > xhi) | (yy < ylo) | (yy > yhi)] = 0
    region = cv2.erode(region, np.ones((15, 15), np.uint8))
    rv, rh = detect_segments(img, exclude | (region == 0), verification=True)
    # Do not select angles near zero here: tilted output must be able to FAIL QA.
    if len(rv) < 12 or len(rh) < 12:
        raise UncertainGrid('insufficient_independent_verification_lines')
    return stats(rv, rh), rv, rh


def validate_angles(before, after):
    """Separate usable residuals from an unreliable / visibly worsening warp.

    Thresholds are product tolerances, not a claim of calibrated camera accuracy.
    Keep raw segment statistics, but use length support for acceptance decisions.
    """
    warnings = []
    for axis in ('vertical', 'horizontal'):
        b, a = before[axis], after[axis]
        bm = b.get('length_weighted_median_deg', b['median_deg'])
        bp = b.get('length_weighted_p90_deg', b['p90_deg'])
        am = a.get('length_weighted_median_deg', a['median_deg'])
        ap = a.get('length_weighted_p90_deg', a['p90_deg'])
        if am > 2.0 or ap > 4.0:
            raise UncertainGrid('residual_' + axis + '_angle_too_large')
        if am > bm + .5 and ap > bp + .8:
            raise UncertainGrid(axis + '_became_worse')
        if a['median_deg'] > .3 or a['p90_deg'] > .8:
            warnings.append(axis + '_residual_notice')
        if ap > bp + .5:
            warnings.append(axis + '_tail_residual_increased')
    return warnings


def grid_transform(image, subject):
    """Return source→rectified matrix and QA metadata; keep image sampling separate."""
    img = image
    h, w = img.shape[:2]
    if max(h, w) > 3000:
        raise UncertainGrid('image_exceeds_3000px_experiment_limit')
    box, boxes, masks = subject.box, subject.boxes, subject.masks
    report = {'method': 'single-square-grid-joint-homography-v2.3', 'action': 'grid_homography'}
    # SAM frees exposed grid beside shoulders/legs that a broad box hides.
    # This mask is only for detection; every output pixel uses the SAME H.
    exclude = np.zeros((h, w), np.uint8)
    pad = max(8, int(min(w, h) * .012))
    for b, mask in zip(boxes, masks):
        x1, y1, x2, y2 = [int(x) for x in b]
        if mask.sum() < .15 * max(1, (x2-x1) * (y2-y1)):
            mask = np.zeros((h, w), bool)
            mask[max(0, y1):min(h, y2), max(0, x1):min(w, x2)] = True
        exclude[mask] = 1
        # Include face stickers even when SAM only finds exposed skin.
        head_end = y1 + int((y2 - y1) * .21)
        exclude[max(0, y1):min(h, head_end), max(0, x1):min(w, x2)] = 1
    coarse = subject.trace['vlm'].get('box')
    if coarse is not None:
        x1, y1, x2, y2 = map(int, coarse)
        exclude[max(0, y1):min(h, y1+int((y2-y1)*.21)), max(0, x1):min(w, x2)] = 1
    exclude = cv2.dilate(exclude, np.ones((2 * pad + 1, 2 * pad + 1), np.uint8)) > 0
    v, u = detect_segments(img, exclude)
    H, sv, sh, grid = solve_grid(v, u, img.shape)
    before, _, _ = measure_grid(img, exclude, np.eye(3), sv, sh)
    report.update({'size': [w, h], 'subject_box': box, 'grid': grid, 'before': before,
                   'fit_reference_angles': stats(sv, sh)})
    H, size, guard = bounded_canvas(H, img.shape, box)
    # Temporary render for independent grid QA; final output samples original only once.
    result = cv2.warpPerspective(img, H, size, flags=cv2.INTER_CUBIC,
                                 borderMode=cv2.BORDER_CONSTANT, borderValue=(242, 242, 242))
    valid = cv2.warpPerspective(np.full((h, w), 255, np.uint8), H, size, flags=cv2.INTER_NEAREST)
    warped_exclude = cv2.warpPerspective(exclude.astype(np.uint8), H, size,
                                        flags=cv2.INTER_NEAREST) > 0
    after, rv, rh = measure_grid(result, warped_exclude | (valid == 0), H, sv, sh)
    report.update({'after': after, 'guard': guard,
                   'H_source_to_output': H.tolist(), 'output_size': list(size),
                   'blank_fraction': float((valid == 0).mean())})
    report['warnings'] = guard['warnings'] + validate_angles(before, after)
    return H, report

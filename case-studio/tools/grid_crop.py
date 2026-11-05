"""Grid-led rectangular framing after rectification, without any resampling.

Body clipping is allowed. The grid sets the frame; the subject's head/upper body
and horizontal position are preferences, not a whole-body containment rule.
"""
from pathlib import Path

import cv2
import numpy as np


class CropUnavailable(ValueError):
    pass


def project(points, H):
    points = np.asarray(points, float).reshape(-1, 2)
    q = np.c_[points, np.ones(len(points))] @ np.asarray(H).T
    if not np.isfinite(q).all() or np.any(np.abs(q[:, 2]) < 1e-8):
        raise CropUnavailable('invalid_grid_projection')
    return q[:, :2] / q[:, 2:]


def content_mask(image):
    """Exclude substantial, nearly black full-edge letterbox bands only.

    Interior dark clothes never become holes in the valid image. Small dark
    edges or an almost entirely black image are not treated as letterboxing.
    """
    h, w = image.shape[:2]
    dark = image.max(axis=2) <= 20
    bounds = [0, 0, w, h]
    for axis, start_index, end_index in ((1, 1, 3), (0, 0, 2)):
        uniform = dark.mean(axis=axis) >= .995
        n = len(uniform)
        for reverse in (False, True):
            scan = uniform[::-1] if reverse else uniform
            count = int(np.argmin(scan)) if not scan.all() else n
            if max(5, int(n * .015)) <= count <= n * .3:
                bounds[end_index if reverse else start_index] = n-count if reverse else count
    mask = np.zeros((h, w), np.uint8)
    x1, y1, x2, y2 = bounds
    mask[y1:y2, x1:x2] = 255
    return mask, bounds


def line_lattice(coordinates, size):
    groups = []
    for coordinate in np.sort(coordinates):
        if not groups or coordinate-np.mean(groups[-1]) > .0035*size:
            groups.append([coordinate])
        else:
            groups[-1].append(coordinate)
    centers = np.array([np.mean(g) for g in groups])
    if len(centers) < 4:
        raise CropUnavailable('insufficient_distinct_crop_grid_lines')
    pitch = float(np.median(np.diff(centers)))
    index = np.rint((centers-centers[0])/pitch)
    origin, pitch = np.linalg.lstsq(np.c_[np.ones(len(index)), index], centers, rcond=None)[0]
    return float(origin), float(pitch)


def framing_segments(image, safe, bounds, vertical, horizontal):
    """Recover exposed grid fragments omitted by the conservative fitting mask.

    This detection ONLY sets framing. It cannot change H or corrected pixels.
    Lines must follow the already calibrated grid's direction and lattice phase.
    """
    h, w = image.shape[:2]
    edges = cv2.Canny(cv2.GaussianBlur(cv2.cvtColor(image, cv2.COLOR_BGR2GRAY), (3, 3), 0), 45, 130)
    edges[~safe] = 0
    edges[:, :max(0, int(bounds[0]))] = 0
    edges[:, min(w, int(bounds[2])):] = 0
    lines = cv2.HoughLinesP(edges, 1, np.pi/1440, 20,
                           minLineLength=max(20, int(min(h, w)*.02)), maxLineGap=8)
    if lines is None:
        return vertical, horizontal
    lines = lines[:, 0].astype(float).reshape(-1, 2, 2)
    delta = lines[:, 1]-lines[:, 0]
    candidates = [lines[np.abs(delta[:, 0]) < np.abs(delta[:, 1])*.07],
                  lines[np.abs(delta[:, 1]) < np.abs(delta[:, 0])*.07]]
    result = []
    for axis, (found, reference) in enumerate(zip(candidates, (vertical, horizontal))):
        origin, pitch = line_lattice(reference.reshape(-1, 2, 2)[:, :, axis].mean(axis=1), max(h, w))
        coordinate = found[:, :, axis].mean(axis=1)
        error = np.abs((coordinate-origin+pitch/2) % pitch-pitch/2)
        found = found[error < max(3., .15*pitch)]
        result.append(np.concatenate([reference.reshape(-1, 4), found.reshape(-1, 4)]))
    return result


def grid_bounds(vertical, horizontal, H, shape, extent_lines=None):
    """Require overlapping support from both line families, not isolated edges."""
    v = project(vertical, H).reshape(-1, 2, 2)
    u = project(horizontal, H).reshape(-1, 2, 2)
    if len(v) < 4 or len(u) < 4:
        raise CropUnavailable('insufficient_grid_support_for_crop')
    vx = np.percentile(v[:, :, 0].mean(axis=1), [1, 99])
    uy = np.percentile(u[:, :, 1].mean(axis=1), [1, 99])
    hx = np.percentile(u[:, :, 0], [3, 97])
    vy = np.percentile(v[:, :, 1], [3, 97])
    # Half a percent gives breathing room without including an adjacent poster.
    h, w = shape[:2]
    pad = .005 * min(h, w)
    b = [max(vx[0], hx[0])-pad, max(uy[0], vy[0])-pad,
         min(vx[1], hx[1])+pad, min(uy[1], vy[1])+pad]
    if extent_lines is not None:
        # Fitting inliers deliberately omit curved/noisy fragments near the
        # board's ends. Use the broader detected family for framing, anchored
        # horizontally to the accepted grid so adjacent posters cannot expand it.
        ev, eh = [project(lines, H).reshape(-1, 2, 2) for lines in extent_lines]
        dv, dh = ev[:, 1]-ev[:, 0], eh[:, 1]-eh[:, 0]
        cx = ev[:, :, 0].mean(axis=1)
        ev = ev[(cx >= b[0]) & (cx <= b[2]) &
                (np.abs(dv[:, 0]) < np.abs(dv[:, 1]) * np.tan(np.radians(4)))]
        overlap = np.minimum(eh[:, :, 0].max(axis=1), b[2])-np.maximum(eh[:, :, 0].min(axis=1), b[0])
        eh = eh[(overlap > .12*(b[2]-b[0])) &
                (np.abs(dh[:, 1]) < np.abs(dh[:, 0]) * np.tan(np.radians(4)))]
        if len(ev) >= 8 and len(eh) >= 8:
            vy = np.percentile(ev[:, :, 1], [1, 99])
            hy = np.percentile(eh[:, :, 1].mean(axis=1), [1, 99])
            # Allow one cell beyond the outer horizontal fragment, but still
            # require vertical evidence there. No extrapolation to the feet.
            _, pitch = line_lattice(u[:, :, 1].mean(axis=1), max(h, w))
            pitch = max(8., min(pitch, .08*h))
            b[1] = min(b[1], max(vy[0], hy[0]-pitch)-pad)
            b[3] = max(b[3], min(vy[1], hy[1]+pitch)+pad)
    b = np.clip(b, [0, 0, 0, 0], [w, h, w, h])
    if b[2]-b[0] < .2*w or b[3]-b[1] < .25*h:
        raise CropUnavailable('grid_crop_support_too_small')
    return b.tolist()


def integral(mask):
    return cv2.integral(mask.astype(np.uint8), sdepth=cv2.CV_64F)


def area(table, box):
    x1, y1, x2, y2 = box
    return float(table[y2, x2] - table[y1, x2] - table[y2, x1] + table[y1, x1])


def choose_rectangle(safe, bounds, subject_mask, subject_box):
    """Search grid-contained, fully valid rectangles, preferring head/torso.

    A common valid span across each candidate's rows handles the slanted canvas
    edges. An integral-mask check also rejects internal holes. This is a bounded
    framing search, not a claim to find the global largest inscribed rectangle.
    """
    h, w = safe.shape
    gx1, gy1, gx2, gy2 = bounds
    sx1, sy1, sx2, sy2 = subject_box
    margin = .018 * (gy2-gy1)
    # Occlusion can hide many top lines. The subject's visible head is a better
    # top anchor; valid pixels still constrain it. Do not extend down to feet.
    gy1 = min(gy1, sy1-margin)
    roi = [max(0, int(np.ceil(gx1))), max(0, int(np.ceil(gy1))),
           min(w, int(np.floor(gx2))), min(h, int(np.floor(gy2)))]
    x1, y1, x2, y2 = roi
    rw, rh = x2-x1, y2-y1
    if rw < 16 or rh < 16 or not np.any(subject_mask):
        raise CropUnavailable('empty_crop_region_or_subject')
    rows = safe[y1:y2, x1:x2]
    exists = rows.any(axis=1)
    left = np.where(exists, rows.argmax(axis=1)+x1, x2)
    right = np.where(exists, x2-rows[:, ::-1].argmax(axis=1), x1)
    invalid = integral(~safe)
    person = integral(subject_mask)
    upper = subject_mask.copy()
    upper[max(0, int(sy1+.6*(sy2-sy1))):] = False
    head = subject_mask.copy()
    head[max(0, int(sy1+.2*(sy2-sy1))):] = False
    upper_i, head_i = integral(upper), integral(head)
    totals = [max(1., table[-1, -1]) for table in (person, upper_i, head_i)]
    # Include the first/last nonempty rows to remove letterboxing precisely.
    active = np.flatnonzero(exists)
    if not len(active):
        raise CropUnavailable('no_valid_grid_pixels')
    tops = np.unique(np.r_[np.linspace(y1, y1+.22*rh, 28).astype(int), y1+active[0]])
    bottoms = np.unique(np.r_[np.linspace(y2-.35*rh, y2, 40).astype(int), y1+active[-1]+1])
    best = None
    subject_cx = (sx1+sx2)/2
    for top in tops:
        for bottom in bottoms:
            if bottom-top < .45*rh or top < y1 or bottom > y2:
                continue
            lo, hi = int(left[top-y1:bottom-y1].max()), int(right[top-y1:bottom-y1].min())
            if hi-lo < .4*rw:
                continue
            # Usually the whole grid wins. A modest centered trim is available
            # when the grid is much wider on one side of the subject.
            for width in np.unique([hi-lo, int(.9*(hi-lo)), int(.8*(hi-lo))]):
                xx = int(np.clip(round(subject_cx-width/2), lo, hi-width))
                box = [xx, int(top), xx+int(width), int(bottom)]
                if area(invalid, box) != 0:
                    continue
                fractions = [area(table, box)/total for table, total in
                             zip((person, upper_i, head_i), totals)]
                grid_fraction = width*(bottom-top)/(rw*rh)
                centered = max(0., 1-abs((box[0]+box[2])/2-subject_cx)/(width/2))
                headroom = np.clip((sy1-top)/max(1., margin), 0, 1)
                score = (.5*grid_fraction + .15*fractions[0] + .2*fractions[1]
                         + .5*fractions[2] + .08*centered + .04*headroom)
                if best is None or score > best[0]:
                    best = score, box, fractions, grid_fraction
    if best is None:
        raise CropUnavailable('no_safe_grid_rectangle')
    _, box, fractions, grid_fraction = best
    return box, {'requested_bounds': roi, 'subject_mask_retained_fraction': fractions[0],
                 'upper_subject_mask_retained_fraction': fractions[1],
                 'head_band_mask_retained_fraction': fractions[2],
                 'frame_retained_fraction': float(grid_fraction)}


def crop_rectified(image, valid, source, source_mask, box, H, vertical, horizontal, extent_lines=None):
    """Return an unscaled pixel slice and reproducible coordinates/diagnostics."""
    h, w = image.shape[:2]
    content, content_bounds = content_mask(source)
    content = cv2.warpPerspective(content, H, (w, h), flags=cv2.INTER_NEAREST)
    # Four-pixel inset also removes cubic interpolation contamination at edges.
    safe = cv2.erode(((valid > 0) & (content > 0)).astype(np.uint8),
                     np.ones((9, 9), np.uint8), borderType=cv2.BORDER_CONSTANT, borderValue=0) > 0
    subject = cv2.warpPerspective(source_mask.astype(np.uint8), H, (w, h),
                                  flags=cv2.INTER_NEAREST) > 0
    x1, y1, x2, y2 = box
    p = project([[x1, y1], [x2, y1], [x2, y2], [x1, y2]], H)
    subject_box = [*p.min(axis=0), *p.max(axis=0)]
    bounds = grid_bounds(vertical, horizontal, H, image.shape, extent_lines)
    if extent_lines is not None:
        vp, hp = [project(lines, H).reshape(-1, 4) for lines in (vertical, horizontal)]
        visible = framing_segments(image, safe, bounds, vp, hp)
        bounds = grid_bounds(vp, hp, np.eye(3), image.shape, visible)
    rect, metrics = choose_rectangle(safe, bounds, subject, subject_box)
    x1, y1, x2, y2 = rect
    if not safe[y1:y2, x1:x2].all():
        raise CropUnavailable('crop_contains_invalid_pixels')
    T = np.array([[1., 0., -x1], [0., 1., -y1], [0., 0., 1.]])
    report = {'status': 'cropped', 'policy': 'grid_first_partial_body_allowed',
              'bounds_xyxy': rect, 'grid_bounds_xyxy': bounds,
              'source_content_bounds_xyxy': content_bounds,
              'output_size': [x2-x1, y2-y1], 'valid_fraction': 1.,
              'H_source_to_crop': (T @ H).tolist(),
              'resampled': False, **metrics}
    return image[y1:y2, x1:x2].copy(), report


def save_crop_preview(out, full, cropped, box):
    """Same display scale on both sides, so framing is visually reviewable."""
    from PIL import Image, ImageDraw
    left = full.copy()
    x1, y1, x2, y2 = box
    cv2.rectangle(left, (x1, y1), (x2-1, y2-1), (70, 170, 70), 4)
    scale = min(800/full.shape[0], 1.)
    ims = [Image.fromarray(cv2.cvtColor(a, cv2.COLOR_BGR2RGB)) for a in (left, cropped)]
    ims = [im.resize((round(im.width*scale), round(im.height*scale)), Image.Resampling.LANCZOS) for im in ims]
    canvas = Image.new('RGB', (sum(im.width for im in ims)+60, ims[0].height+60), '#eeeae3')
    draw = ImageDraw.Draw(canvas)
    x = 20
    for label, im in zip(('RECTIFIED / CROP FRAME', 'GRID CROP / NO RESIZE'), ims):
        draw.text((x, 14), Path(out).name+'  '+label, fill='#26352c')
        canvas.paste(im, (x, 40))
        x += im.width+20
    canvas.save(Path(out) / 'crop_preview.jpg', quality=94)

"""Axis-aligned pixel boundaries; never use a person's midpoint as the seam."""
import math

import cv2
import numpy as np


def translation(rect):
    x, y = rect[:2]
    return np.array([[1., 0., -x], [0., 1., -y], [0., 0., 1.]])


def slice_image(image, rect):
    x1, y1, x2, y2 = rect
    if (any(type(n) is not int for n in rect)
            or not (0 <= x1 < x2 <= image.shape[1] and 0 <= y1 < y2 <= image.shape[0])):
        raise ValueError('invalid_pixel_rectangle')
    return image[y1:y2, x1:x2].copy()


def profile(image, axis):
    """Two-scale color steps across many rows suppress thin grid-line edges."""
    source = image if axis == 0 else image.transpose(1, 0, 2)
    h, w = source.shape[:2]
    source = cv2.resize(source, (w, min(512, h)), interpolation=cv2.INTER_AREA).astype(np.float32)
    radius = max(2, round(w * .002))
    prefix = np.pad(np.cumsum(source, axis=1), ((0, 0), (1, 0), (0, 0)))
    values = []
    for r in (radius, radius*3):
        positions = np.arange(w+1)
        lo, hi = np.maximum(0, positions-r), np.minimum(w, positions+r)
        left = (prefix[:, positions] - prefix[:, lo])/np.maximum(positions-lo, 1)[None, :, None]
        right = (prefix[:, hi] - prefix[:, positions])/np.maximum(hi-positions, 1)[None, :, None]
        values.append(np.linalg.norm(left-right, axis=2)/math.sqrt(3))
    persistent = np.minimum(values[0], values[1])
    blocks = np.array([np.percentile(block, 60, axis=0) for block in np.array_split(persistent, 8, axis=0)])
    scores = np.median(blocks, axis=0)
    scores[:radius*3] = 0
    scores[-radius*3:] = 0
    return scores, blocks


def hard_candidates(image, layout):
    axis = layout['axis']; length = image.shape[1-axis]
    center = np.mean(layout['seam']['band'])*length
    radius = max(8, int(.055*length))
    lo, hi = max(1, int(center-radius)), min(length-1, int(center+radius))
    scores, blocks = profile(image, axis)
    source = image if axis == 0 else image.transpose(1, 0, 2)
    # All candidates have actual image support. Semantic midpoint alone is not evidence.
    support = np.count_nonzero(blocks >= 2.5, axis=0)
    ranked = sorted(range(lo, hi+1), key=lambda x: (-scores[x]*(support[x]/8)**3, abs(x-center)))
    picks = []
    for x in ranked:
        if scores[x] < 3 or support[x] < 6:
            continue
        if any(abs(x-c['cut']) < max(4, .012*length) for c in picks):
            continue
        # A slanted grid line/soft crossfade can look like a step after averaging
        # many rows. Require a sharp edge at this SAME native-pixel column in at
        # least six spatial blocks, independently of the wide-window scores.
        adjacent = np.linalg.norm(source[:, x].astype(float)-source[:, x-1].astype(float), axis=1)/math.sqrt(3)
        sharpness = [float(np.percentile(part, 60)) for part in np.array_split(adjacent, 8)]
        if sum(n >= 3 for n in sharpness) < 6:
            continue
        # Scores are already computed at native pixel boundaries. A second
        # adjacent-pixel maximization would drift onto JPEG ringing/grid edges.
        picks.append({'cut': int(x), 'band': [int(x), int(x)],
                      'score': float(scores[x]), 'supported_blocks': int(np.count_nonzero(blocks[:, x] >= 2.5)),
                      'sharpness_by_block': sharpness, 'sharp_blocks': sum(n >= 3 for n in sharpness),
                      'method': 'two_scale_color_step_with_multiband_support'})
        if len(picks) == 3:
            break
    if not picks:
        raise ValueError('no_reliable_hard_seam_evidence')
    return picks


def rectangles(image, layout, candidate):
    h, w = image.shape[:2]; axis = layout['axis']
    result = []
    for index, panel in enumerate(layout['panels']):
        b = np.asarray(panel['bbox']) * [w, h, w, h]
        rect = [math.ceil(b[0]), math.ceil(b[1]), math.floor(b[2]), math.floor(b[3])]
        # Snap only genuine near-image outer edges; interior coordinates are refined by evidence.
        for k, limit in ((0, w), (1, h), (2, w), (3, h)):
            if k < 2 and b[k] < .003*limit:
                rect[k] = 0
            if k >= 2 and b[k] > .997*limit:
                rect[k] = limit
        rect[axis+2 if index == 0 else axis] = candidate['band'][index]
        if min(rect[2]-rect[0], rect[3]-rect[1]) < 64:
            raise ValueError('child_photo_too_small')
        slice_image(image, rect)
        result.append(rect)
    if result[0][axis+2] > result[1][axis]:
        raise ValueError('child_regions_overlap')
    return result


def check_subjects(rects, subjects, masks, shape, tolerance=.002):
    """Reject new cuts through visible people; an original-image edge is allowed."""
    h, w = shape[:2]
    report = []
    for rect, box, mask in zip(rects, subjects, masks):
        x1, y1, x2, y2 = rect
        if mask.shape != (h, w) or not mask.any():
            raise ValueError('missing_subject_mask')
        outside = 1-float(mask[y1:y2, x1:x2].sum()/mask.sum())
        # Bounding boxes can include background. SAM guards actual visible pixels.
        if outside > tolerance:
            raise ValueError('new_split_cuts_subject')
        report.append({'subject_box_parent_xyxy': list(map(float, box)),
                       'excluded_subject_fraction': outside, 'mask_pixels': int(mask.sum())})
    return report


def overlay(image, rects, candidate, axis):
    out = image.copy(); scale = max(1, round(min(image.shape[:2])/400))
    a, b = candidate['band']
    if b > a:
        region = out[:, a:b] if axis == 0 else out[a:b, :]
        region[:] = (.45*region + .55*np.array([40, 40, 230])).astype(np.uint8)
    else:
        p, q = ((a, 0), (a, image.shape[0]-1)) if axis == 0 else ((0, a), (image.shape[1]-1, a))
        cv2.line(out, p, q, (40, 40, 230), scale*2)
    for i, (x1, y1, x2, y2) in enumerate(rects, 1):
        cv2.rectangle(out, (x1, y1), (x2-1, y2-1), (40, 190, 40), scale)
        cv2.putText(out, str(i), (x1+12*scale, y1+35*scale), cv2.FONT_HERSHEY_SIMPLEX, scale, (40, 190, 40), scale*2)
    return out

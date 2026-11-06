"""Reuse approved camera/scale transforms; fit two rectangles without stretching."""
from itertools import combinations
import numpy as np


def project(points, matrix):
    points = np.c_[np.asarray(points, float), np.ones(len(points))] @ np.asarray(matrix).T
    if np.any(np.abs(points[:, 2]) < 1e-8):
        raise ValueError('cover_transform_crosses_horizon')
    return points[:, :2] / points[:, 2:3]


def measure(meta, inset=3):
    H = np.asarray(meta['H_source_to_normalized'], float)
    if H.shape != (3, 3) or not np.isfinite(H).all() or abs(np.linalg.det(H)) < 1e-10:
        raise ValueError('invalid_cover_source_transform')
    upstream = meta['upstream_report']; frame = upstream['frame']
    # Check the matrix is the approved camera geometry plus uniform scale only.
    N = np.asarray(meta['H_aligned_to_normalized'], float)
    A = np.asarray(frame['H_corrected_to_aligned'], float)
    if not np.allclose(H, N @ np.asarray(frame['H_source_to_aligned']), atol=1e-7):
        raise ValueError('cover_transform_binding_mismatch')
    similarity = N @ A
    if (not np.allclose(similarity[2], [0, 0, 1]) or
            not np.allclose(similarity[:2, :2], np.eye(2)*similarity[0, 0]) or similarity[0, 0] <= 0):
        raise ValueError('cover_requires_uniform_upstream_scale')
    bounds = np.asarray(frame['source_content_bounds_xyxy'], float)
    w, h = upstream['size']
    if not (0 <= bounds[0] < bounds[2] <= w and 0 <= bounds[1] < bounds[3] <= h):
        raise ValueError('invalid_cover_source_content_bounds')
    l, t, r, b = bounds + [inset, inset, -inset-1, -inset-1]
    if r <= l or b <= t:
        raise ValueError('cover_source_too_small')
    corners = np.array([[l, t], [r, t], [r, b], [l, b]])
    z = np.c_[corners, np.ones(4)] @ H[2]
    if not (np.all(z > 0) or np.all(z < 0)):
        raise ValueError('cover_transform_crosses_horizon')
    polygon = project(corners, H)
    kp = np.asarray(meta['keypoints_normalized']); confidence = meta['keypoint_confidence']
    if min(confidence[i] for i in (5, 6, 11, 12)) < .35:
        raise ValueError('cover_shoulders_or_hips_unreliable')
    shoulder = kp[[5, 6]].mean(axis=0); hip = kp[[11, 12]].mean(axis=0)
    torso = hip[1]-shoulder[1]
    if not np.isfinite(torso) or torso < 30:
        raise ValueError('invalid_cover_torso_reference')
    # All evidence is reused, not inferred by a new model. Subject detector boxes
    # can miss occluded heads: conservatively include visible bounds + face points.
    box = upstream['subject_box']
    head_candidates = [meta['visible_bounds_normalized'][1],
                       project([[box[0], box[1]], [box[2], box[1]]], H)[:, 1].min()]
    face = [kp[i, 1] for i in range(5) if confidence[i] >= .5]
    if face:
        head_candidates.append(min(face)-.22*torso)
    # Cannot reconstruct a head beyond the original source. Clamp the estimate
    # to the available source top edge, then test the full rectangle below.
    top = max(polygon[0, 1], polygon[1, 1])
    head = max(min(head_candidates), top)
    desired_top = max(head-.045*torso, top)
    return {'H': H, 'polygon': polygon, 'bounds': bounds, 'torso': float(torso),
            'head_top': float(head), 'desired_top': float(desired_top),
            'source_top': float(top),
            'shoulder': shoulder.tolist(), 'hip': hip.tolist(),
            'visibility_scope': 'original_source_recovered_with_existing_geometry',
            'head_status': meta['visibility']['head']}


def halfplanes(polygon):
    """Convex source footprint as ax+by<=c, irrespective of winding."""
    centre = polygon.mean(axis=0); rows = []
    for p, q in zip(polygon, np.roll(polygon, -1, axis=0)):
        a, b = q[1]-p[1], p[0]-q[0]; c = a*p[0]+b*p[1]
        if a*centre[0]+b*centre[1] > c:
            a, b, c = -a, -b, -c
        norm = np.hypot(a, b)
        rows.append([a/norm, b/norm, c/norm])
    return rows


def constraints_for(measurement, ratio, cap, center_x=0, minimum_top=None, top_limit=None, bottom_limit=None):
    # Rectangle near the approved neutral shoulder x=0. Variables are
    # (top, height). Each polygon constraint uses the worst rectangle corner.
    rows = [[b, abs(a)*ratio/2+max(b, 0), c-a*center_x]
            for a, b, c in halfplanes(measurement['polygon'])]
    rows += [[0, -1, 0], [0, 1, cap], [1, 0, measurement['desired_top'] if top_limit is None else top_limit]]
    if minimum_top is not None:
        rows.append([-1, 0, -minimum_top])
    if bottom_limit is not None:
        rows.append([1, 1, bottom_limit])
    return np.asarray(rows, float)


def largest_height(rows):
    candidates = []
    for first, second in combinations(rows, 2):
        A = np.array([first[:2], second[:2]])
        if abs(np.linalg.det(A)) < 1e-10:
            continue
        point = np.linalg.solve(A, [first[2], second[2]])
        if np.all(rows[:, :2] @ point <= rows[:, 2]+1e-7):
            candidates.append(point)
    if not candidates or max(p[1] for p in candidates) < 60:
        raise ValueError('no_valid_cover_rectangle_preserving_head')
    return max(p[1] for p in candidates)


def interval(rows, height, ratio=None):
    # Accept either polygon halfplanes or top/height inequalities.
    if ratio is not None:
        rows = [[b, abs(a)*ratio/2+max(b, 0), c] for a, b, c in rows]
    lo, hi = -np.inf, np.inf
    for a, b, c in rows:
        remaining = c-b*height
        if abs(a) < 1e-10:
            if remaining < -1e-6:
                raise ValueError('cover_rectangle_outside_source')
        elif a > 0:
            hi = min(hi, remaining/a)
        else:
            lo = max(lo, remaining/a)
    if lo > hi+1e-6:
        raise ValueError('cover_rectangle_has_no_vertical_position')
    return lo, max(lo, hi)


def plan_pair(metadata, target=(500, 478), max_torso_heights=2.8):
    if len(metadata) != 2 or len(target) != 2 or min(target) < 64 or max(target) > 4096:
        raise ValueError('cover_requires_two_photos_and_valid_target')
    if not 1.5 <= max_torso_heights <= 4:
        raise ValueError('invalid_cover_body_extent')
    measured = [measure(m) for m in metadata]
    ratio = target[0]/target[1]
    torso = float(np.median([m['torso'] for m in measured]))
    # Pose hip joints sit above the visible bottom of the pelvis. Leave a
    # quarter torso of room below them so the crop includes the hips, not just
    # the waistband, while avoiding the previous mid-thigh composition.
    bottom_target = max(m['hip'][1] for m in measured)+.25*torso
    preferred = min(m['desired_top'] for m in measured)

    def candidates_for(top, partial):
        # The hips determine the desired bottom. Available image area is only
        # a constraint, not a reason to shrink a person to show extra legs.
        cap = min(max_torso_heights*torso, bottom_target-top)
        candidates = []
        for center_x in np.linspace(-.15*torso, .15*torso, 9):
            rows = [constraints_for(m, ratio, cap, center_x,
                                    top if partial else top-.04*torso,
                                    top+.04*torso if partial else None, bottom_target)
                    for m in measured]
            try:
                candidates.append((largest_height(np.concatenate(rows)), float(center_x), rows))
            except ValueError:
                continue
        return candidates

    partial = any(m['head_status'] not in ('complete', 'touching_border') for m in measured)
    if partial:
        preferred = max(m['source_top'] for m in measured)
    candidates = candidates_for(preferred, partial)
    if not candidates and not partial:
        partial = True
        preferred = max(m['source_top'] for m in measured)
        candidates = candidates_for(preferred, partial)
    if not candidates:
        raise ValueError('no_common_cover_frame_with_locked_shoulders')
    height, center_x, constraints = max(candidates, key=lambda c: (round(c[0], 4), -abs(c[1])))
    centred = next((c for c in candidates if abs(c[1]) < 1e-6), None)
    if centred and height <= centred[0]*1.02:
        height, center_x, constraints = centred
    available = [largest_height(rows) for rows in constraints]
    height -= 1e-4; width = height*ratio
    ranges = [interval(rows, height) for rows in constraints]
    lower = max(r[0] for r in ranges); upper = min(r[1] for r in ranges)
    if lower > upper+1e-6:
        raise ValueError('cover_pair_cannot_use_independent_vertical_offsets')
    top = float(np.clip(preferred, lower, max(lower, upper)))
    actual_bottom = top+height
    hip_target_reached = actual_bottom >= max(m['hip'][1] for m in measured)-.025*torso
    review_reasons = []
    if partial:
        review_reasons.append('partial_head_source_pair_uses_common_shoulder_to_hip_crop')
    if not hip_target_reached:
        review_reasons.append('narrow_source_limits_head_to_hip_in_fixed_isotropic_window')
    scale = target[1]/height
    plans = []
    for m, maximum in zip(measured, available):
        left = center_x-width/2
        # Pixel-centre convention; the frame edges map to [-.5,w-.5].
        T = np.array([[scale, 0, -scale*left-.5], [0, scale, -scale*top-.5], [0, 0, 1]])
        plans.append({'crop_xyxy_normalized': [left, top, left+width, top+height],
                      'output_size': list(target), 'scale': scale, 'scale_x': scale, 'scale_y': scale,
                      'H_normalized_to_cover': T.tolist(), 'H_source_to_cover': (T @ m['H']).tolist(),
                      'source_content_bounds_xyxy': m['bounds'].tolist(),
                      'source_valid_polygon_normalized': m['polygon'].tolist(),
                      'shared_pair_size': [width, height], 'available_height': float(maximum),
                      'horizontal_center_normalized': center_x,
                      'headroom_limit_torsos': .04, 'joint_frame_feasible': True,
                      'shoulder_output': project([m['shoulder']], T)[0].tolist(),
                      'neutral_shoulder_output': project([[0, 0]], T)[0].tolist(),
                      'head_top_normalized': m['head_top'], 'new_head_crop': top > m['head_top']+1e-5,
                      'head_already_incomplete': m['head_status'] not in ('complete', 'touching_border'),
                      'head_evidence_scope': 'reused_evidence_not_new_full_head_certification',
                      'shoulder_alignment_relaxed': False,
                      'review_reasons': list(review_reasons),
                      'framing_policy': 'head_to_hip_locked_pair',
                      'hip_target_reached': bool(hip_target_reached),
                      'hip_output': project([m['hip']], T)[0].tolist(),
                      'bottom_target_normalized': float(bottom_target),
                      'hip_margin_torsos': .25,
                      'partial_head_pair': partial,
                      'body_extent_torsos': (top+height-m['shoulder'][1])/m['torso'],
                      'mode': 'shared_shoulder_to_hip' if partial else 'head_to_hip',
                      'method': 'two_front_sources_approved_geometry_uniform_scale'})
    return plans

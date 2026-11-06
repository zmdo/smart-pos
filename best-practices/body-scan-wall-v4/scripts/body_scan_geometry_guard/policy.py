"""Decide from camera uncertainty and physical wall lines, never body posture."""
from dataclasses import asdict, dataclass

import numpy as np

from scripts.body_scan.geometry import project
from scripts.body_scan.wall_geometry import line_angle, scene_valid
from . import VERSION


@dataclass(frozen=True)
class Policy:
    significant_roll_deg: float = 3.
    significant_pitch_deg: float = 12.
    uncertainty_to_angle: float = .5
    minimum_line_coverage: float = .25
    source_level_deg: float = 1.
    regression_deg: float = 2.
    final_bad_deg: float = 3.
    supported_final_deg: float = 1.5


def quantile(values, weights, fraction=.5):
    order = np.argsort(values)
    values, weights = np.asarray(values)[order], np.asarray(weights)[order]
    return float(values[min(len(values)-1, np.searchsorted(np.cumsum(weights), weights.sum()*fraction))])


def interval_union(intervals):
    total = 0.; right = -float('inf')
    for low, high in sorted(intervals):
        total += max(0., high-max(low, right))
        right = max(right, high)
    return total


def verified_lines(row):
    """Reject hallucinated IDs per family, so a bad vertical ID cannot erase valid horizontals."""
    audit = row.get('refinement', {})
    if not scene_valid(audit.get('scene', {})):
        return {}, ['unreliable_wall_scene']
    selection = audit.get('selection', {})
    confidence = selection.get('confidence')
    if type(confidence) not in (int, float) or not .8 <= confidence <= 1:
        return {}, ['unreliable_wall_selection']
    candidates = audit.get('line_candidates', [])
    result = {}; rejected = []
    width, height = row['size']
    for family in ('horizontal', 'vertical'):
        ids = selection.get(family+'_ids', [])
        index = {c['id']: c for c in candidates if c.get('direction') == family}
        if not isinstance(ids, list) or any(type(i) is not int or i not in index for i in ids):
            rejected.append('invalid_'+family+'_selection')
            continue
        lines = []
        for i in dict.fromkeys(ids):
            segment = np.asarray(index[i].get('segment'), float)
            if (segment.shape != (4,) or not np.isfinite(segment).all()
                    or (segment < 0).any() or (segment > [width, height, width, height]).any()):
                rejected.append('invalid_segment_'+str(i))
                continue
            angle = abs(line_angle(segment))
            if (family == 'horizontal' and angle >= 20) or (family == 'vertical' and angle <= 70):
                rejected.append('direction_mismatch_'+str(i))
                continue
            if np.linalg.norm(segment[2:]-segment[:2]) > 1:
                lines.append(index[i])
        if lines:
            result[family] = lines
    return result, rejected


def family_metrics(lines, family, H, size, policy):
    axis = 0 if family == 'horizontal' else 1
    extent = size[axis]
    before = []; after = []; weights = []; intervals = []; positions = []
    for line in lines:
        points = np.asarray(line['segment']).reshape(2, 2)
        mapped = project(points, H)
        if not np.isfinite(mapped).all():
            raise ValueError('non_finite_wall_projection')
        def error(p):
            angle = line_angle(p.ravel())
            return abs(angle) if family == 'horizontal' else 90-abs(angle)
        before.append(error(points)); after.append(error(mapped))
        weights.append(float(np.linalg.norm(points[1]-points[0])))
        intervals.append(sorted(points[:, axis].tolist()))
        positions.append(float(points[:, 1-axis].mean()))
    b, a, w = np.asarray(before), np.asarray(after), np.asarray(weights)
    coverage = interval_union(intervals)/extent
    regression_share = float(w[(b <= policy.source_level_deg) &
                               (a >= policy.final_bad_deg) &
                               (a-b >= policy.regression_deg)].sum()/w.sum())
    enough = coverage >= policy.minimum_line_coverage
    return {'ids': [c['id'] for c in lines], 'source_errors_deg': before,
            'corrected_errors_deg': after, 'coverage': coverage,
            'source_median_deg': quantile(b, w), 'corrected_median_deg': quantile(a, w),
            'corrected_p90_deg': quantile(a, w, .9), 'regression_share': regression_share,
            'position_spread': (max(positions)-min(positions))/size[1-axis],
            'strong_regression': bool(enough and regression_share >= .75),
            'supports_correction': bool(enough and quantile(a, w, .9) <= policy.supported_final_deg
                                       and quantile(b-a, w) >= .8)}


def decide(row, policy=None):
    policy = policy or Policy()
    result = {'version': VERSION, 'policy': asdict(policy), 'action': 'retain', 'triggered': False}
    if row['status'] != 'rectangular' or row.get('route') != 'non_grid':
        return {**result, 'reason': 'outside_non_grid_scope'}
    geometry = row['geometry']; calibration = geometry.get('calibration', {})
    if not calibration or not geometry.get('correction_applied'):
        return {**result, 'reason': 'no_camera_correction'}
    H = np.asarray(geometry['H_source_to_corrected'], float)
    if H.shape != (3, 3) or not np.isfinite(H).all() or abs(np.linalg.det(H)) < 1e-10:
        raise ValueError('invalid_geometry_matrix')
    uncertain_axes = []
    for axis, minimum in [('roll', policy.significant_roll_deg), ('pitch', policy.significant_pitch_deg)]:
        angle, uncertainty = abs(float(calibration[axis+'_deg'])), float(calibration[axis+'_uncertainty_deg'])
        if not np.isfinite([angle, uncertainty]).all() or uncertainty < 0:
            raise ValueError('invalid_calibration_uncertainty')
        # A warning alone is too broad. This is a screening heuristic, not a probability interval.
        if angle >= minimum and uncertainty >= angle*policy.uncertainty_to_angle:
            uncertain_axes.append(axis)
    lines, rejected = verified_lines(row)
    metrics = {family: family_metrics(values, family, H, row['size'], policy)
               for family, values in lines.items()}
    regressions = [f for f, m in metrics.items() if m['strong_regression']]
    result.update({'uncertain_significant_axes': uncertain_axes, 'wall_metrics': metrics,
                   'rejected_evidence': rejected, 'regressed_families': regressions})
    if regressions:
        return {**result, 'triggered': True, 'action': 'rollback', 'reason': 'verified_wall_regression'}
    if uncertain_axes:
        # Both directions, at separated positions, are needed to validate a large uncertain camera warp.
        supported = (len(metrics) == 2 and all(m['supports_correction'] for m in metrics.values())
                     and all(m['position_spread'] >= .15 for m in metrics.values()))
        if supported:
            return {**result, 'triggered': True, 'reason': 'uncertain_camera_supported_by_wall'}
        return {**result, 'triggered': True, 'action': 'rollback', 'reason': 'uncertain_camera_without_wall_support'}
    return {**result, 'reason': 'no_suspect_transform'}

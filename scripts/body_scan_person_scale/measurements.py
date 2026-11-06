"""Measure confidence-checked segment lengths, never silhouette/waist/head size."""
import numpy as np

from scripts.body_scan.geometry import project
from scripts.body_scan.group_scale import raised_arms

SEGMENTS = {'torso': ((5, 11), (6, 12)), 'thigh': ((11, 13), (12, 14)), 'shin': ((13, 15), (14, 16))}


def measure(row, semantic):
    kp = np.asarray(row['pose']['keypoints_source'], float)
    H = np.asarray(row['geometry']['H_source_to_corrected'])
    points = project(kp[:, :2], H)
    is_side = row['classification'].get('view', '').startswith('side')
    raised = semantic['arms_raised'] or raised_arms(row, {'pose': {'arms_raised': False}})
    neutral = (semantic['neutral_reference'] and not raised and
               row['classification'].get('view') in ('front', 'back') and semantic['confidence'] >= .8)
    lengths = {}; diagnostics = {}
    for name, pairs in SEGMENTS.items():
        candidates = []
        enabled = semantic[name+'_usable'] and semantic['confidence'] >= .8
        if name == 'torso' and raised:
            enabled = False
        for a, b in pairs:
            delta = points[b]-points[a]
            confidence = float(min(kp[a, 2], kp[b, 2]))
            if enabled and confidence >= .8 and delta[1] > 5 and abs(delta[0]) < .5*delta[1]:
                candidates.append({'pair': [a, b], 'confidence': confidence,
                                   'length': float(np.linalg.norm(delta))})
        diagnostics[name] = candidates
        if not candidates:
            continue
        if is_side:
            # Do not average a confidently visible leg with a foreshortened far-side leg.
            selected = max(candidates, key=lambda p: p['confidence'])
            lengths[name] = selected['length']
        elif len(candidates) == 2 and max(c['length'] for c in candidates)/min(c['length'] for c in candidates) <= 1.12:
            lengths[name] = float(np.mean([c['length'] for c in candidates]))
        # A frontal reference with only one questionable side is not a ruler.
    # Covered knees must not disqualify a clearly visible relaxed shoulder/hip reference.
    # Consensus across at least two neutral photos is enforced by the group solver.
    if 'torso' not in lengths:
        neutral = False
    return {'neutral': bool(neutral), 'raised_arms': bool(raised), 'lengths': lengths,
            'segments': diagnostics, 'source_points_unchanged': True}

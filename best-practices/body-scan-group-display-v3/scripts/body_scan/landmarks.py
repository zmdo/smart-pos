"""Shoulder/hip measurements; preserve actual body tilt."""
import unicodedata
import numpy as np
from .geometry import project

class AlignmentUnavailable(ValueError):
    pass


def member_key(asset):
    values = [unicodedata.normalize('NFKC', str(asset.get(k) or '')).strip() for k in ('store', 'member')]
    if not all(values):
        raise AlignmentUnavailable('missing_store_or_member')
    return tuple(values)


def landmarks(keypoints, H, box, view, threshold=.60):
    """COCO joints 5/6 shoulders, 11/12 hips. Side views use the best visible pair.

    Scale uses shoulder-to-hip distance, never projected shoulder width. The
    latter naturally collapses in profile and would incorrectly enlarge it.
    """
    kp = np.asarray(keypoints, float)
    if kp.shape != (17, 3) or not np.isfinite(kp).all():
        raise AlignmentUnavailable('invalid_pose_keypoints')
    box = np.asarray(box, float)
    points = project(kp[:, :2], H)
    mapped_box = project([[box[0], box[1]], [box[2], box[1]],
                          [box[2], box[3]], [box[0], box[3]]], H)
    body_height = np.ptp(mapped_box[:, 1])
    pairs = []
    for shoulder, hip in ((5, 11), (6, 12)):
        confidence = min(kp[shoulder, 2], kp[hip, 2])
        delta = points[hip]-points[shoulder]
        length = float(np.linalg.norm(delta))
        if confidence < threshold or not .15*body_height < delta[1] < .7*body_height:
            continue
        if abs(delta[0]) > .65*delta[1]:
            continue
        margin = (box[2:]-box[:2])*.12
        xy = kp[[shoulder, hip], :2]
        if (xy < box[:2]-margin).any() or (xy > box[2:]+margin).any():
            continue
        pairs.append({'indices': [shoulder, hip], 'confidence': float(confidence), 'length': length})
    is_side = str(view).startswith('side')
    if not pairs or (not is_side and len(pairs) != 2):
        raise AlignmentUnavailable('shoulder_or_hip_confidence_insufficient')
    if is_side:
        pairs = [max(pairs, key=lambda p: p['confidence'])]
    elif max(p['length'] for p in pairs)/min(p['length'] for p in pairs) > 1.35:
        raise AlignmentUnavailable('bilateral_torso_lengths_disagree')
    shoulders = [points[p['indices'][0]] for p in pairs]
    hips = [points[p['indices'][1]] for p in pairs]
    return {'anchor': np.mean(shoulders, axis=0).tolist(),
            'hip_anchor': np.mean(hips, axis=0).tolist(),
            'torso_length': float(np.mean([p['length'] for p in pairs])),
            'confidence': float(np.mean([p['confidence'] for p in pairs])),
            'selected_pairs': [p['indices'] for p in pairs],
            'mode': 'visible_side_pair' if is_side else 'bilateral_midpoint',
            'keypoints_source': kp.tolist(), 'keypoints_corrected': points.tolist()}


def compatible(a, b):
    length = min(a['torso_length'], b['torso_length'])
    return (abs(a['torso_length']-b['torso_length'])/length <= .12 and
            np.linalg.norm(np.asarray(a['anchor'])-b['anchor'])/length <= .10)

"""Shoulder anchors and shared group framing; no head or hair scale reference."""
from dataclasses import dataclass
import unicodedata

import numpy as np

from grid_crop import project


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


@dataclass(frozen=True)
class GroupConfig:
    width: int = 768
    height: int = 1280
    shoulder_y: float | None = None
    torso_fraction: float = .36
    max_torso_fraction: float = .75

    def __post_init__(self):
        if not (64 <= self.width <= 4096 and 64 <= self.height <= 4096):
            raise AlignmentUnavailable('invalid_output_size')
        if not .5 <= self.width/self.height <= 1.:
            raise AlignmentUnavailable('invalid_portrait_aspect')
        if self.shoulder_y is not None and not .05 <= self.shoulder_y <= .5:
            raise AlignmentUnavailable('invalid_shoulder_target')
        if not .2 <= self.torso_fraction <= self.max_torso_fraction <= .85:
            raise AlignmentUnavailable('invalid_torso_target')


def group_plan(items, config):
    """One target torso length and shoulder point for ALL accepted group images.

    Solve common valid framing before rendering; never clamp each image's anchor
    independently afterwards, which would undo the alignment. No rotation is
    introduced: real shoulder tilt and the corrected grid stay unchanged.
    """
    if not items:
        raise AlignmentUnavailable('empty_group')
    supports = []
    for item in items:
        x, y = np.asarray(item['pose']['anchor'])+.5  # pixel edge coordinates
        length = item['pose']['torso_length']
        x1, y1, x2, y2 = np.asarray(item['bounds'], float)+[2, 2, -2, -2]
        support = np.array([x-x1, x2-x, y-y1, y2-y])/length
        if not np.isfinite(support).all() or (support <= 0).any() or length <= 0:
            raise AlignmentUnavailable('shoulder_outside_valid_grid_frame')
        supports.append(support)
    left, right, above, below = np.min(supports, axis=0)
    target = max(config.height*config.torso_fraction,
                 config.width/(2*left), config.width/(2*right),
                 config.height/(above+below)) * (1+1e-7)
    if target > config.height*config.max_torso_fraction:
        raise AlignmentUnavailable('shared_frame_requires_excessive_group_zoom')
    lo, hi = max(0., config.height-target*below), min(float(config.height), target*above)
    if lo > hi+1e-6:
        raise AlignmentUnavailable('no_common_shoulder_height')
    # Default composition retains as much of the existing upper image as the
    # entire group permits, up to the midline. This uses grid bounds, not head
    # landmarks, hair height, or facial stickers as a calibration reference.
    preferred_y = min(hi, config.height*.5) if config.shoulder_y is None else config.height*config.shoulder_y
    tx, ty = config.width/2, float(np.clip(preferred_y, lo, hi))
    plans = {}
    for item in items:
        sx, sy = item['pose']['anchor']
        scale = target/item['pose']['torso_length']
        left = sx+.5-tx/scale
        top = sy+.5-ty/scale
        A = np.array([[scale, 0., tx-.5-scale*sx],
                      [0., scale, ty-.5-scale*sy], [0., 0., 1.]])
        plans[item['asset_id']] = {'bounds_xyxy': [left, top, left+config.width/scale, top+config.height/scale],
                                  'uniform_scale': float(scale), 'H_corrected_to_aligned': A.tolist()}
    notices = []
    if target > config.height*config.torso_fraction*1.05:
        notices.append('shared_zoom_increased_to_avoid_blank_pixels')
    if config.shoulder_y is not None and abs(ty/config.height-config.shoulder_y) > .02:
        notices.append('group_shoulder_height_adjusted_to_available_pixels')
    return {'output_size': [config.width, config.height], 'torso_target_pixels': float(target),
            'mode': 'shared_shoulders_and_torso',
            'shoulder_target_xy': [tx-.5, ty-.5], 'image_count': len(items),
            'singleton': len(items) == 1, 'warnings': notices, 'plans': plans}

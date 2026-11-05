"""Common shoulder-relative framing, with a bounded vertical display stretch."""
import math
from collections import Counter
from dataclasses import dataclass

import numpy as np

from .visibility import profile_name

PROFILES = {
    'full_body': {'label': '全身', 'height': 1920, 'shoulder_y': .23},
    'feet_cropped': {'label': '脚部贴边或不完整', 'height': 1792, 'shoulder_y': .23},
    'head_cropped': {'label': '头部贴边或不完整、腿脚完整', 'height': 1664, 'shoulder_y': .08},
    'head_feet_cropped': {'label': '头脚贴边或不完整、腿部可见', 'height': 1536, 'shoulder_y': .08},
    'legs_cropped': {'label': '下肢不完整', 'height': 1408, 'shoulder_y': .28},
    'head_legs_cropped': {'label': '头部贴边或不完整、下肢不完整', 'height': 1184, 'shoulder_y': .12},
    'upper_body': {'label': '上半身', 'height': 1152, 'shoulder_y': .32},
    'torso': {'label': '头部贴边或不完整、仅至大腿/髋', 'height': 1024, 'shoulder_y': .12},
}


@dataclass(frozen=True)
class Config:
    width: int = 768
    max_stretch: float = 1.10
    max_crop_loss: float = .25
    crop_step: float = .02
    max_steps: int = 80
    adaptive_group_ratio: bool = True

    def __post_init__(self):
        if not 256 <= self.width <= 2048:
            raise ValueError('invalid_output_width')
        if not 1 <= self.max_stretch <= 1.15:
            raise ValueError('invalid_display_stretch_limit')
        if not 0 <= self.max_crop_loss <= .6 or not 0 < self.crop_step <= .05 or not 1 <= self.max_steps <= 150:
            raise ValueError('invalid_crop_limits')


class PlanUnavailable(ValueError):
    def __init__(self, reason, detail):
        super().__init__(reason)
        self.detail = detail


def contains(outer, inner, tolerance=1e-6):
    return all(a <= b+tolerance for a, b in zip(outer[:2], inner[:2])) and all(
        a+tolerance >= b for a, b in zip(outer[2:], inner[2:]))


def intersection(rectangles):
    a = np.asarray(rectangles, float)
    if a.ndim != 2 or a.shape[1] != 4 or not np.isfinite(a).all() or (a[:, 2:] <= a[:, :2]).any():
        raise ValueError('invalid_group_rectangles')
    result = np.r_[a[:, :2].max(axis=0), a[:, 2:].min(axis=0)]
    if (result[2:] <= result[:2]).any():
        raise ValueError('no_common_shoulder_rectangle')
    return result


def locate_interval(low, high, size, required_low, required_high, anchor_fraction):
    first = max(low, required_high-size)
    last = min(high-size, required_low)
    if first > last+1e-6:
        raise ValueError('target_aspect_would_cut_required_body')
    return float(np.clip(-size*anchor_fraction, first, max(first, last)))


def crop_steps(common, final, config):
    current = np.asarray(common, float)
    target = np.asarray(final, float)
    steps = []
    for _ in range(config.max_steps):
        size = current[2:]-current[:2]
        new_size = np.maximum(target[2:]-target[:2], size*(1-config.crop_step))
        removed = size-new_size
        eventual = (target[:2]-current[:2])+(current[2:]-target[2:])
        left = np.divide(target[:2]-current[:2], eventual, out=np.zeros(2), where=eventual > 1e-8)*removed
        following = np.r_[current[:2]+left, current[2:]-(removed-left)]
        if np.allclose(following, target, atol=1e-6):
            if not np.allclose(current, target, atol=1e-6):
                steps.append(target.tolist())
            return steps
        steps.append(following.tolist()); current = following
    raise ValueError('crop_iteration_limit')


def plan_group(items, profile, config=None, profiles=None, output_height=None):
    config = config or Config(); profiles = profiles or PROFILES
    if profile not in profiles or not items:
        raise ValueError('unknown_or_empty_profile')
    state = profiles[profile]
    if not isinstance(state['label'], str) or not 0 <= state['shoulder_y'] <= .5 or not math.isfinite(state['height']):
        raise ValueError('invalid_profile_configuration')
    width = config.width
    height = round(state['height']*width/768) if output_height is None else output_height
    if not 256 <= height <= 6144 or not .5 <= height/width <= 4:
        raise ValueError('invalid_profile_dimensions')
    common = intersection([r['normalized_bounds'] for r in items])
    required = np.asarray([r['required_core'] for r in items])
    required = np.r_[required[:, :2].min(axis=0), required[:, 2:].max(axis=0)]
    required[:2] = np.minimum(required[:2], [-.5, -.5])
    required[2:] = np.maximum(required[2:], [.5, .5])
    # Retain the visible vertical body span that fits inside the common frame.
    # A single sticker touching the top must not make a short-frame preference
    # crop every other head; mixed full/partial photos already share the minimum
    # available extent before this extra aspect-ratio adjustment.
    bodies = np.asarray([r['visible_bounds_normalized'] for r in items])
    required[1] = min(required[1], max(common[1], bodies[:, 1].min()))
    required[3] = max(required[3], min(common[3], bodies[:, 3].max()))
    # A mixed full/partial group shares its available body extent. Never create
    # a second frame to retain a body part absent from other photos of the person.
    protect_head = all(r['visibility']['head'] == 'complete' for r in items)
    protect_feet = all(r['visibility']['lower_extent'] == 'feet_complete' for r in items)
    for item in items:
        body = item['visible_bounds_normalized']
        if protect_head:
            required[1] = min(required[1], body[1])
        if protect_feet:
            required[3] = max(required[3], body[3])
    detail = {'profile': profile, 'common_rectangle': common.tolist(), 'required_rectangle': required.tolist(),
              'member_ids': [r['asset_id'] for r in items],
              'protected_parts': {'shoulders_hips': True, 'head': protect_head, 'feet': protect_feet,
                                  'shared_visible_vertical_extent': True}}
    if not contains(common, required):
        raise PlanUnavailable('common_frame_would_cut_confirmed_head_feet_or_torso', detail)
    w0, h0 = common[2:]-common[:2]
    ratio = height/width
    current_ratio = h0/w0
    w, h = float(w0), float(h0)
    if current_ratio < ratio/config.max_stretch:
        w = h*config.max_stretch/ratio
    elif current_ratio > ratio:
        h = w*ratio
    loss = 1-w*h/(w0*h0)
    detail['additional_crop_fraction'] = float(loss)
    if loss > config.max_crop_loss+1e-9:
        raise PlanUnavailable('target_ratio_requires_excessive_group_crop', detail)
    try:
        x = locate_interval(common[0], common[2], w, required[0], required[2], .5)
        y = locate_interval(common[1], common[3], h, required[1], required[3], state['shoulder_y'])
        crop = [x, y, x+w, y+h]
        steps = crop_steps(common, crop, config)
    except ValueError as error:
        raise PlanUnavailable(str(error), detail) from None
    sx, sy = width/w, height/h
    stretch = sy/sx
    if not 1-1e-9 <= stretch <= config.max_stretch+1e-9:
        raise PlanUnavailable('display_stretch_outside_limits', detail)
    display = np.array([[sx, 0., -sx*x-.5], [0., sy, -sy*y-.5], [0., 0., 1.]])
    # Isotropic reference uses exactly the same crop, with letterboxing only.
    uniform_scale = min(sx, sy)
    offset = np.array([(width-uniform_scale*w)/2, (height-uniform_scale*h)/2])
    uniform = np.array([[uniform_scale, 0., -uniform_scale*x+offset[0]-.5],
                        [0., uniform_scale, -uniform_scale*y+offset[1]-.5], [0., 0., 1.]])
    return {**detail, 'label': state['label'], 'output_size': [width, height], 'crop_rectangle': crop,
            'crop_steps': steps, 'crop_step_limit': config.crop_step,
            'scale_x': sx, 'scale_y': sy, 'vertical_stretch': stretch,
            'stretch_limit': config.max_stretch, 'shoulder_target': display[:2, 2].tolist(),
            'H_normalized_to_display': display.tolist(), 'H_normalized_to_uniform': uniform.tolist(),
            'uniform_content_edges': [float(offset[0]-.5), float(offset[1]-.5),
                                      float(offset[0]+uniform_scale*w-.5), float(offset[1]+uniform_scale*h-.5)],
            'presentation_only': True,
            'note': 'One person uses one common crop, output size and bounded aspect change; presentation only.'}


def plan_person(items, config=None, profiles=None):
    """Choose ONE preferred frame from collective visibility, then fit the whole person group."""
    config = config or Config(); profiles = profiles or PROFILES
    if not items:
        raise ValueError('empty_person_group')
    lower_order = {'feet_complete': 0, 'feet_cut': 1, 'feet_touching_border': 1,
                   'calves_cut': 2, 'knees_cut': 3, 'thighs_cut': 4, 'hips_cut': 5}
    lower = max((r['visibility']['lower_extent'] for r in items), key=lambda name: (lower_order[name], name))
    all_heads = all(r['visibility']['head'] == 'complete' for r in items)
    profile = profile_name({'head': 'complete' if all_heads else 'cut', 'lower_extent': lower})
    preferred_height = round(profiles[profile]['height']*config.width/768)
    selection = {'group_policy': 'one_frame_per_store_member',
                 'input_coverage_counts': dict(sorted(Counter(profile_name(r['visibility']) for r in items).items())),
                 'group_head_complete_in_all_photos': all_heads, 'group_lower_extent': lower,
                 'preferred_output_size': [config.width, preferred_height], 'ratio_adjusted': False}
    try:
        plan = plan_group(items, profile, config, profiles)
    except PlanUnavailable as error:
        adaptable = ('target_ratio_requires_excessive_group_crop',
                     'target_aspect_would_cut_required_body', 'crop_iteration_limit')
        if not config.adaptive_group_ratio or str(error) not in adaptable:
            raise
        common = np.asarray(error.detail['common_rectangle'])
        required = np.asarray(error.detail['required_rectangle'])
        w, h = common[2:]-common[:2]; rw, rh = required[2:]-required[:2]
        # Only one dimension is cropped. This interval enforces both area loss
        # and the number of small crop steps without relaxing either threshold.
        loss = min(config.max_crop_loss, 1-(1-config.crop_step)**config.max_steps)
        low_ratio = max(.5, rh/w, (1-loss)*h/w)
        high_ratio = min(4., config.max_stretch*h/max(rw, (1-loss)*w))
        low = max(256, math.ceil(config.width*low_ratio-1e-7))
        high = min(6144, math.floor(config.width*high_ratio+1e-7))
        if low > high:
            raise PlanUnavailable('no_single_group_ratio_satisfies_constraints', error.detail) from None
        height = max(low, min(preferred_height, high))
        plan = plan_group(items, profile, config, profiles, output_height=height)
        selection.update({'ratio_adjusted': height != preferred_height, 'ratio_adjustment_reason': str(error),
                          'feasible_height_range': [low, high]})
    plan.update(selection)
    crop = plan['crop_rectangle']
    plan['originally_complete_parts_cropped'] = [
        {'asset_id': r['asset_id'],
         'head': r['visibility']['head'] == 'complete' and crop[1] > r['visible_bounds_normalized'][1]+1e-6,
         'feet': r['visibility']['lower_extent'] == 'feet_complete' and crop[3] < r['visible_bounds_normalized'][3]-1e-6}
        for r in items]
    return plan

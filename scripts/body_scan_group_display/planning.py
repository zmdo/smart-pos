"""Common shoulder-relative framing, with a bounded vertical display stretch."""
import math
from dataclasses import dataclass

import numpy as np

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


def plan_group(items, profile, config=None, profiles=None):
    config = config or Config(); profiles = profiles or PROFILES
    if profile not in profiles or not items:
        raise ValueError('unknown_or_empty_profile')
    state = profiles[profile]
    if not isinstance(state['label'], str) or not 0 <= state['shoulder_y'] <= .5 or not math.isfinite(state['height']):
        raise ValueError('invalid_profile_configuration')
    width = config.width; height = round(state['height']*width/768)
    if not 256 <= height <= 6144 or not .5 <= height/width <= 4:
        raise ValueError('invalid_profile_dimensions')
    common = intersection([r['normalized_bounds'] for r in items])
    required = np.asarray([r['required_core'] for r in items])
    required = np.r_[required[:, :2].min(axis=0), required[:, 2:].max(axis=0)]
    required[:2] = np.minimum(required[:2], [-.5, -.5])
    required[2:] = np.maximum(required[2:], [.5, .5])
    # Preserve complete head/feet whenever they were actually confirmed visible.
    for item in items:
        body = item['visible_bounds_normalized']; value = item['visibility']
        if value['head'] == 'complete':
            required[1] = min(required[1], body[1])
        if value['lower_extent'] == 'feet_complete':
            required[3] = max(required[3], body[3])
    detail = {'profile': profile, 'common_rectangle': common.tolist(), 'required_rectangle': required.tolist(),
              'member_ids': [r['asset_id'] for r in items]}
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
            'note': 'Display applies the same bounded vertical aspect change to the whole cohort; not a measurement image.'}

"""Shared uniform framing and maximum real-photo rectangle."""
from dataclasses import dataclass
import cv2
import numpy as np
from .geometry import project, content_mask
from .landmarks import AlignmentUnavailable

@dataclass(frozen=True)
class UniformConfig:
    width: int = 768
    height: int = 1792
    torso_fraction: float = .27
    shoulder_y: float = .23
    background_rgb: tuple = (238, 234, 227)

    def __post_init__(self):
        if not (64 <= self.width <= 4096 and 64 <= self.height <= 4096):
            raise AlignmentUnavailable('invalid_output_size')
        if not .3 <= self.width/self.height <= 1.:
            raise AlignmentUnavailable('invalid_portrait_aspect')
        if not .15 <= self.torso_fraction <= .45:
            raise AlignmentUnavailable('invalid_torso_fraction')
        if not .1 <= self.shoulder_y <= .4 or self.shoulder_y+self.torso_fraction >= .9:
            raise AlignmentUnavailable('invalid_shoulder_target')
        if len(self.background_rgb) != 3 or any(not isinstance(c, int) or not 0 <= c <= 255 for c in self.background_rgb):
            raise AlignmentUnavailable('invalid_background_color')


def uniform_plan(pose, config):
    """The same torso/frame ratio and shoulder location for every image."""
    anchor = np.asarray(pose['anchor'], float)
    length = float(pose['torso_length'])
    if anchor.shape != (2,) or not np.isfinite(anchor).all() or not np.isfinite(length) or length <= 0:
        raise AlignmentUnavailable('invalid_saved_pose')
    torso = config.height*config.torso_fraction
    scale = torso/length
    target = np.array([config.width/2-.5, config.height*config.shoulder_y-.5])
    A = np.array([[scale, 0., target[0]-scale*anchor[0]],
                  [0., scale, target[1]-scale*anchor[1]], [0., 0., 1.]])
    top_left = anchor+.5-np.array([config.width/2, config.height*config.shoulder_y])/scale
    return {'bounds_xyxy': [*top_left, *(top_left+np.array([config.width, config.height])/scale)],
            'uniform_scale': float(scale), 'H_corrected_to_aligned': A.tolist(),
            'shoulder_target_xy': target.tolist(), 'torso_target_pixels': float(torso),
            'torso_fraction': config.torso_fraction}


def compose_full_source(source, H, config):
    """One resampling pass, using the entire source footprint, not an inset box.

    Extend boundary samples for cubic interpolation only. The separately warped
    mask always prevents those extrapolated pixels from filling missing areas.
    Original black letterbox bands are excluded, interior dark clothing is not.
    """
    source_mask, bounds = content_mask(source)
    x1, y1, x2, y2 = bounds
    crop = source[y1:y2, x1:x2]
    if crop.size == 0:
        raise AlignmentUnavailable('empty_original_content')
    sampling_source = cv2.copyMakeBorder(crop, y1, source.shape[0]-y2, x1, source.shape[1]-x2,
                                         cv2.BORDER_REPLICATE)
    size = (config.width, config.height)
    used = cv2.warpPerspective(source_mask, H, size, flags=cv2.INTER_NEAREST,
                               borderMode=cv2.BORDER_CONSTANT, borderValue=0)
    if not used.any():
        raise AlignmentUnavailable('source_outside_frame')
    sampled = cv2.warpPerspective(sampling_source, H, size, flags=cv2.INTER_CUBIC,
                                  borderMode=cv2.BORDER_REPLICATE)
    image = np.empty_like(sampled); image[:] = config.background_rgb[::-1]
    image[used > 0] = sampled[used > 0]
    original_footprint = cv2.warpPerspective(np.full(source.shape[:2], 255, np.uint8), H, size,
                                             flags=cv2.INTER_NEAREST)
    return image, used, {'source_content_bounds_xyxy': bounds,
                        'missing_outside_original_pixels': int(np.count_nonzero(original_footprint == 0)),
                        'missing_original_black_band_pixels': int(np.count_nonzero((original_footprint > 0) & (used == 0)))}


def contains(outer, inner):
    return outer[0] <= inner[0] and outer[1] <= inner[1] and outer[2] >= inner[2] and outer[3] >= inner[3]


def largest_valid_rectangle(mask, required=None):
    """Exact largest all-valid pixel rectangle via O(height*width) histograms.

    Optional required bounds must be wholly contained. Maximal histogram spans
    dominate their subrectangles, including under this containment constraint.
    Equal-area solutions prefer more height, then more lower content, then left.
    """
    valid = np.asarray(mask) > 0
    if valid.ndim != 2 or not valid.size:
        raise AlignmentUnavailable('invalid_available_mask')
    height, width = valid.shape
    if required is not None:
        if (len(required) != 4 or any(int(n) != n for n in required) or
                not (0 <= required[0] < required[2] <= width and 0 <= required[1] < required[3] <= height)):
            raise AlignmentUnavailable('invalid_required_rectangle')
        x1, y1, x2, y2 = map(int, required)
        if not valid[y1:y2, x1:x2].all():
            raise AlignmentUnavailable('required_rectangle_not_available')
    heights = np.zeros(width+1, np.int32)
    best, best_key = None, None
    for y in range(height):
        heights[:width] = np.where(valid[y], heights[:width]+1, 0)
        stack = []
        for x in range(width+1):
            current = int(heights[x]); start = x
            while stack and stack[-1][1] > current:
                left, h = stack.pop(); start = left
                rect = [left, y+1-h, x, y+1]
                if required is not None and not contains(rect, required):
                    continue
                key = ((x-left)*h, h, y+1, -left)
                if best_key is None or key > best_key:
                    best, best_key = rect, key
            if current and (not stack or stack[-1][1] < current):
                stack.append((start, current))
    if best is None:
        raise AlignmentUnavailable('no_valid_rectangle')
    return best, int(best_key[0])


def select_rectangle(available, required):
    unconstrained, global_area = largest_valid_rectangle(available)
    if contains(unconstrained, required):
        rect, selected_area = unconstrained, global_area
    else:
        rect, selected_area = largest_valid_rectangle(available, required)
    return rect, {'selected_rectangle_area': selected_area, 'unconstrained_maximum_area': global_area,
                  'is_unconstrained_global_maximum': selected_area == global_area,
                  'required_subject_bounds_xyxy': list(required)}


def rectangular_image(image, available, rect, background_rgb):
    x1, y1, x2, y2 = rect
    if (image.shape[:2] != available.shape or not (0 <= x1 < x2 <= image.shape[1] and 0 <= y1 < y2 <= image.shape[0]) or
            not (available[y1:y2, x1:x2] > 0).all()):
        raise AlignmentUnavailable('rectangle_contains_unavailable_pixels')
    output = np.empty_like(image); output[:] = background_rgb[::-1]
    output[y1:y2, x1:x2] = image[y1:y2, x1:x2]
    used = np.zeros(available.shape, np.uint8); used[y1:y2, x1:x2] = 255
    return output, used


def required_subject_rectangle(pose, A, config):
    selected = sorted({j for pair in pose['selected_pairs'] for j in pair})
    points = project(np.asarray(pose['keypoints_corrected'])[selected], A)
    bounds = [*np.floor(points.min(axis=0)).astype(int), *(np.ceil(points.max(axis=0)).astype(int)+1)]
    if not contains([0, 0, config.width, config.height], bounds):
        raise AlignmentUnavailable('shoulders_or_hips_outside_frame')
    return [int(n) for n in bounds]

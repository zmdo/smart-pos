"""Do not newly crop a head/foot previously verified as complete."""
import numpy as np

from scripts.body_scan.geometry import project


def check(previous, old_frame, new_frame, measured_bounds=None):
    visibility = previous['visibility']
    x1, y1, x2, y2 = old_frame['content_rectangle_xyxy']
    box = np.asarray(visibility['visible_bbox'])*[x2-x1, y2-y1, x2-x1, y2-y1]+[x1, y1, x1, y1]
    if measured_bounds is not None:
        box = np.asarray(measured_bounds, float)
    old_to_new = np.asarray(new_frame['H_source_to_aligned']) @ np.linalg.inv(np.asarray(old_frame['H_source_to_aligned']))
    corners = project([[box[0], box[1]], [box[2], box[1]], [box[2], box[3]], [box[0], box[3]]], old_to_new)
    rect = new_frame['content_rectangle_xyxy']
    old_to_display = np.asarray(previous['output']['H_aligned_to_display'])
    old_visible = project([[box[0], box[1]], [box[2], box[3]]], old_to_display)
    old_height = previous['group_plan']['output_size'][1]
    # Only protect extents that the old final product actually retained.
    protect_head = visibility['head'] == 'complete' and old_visible[:, 1].min() >= -.5
    protect_feet = visibility['lower_extent'] == 'feet_complete' and old_visible[:, 1].max() <= old_height-.5
    # A 2-pixel remnant is not reliable headroom: masks and cubic sampling have
    # finite precision. Keep up to 1% breathing room, capped by the old margin.
    head_margin = min(max(0., box[1]-y1), .01*(rect[3]-rect[1]))
    foot_margin = min(max(0., y2-1-box[3]), .01*(rect[3]-rect[1]))
    result = {'protect_head': bool(protect_head), 'protect_feet': bool(protect_feet),
              'mapped_top': float(corners[:, 1].min()), 'mapped_bottom': float(corners[:, 1].max()),
              'candidate_content_top_bottom': [rect[1], rect[3]],
              'minimum_head_margin': float(head_margin), 'minimum_foot_margin': float(foot_margin), 'reason': None}
    if protect_head and corners[:, 1].min() < rect[1]+head_margin-.5:
        result['reason'] = 'would_crop_previously_complete_head'
    elif protect_feet and corners[:, 1].max() > rect[3]-.5-foot_margin:
        result['reason'] = 'would_crop_previously_complete_feet'
    return result


def measure_bounds(mask, rect):
    # Require several foreground pixels on an occupied row, ignoring isolated specks.
    occupied = np.flatnonzero(mask.sum(axis=1) >= max(3, int(mask.shape[1]*.01)))
    if not len(occupied):
        raise ValueError('boundary_mask_has_no_supported_rows')
    ys, xs = np.nonzero(mask)
    return [float(xs.min()+rect[0]), float(occupied[0]+rect[1]),
            float(xs.max()+rect[0]), float(occupied[-1]+rect[1])]

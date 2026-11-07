"""A fixed-ratio rectangle inside the source, with no masking or padding."""
import math

from PIL import Image


def box_pixels(value, size):
    if (not isinstance(value, list) or len(value) != 4
            or not all(isinstance(v, (int, float)) and not isinstance(v, bool)
                       and math.isfinite(v) and 0 <= v <= 1000 for v in value)):
        raise ValueError('invalid_normalized_box')
    x1, y1, x2, y2 = value
    if x2 - x1 < 30 or y2 - y1 < 30:
        raise ValueError('region_too_small')
    w, h = size
    return [math.floor(x1*w/1000), math.floor(y1*h/1000),
            math.ceil(x2*w/1000), math.ceil(y2*h/1000)]


def padded(box, size, margin):
    x1, y1, x2, y2 = box
    w, h = size
    return [max(0, x1-margin), max(0, y1-margin), min(w, x2+margin), min(h, y2+margin)]


def parse_ratio(text):
    try:
        rw, rh = [int(part) for part in text.split(':')]
    except (ValueError, AttributeError):
        raise ValueError('ratio_must_be_positive_integers_like_3:4') from None
    if not 1 <= rw <= 100 or not 1 <= rh <= 100:
        raise ValueError('invalid_ratio')
    divisor = math.gcd(rw, rh)
    return rw//divisor, rh//divisor


def rectangle_in_source(size, content, preferred, ratio, anchor_y='center', anchor_x='center'):
    """Contain the preferred box when possible, otherwise maximize content coverage."""
    w, h = size
    rw, rh = ratio
    max_units = min(w//rw, h//rh)
    if max_units < 1:
        raise ValueError('source_too_small_for_ratio')
    preferred_units = math.ceil(max((preferred[2]-preferred[0])/rw,
                                    (preferred[3]-preferred[1])/rh))
    core_units = math.ceil(max((content[2]-content[0])/rw, (content[3]-content[1])/rh))
    units = min(preferred_units, max_units)
    cw, ch = rw*units, rh*units
    target = preferred if preferred_units <= max_units else content

    def origin(lo, hi, length, available, anchor='center'):
        desired = (lo if anchor in ('top', 'start') else hi-length if anchor == 'bottom'
                   else round((lo+hi-length)/2))
        if hi-lo <= length:
            lower, upper = max(0, hi-length), min(lo, available-length)
        else:
            lower, upper = max(0, lo), min(hi-length, available-length)
        return max(lower, min(desired, upper))

    x = origin(target[0], target[2], cw, w, anchor_x)
    y = origin(target[1], target[3], ch, h, anchor_y)
    return [x, y, x+cw, y+ch], core_units <= max_units


def make_frame(original, selection, ratio=(3, 4), max_side=None, priority=None):
    if selection.get('is_report') is not True:
        raise ValueError('not_a_report')
    medium = selection.get('medium')
    if medium not in ('screenshot', 'paper_photo'):
        raise ValueError('unknown_report_medium')
    rw, rh = parse_ratio(':'.join(map(str, ratio)))
    if max_side is not None and max_side < max(64, rw, rh):
        raise ValueError('invalid_max_side')
    content = box_pixels(selection.get('content_box'), original.size)
    margin = max(4, round(min(original.size)*(.03 if medium == 'screenshot' else .006)))
    preferred = content
    if medium == 'paper_photo':
        paper = box_pixels(selection.get('paper_box'), original.size)
        preferred = [min(paper[0], content[0]), min(paper[1], content[1]),
                     max(paper[2], content[2]), max(paper[3], content[3])]
    preferred = padded(preferred, original.size, margin)
    anchor_y = 'top' if medium == 'screenshot' else 'center'
    box, contained = rectangle_in_source(original.size, content, preferred, (rw, rh), anchor_y)
    priority_box = content
    priority_used = not contained and priority is not None
    if priority_used:
        priority_box = box_pixels(priority.get('primary_box'), original.size)
        # Keep the largest available window, positioned around the important data.
        box, _ = rectangle_in_source(original.size, priority_box, preferred, (rw, rh),
                                      'bottom' if medium == 'screenshot' else 'center',
                                      'start' if medium == 'screenshot' else 'center')
    crop = original.crop(box)
    output = crop.copy()
    scale = 1.
    if max_side is not None and max(crop.size) > max_side:
        units = max_side//max(rw, rh)
        output = crop.resize((rw*units, rh*units), Image.Resampling.LANCZOS)
        scale = output.width/crop.width
    cx1, cy1, cx2, cy2 = content
    x1, y1, x2, y2 = box
    intersection = max(0, min(x2, cx2)-max(x1, cx1))*max(0, min(y2, cy2)-max(y1, cy1))
    coverage = intersection/((cx2-cx1)*(cy2-cy1))
    cuts = [max(0, x1-cx1), max(0, y1-cy1), max(0, cx2-x2), max(0, cy2-y2)]
    assert contained == (not any(cuts))
    px1, py1, px2, py2 = priority_box
    primary_intersection = max(0, min(x2, px2)-max(x1, px1))*max(0, min(y2, py2)-max(y1, py1))
    primary_coverage = primary_intersection/((px2-px1)*(py2-py1))
    primary_contained = x1 <= px1 and y1 <= py1 and x2 >= px2 and y2 >= py2
    flags = list(selection.get('issues') or [])
    if not contained:
        if priority_used:
            flags.append('原图无法容纳全部正文，已优先主要指标及前后数据；次要内容允许裁去')
            flags.extend(priority.get('issues') or [])
            if not primary_contained:
                flags.append('原图边界仍不足以容纳完整核心区域，候选保留尽可能多的核心内容，需审核')
        else:
            flags.append('原图无法容纳全部正文，尚未获得核心区域定位；候选需审核')
    evidence = {'medium': medium, 'crop_xyxy': box, 'content_xyxy': content,
                'preferred_xyxy': preferred, 'frame_size': list(output.size), 'ratio': [rw, rh],
                'margin_pixels': margin, 'scale_x': scale, 'scale_y': scale,
                'pixel_policy': 'source_rectangle_pixels' if scale == 1 else 'explicit_max_side_cap',
                'geometry': 'source_rectangle_crop' if scale == 1 else 'source_rectangle_uniform_resize',
                'crop_inside_source': True, 'background_mask_applied': False, 'padding_applied': False,
                'content_fully_contained': contained, 'content_box_coverage': coverage,
                'priority_used': priority_used, 'priority_xyxy': priority_box,
                'priority_fully_contained': primary_contained, 'priority_box_coverage': primary_coverage,
                'content_cut_pixels_ltrb': cuts, 'source_bounds_limited': not contained,
                'perspective_correction': False, 'dewarping': False, 'rotation': False,
                'review_reasons': flags}
    return output, crop, evidence

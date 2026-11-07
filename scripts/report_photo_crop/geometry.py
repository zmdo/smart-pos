"""Only axis-aligned cropping, background masking and a uniform affine scale."""
import math

import cv2
import numpy as np
from PIL import Image, ImageDraw


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


def make_frame(original, selection, ratio=(3, 4), max_side=None):
    if not selection.get('is_report') is True:
        raise ValueError('not_a_report')
    medium = selection.get('medium')
    if medium not in ('screenshot', 'paper_photo'):
        raise ValueError('unknown_report_medium')
    rw, rh = parse_ratio(':'.join(map(str, ratio)))
    if max_side is not None and max_side < max(64, rw, rh):
        raise ValueError('invalid_max_side')
    size = original.size
    content = box_pixels(selection.get('content_box'), size)
    # VLM bounds are approximate; screenshots need room for thin table borders.
    margin = max(4, round(min(size)*(.03 if medium == 'screenshot' else .006)))
    crop_box = padded(content, size, margin)
    working = original
    mask_applied = False
    content_coverage = 1.0
    flags = list(selection.get('issues') or [])
    if medium == 'paper_photo':
        paper = box_pixels(selection.get('paper_box'), size)
        # Retain every claimed useful-content pixel even if paper detection is tighter.
        crop_box = padded([min(paper[0], content[0]), min(paper[1], content[1]),
                           max(paper[2], content[2]), max(paper[3], content[3])], size, margin)
        polygon = selection.get('paper_polygon')
        if (not isinstance(polygon, list) or not 4 <= len(polygon) <= 16
                or any(not isinstance(p, list) or len(p) != 2
                       or any(not isinstance(v, (int, float)) or isinstance(v, bool)
                              or not math.isfinite(v) or not 0 <= v <= 1000 for v in p)
                       for p in polygon)):
            raise ValueError('invalid_paper_polygon')
        points = np.array([[p[0]*size[0]/1000, p[1]*size[1]/1000] for p in polygon], dtype=np.float32)
        hull = cv2.convexHull(points).reshape(-1, 2)
        if cv2.contourArea(hull) < .1*size[0]*size[1]:
            raise ValueError('paper_region_too_small')
        mask = Image.new('L', size)
        ImageDraw.Draw(mask).polygon([tuple(p) for p in hull], fill=255)
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (4*margin+1, 4*margin+1))
        mask = Image.fromarray(cv2.dilate(np.asarray(mask), kernel))
        # A useful-content rectangle includes background corners of tilted pages.
        # Do not union that whole rectangle back into the paper mask. Reject a
        # strongly conflicting paper estimate instead of trusting a narrow polygon.
        cx1, cy1, cx2, cy2 = content
        content_coverage = float(np.mean(np.asarray(mask)[cy1:cy2, cx1:cx2] == 255))
        if content_coverage >= .88:
            working = Image.composite(original, Image.new('RGB', size, 'white'), mask)
            mask_applied = True
        else:
            flags.append('纸边与正文范围冲突，已保留原像素；外围背景需检查')
    crop = working.crop(crop_box)
    cw, ch = crop.size
    # The ratio is fixed; pixel dimensions follow the useful source crop.
    units = math.ceil(max(cw/rw, ch/rh))
    if max_side is not None:
        units = min(units, max_side//max(rw, rh))
    fw, fh = rw*units, rh*units
    frame_size = (fw, fh)
    scale = min(1., fw/cw, fh/ch)
    if scale == 1:
        dx, dy = (fw-cw)//2, (fh-ch)//2
        output = Image.new('RGB', frame_size, 'white')
        output.paste(crop, (dx, dy))
    else:
        # An explicitly requested export cap uses one continuous scalar for both axes.
        dx, dy = (fw-cw*scale)/2, (fh-ch*scale)/2
        output = crop.transform(frame_size, Image.Transform.AFFINE,
                                (1/scale, 0, -dx/scale, 0, 1/scale, -dy/scale),
                                resample=Image.Resampling.BICUBIC, fillcolor='white')
    evidence = {'medium': medium, 'crop_xyxy': crop_box, 'content_xyxy': content,
                'frame_size': list(frame_size), 'margin_pixels': margin, 'scale_x': scale, 'scale_y': scale,
                'ratio': [rw, rh], 'pixel_policy': 'native_crop_pixels' if scale == 1 else 'explicit_max_side_cap',
                'placement_xy': [dx, dy], 'occupied_fraction': cw*ch*scale**2/(fw*fh),
                'background_mask_applied': mask_applied,
                'geometry': 'crop_translation_no_resampling' if scale == 1 else 'crop_uniform_scale_translation',
                'paper_mask_content_box_coverage': content_coverage,
                'perspective_correction': False, 'dewarping': False,
                'rotation': False, 'review_reasons': flags}
    return output, crop, evidence

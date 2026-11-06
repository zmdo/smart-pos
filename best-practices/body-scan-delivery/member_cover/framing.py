"""Use existing verified pose/visibility results; never stretch cover subjects."""
import math
from PIL import Image


def project(point, matrix):
    x, y = point
    z = matrix[2][0]*x+matrix[2][1]*y+matrix[2][2]
    return [(matrix[i][0]*x+matrix[i][1]*y+matrix[i][2])/z for i in (0,1)]


def coverage_rank(meta):
    v = meta['visibility']
    head = v.get('head') == 'complete'
    return (int(head and v.get('lower_extent') == 'feet_complete'), int(head),
            int(v.get('head') == 'touching_border'))


def plan_pair(metadata, sizes, target=(500,478)):
    tw, th = target
    measures = []
    for meta, (w,h) in zip(metadata, sizes):
        H = meta['group_plan']['H_normalized_to_display']
        kp = [project(p,H) for p in meta['keypoints_normalized']]
        confidence = meta['keypoint_confidence']
        if min(confidence[i] for i in (5,6,11,12)) < .35:
            raise ValueError('cover_shoulders_or_hips_unreliable')
        sx, sy = [(kp[5][j]+kp[6][j])/2 for j in (0,1)]
        hy = (kp[11][1]+kp[12][1])/2
        torso = hy-sy
        if not math.isfinite(torso) or torso < 30:
            raise ValueError('invalid_cover_torso_reference')
        v = meta['visible_bounds_normalized']
        top = max(0., min(h-1., project(v[:2],H)[1]+.5))
        measures.append({'shoulder':[sx,sy], 'torso':torso, 'head_top':top,
                         'head_status':meta['visibility']['head'], 'size':[w,h]})
    # Keep the pair's existing common scale. The largest in-bounds fixed-aspect
    # frame gives head/shoulders/torso priority without using face or body width.
    height = min(min(h,w*th/tw) for w,h in sizes)
    width = height*tw/th
    shoulder_target = max((m['shoulder'][1]-m['head_top']+height*.025)/height for m in measures)
    shoulder_target = max(.27,min(.65,shoulder_target))
    plans = []
    for m in measures:
        w,h = m['size'];sx,sy = m['shoulder']
        left = min(max(0.,sx-width/2),(w-width))
        top = min(max(0.,sy-height*shoulder_target),h-height)
        # If the source includes a head, do not sacrifice its top to the anchor.
        if m['head_status'] in ('complete','touching_border'):
            top = min(top,max(0.,m['head_top']-height*.025))
        plans.append({**m,'crop_xyxy':[left,top,left+width,top+height],
                      'output_size':list(target),'scale':tw/width,'scale_x':tw/width,'scale_y':th/height,
                      'mode':'full_body_to_upper_body' if coverage_rank(metadata[len(plans)])[0] else 'available_upper_body',
                      'head_already_incomplete':m['head_status'] not in ('complete','touching_border'),
                      'new_head_crop':top>m['head_top']+.01,
                      'method':'shared_fixed_frame_existing_shoulder_pose'})
    return plans


def crop_photo(path, plan):
    with Image.open(path) as im:
        return im.convert('RGB').resize(tuple(plan['output_size']), Image.Resampling.LANCZOS, box=tuple(plan['crop_xyxy']))

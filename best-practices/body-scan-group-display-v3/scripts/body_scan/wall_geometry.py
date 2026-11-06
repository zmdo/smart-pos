"""Refine camera yaw from semantically verified physical wall lines."""
import math

import cv2
import numpy as np

from .geometry import project


def scene_valid(scene):
    try:
        p = np.asarray(scene['wall_polygon'], float)
        return (scene.get('near_planar_wall') is True and .75 <= float(scene.get('confidence', 0)) <= 1
                and p.ndim == 2 and p.shape[1] == 2 and 3 <= len(p) <= 12
                and np.isfinite(p).all() and ((p >= 0) & (p <= 1)).all())
    except (KeyError, TypeError, ValueError):
        return False


def wall_mask(image, scene, person_mask=None):
    mask = np.zeros(image.shape[:2], np.uint8)
    if not scene_valid(scene):
        return mask
    h, w = image.shape[:2]
    polygon = np.rint(np.asarray(scene['wall_polygon'])*[w-1, h-1]).astype(np.int32)
    cv2.fillPoly(mask, [polygon], 255)
    mask = cv2.erode(mask, np.ones((15, 15), np.uint8))
    if person_mask is not None:
        exclusion = cv2.dilate(person_mask.astype(np.uint8), np.ones((31, 31), np.uint8))
        mask[exclusion > 0] = 0
    return mask


def line_angle(segment):
    d = np.asarray(segment[2:])-segment[:2]
    a = math.degrees(math.atan2(d[1], d[0]))
    return (a+90) % 180-90


def candidates(image, scene, person_mask):
    if not scene_valid(scene) or not scene.get('references'):
        return []
    h, w = image.shape[:2]
    gray=cv2.cvtColor(image,cv2.COLOR_BGR2GRAY)
    lsd=cv2.createLineSegmentDetector(cv2.LSD_REFINE_STD).detect(gray)[0]
    edges=cv2.Canny(gray,40,120)
    hough=cv2.HoughLinesP(edges,1,np.pi/1800,45,minLineLength=w*.10,maxLineGap=w*.04)
    arrays=[a[:,0] for a in (lsd,hough) if a is not None]
    if not arrays:
        return []
    raw=np.concatenate(arrays)
    hints = []
    for ref in scene['references']:
        try:
            q = np.asarray(ref['segment'], float)
            if q.shape != (4,) or not np.isfinite(q).all() or ((q < 0) | (q > 1)).any():
                continue
            if ref.get('kind') not in ('wall_skirt_seam', 'wall_panel_joint', 'wall_boundary'):
                continue
            if float(ref.get('confidence', 0)) >= .75:
                hints.append((ref['direction'], q*[w,h,w,h]))
        except (KeyError, ValueError, TypeError):
            continue
    possible = []
    for s in raw.astype(float):
        a = abs(line_angle(s)); length = float(np.linalg.norm(s[2:]-s[:2]))
        direction = 'horizontal' if a < 20 else ('vertical' if a > 70 else None)
        if direction is None or length < (.12*w if direction == 'horizontal' else .16*h):
            continue
        mid = (s[:2]+s[2:])/2
        hint_dist = []
        for kind, hint in hints:
            if kind != direction:
                continue
            hm = (hint[:2]+hint[2:])/2
            distance = abs(mid[1]-hm[1])/h if kind == 'horizontal' else abs(mid[0]-hm[0])/w
            if distance <= (.12 if kind == 'horizontal' else .07):
                hint_dist.append(distance)
        if not hint_dist:
            continue
        points = np.rint(np.linspace(s[:2], s[2:], 25)).astype(int)
        points = np.clip(points, [0,0], [w-1,h-1])
        if np.mean(person_mask[points[:,1], points[:,0]] > 0) > .15:
            continue
        possible.append({'segment': s.tolist(), 'direction': direction, 'length': length,
                         'score': length/(1+min(hint_dist)*8)})
    # Deduplicate adjacent LSD edges; retain actual measured endpoints.
    selected = []
    for item in sorted(possible, key=lambda c:c['score'], reverse=True):
        s = np.array(item['segment']); mid = (s[:2]+s[2:])/2
        duplicate = False
        for old in selected:
            q = np.array(old['segment']); d = q[2:]-q[:2]; norm = np.linalg.norm(d)
            cross = abs(np.linalg.det(np.stack([d, mid-q[:2]])))/norm
            t = np.dot(mid-q[:2], d)/(norm*norm)
            if old['direction'] == item['direction'] and cross < 5 and -.05 < t < 1.05:
                duplicate = True
        if not duplicate:
            selected.append(item)
        if len(selected) == 14:
            break
    return [{'id': i+1, **s} for i,s in enumerate(selected)]


def annotate(image, lines):
    out = image.copy(); thick = max(2, round(max(image.shape[:2])/600))
    for row in lines:
        s = np.rint(row['segment']).astype(int); a,b = tuple(s[:2]),tuple(s[2:])
        color = ((53*row['id'])%180+60, (97*row['id'])%180+60, (137*row['id'])%180+60)
        cv2.line(out, a, b, color, thick)
        x,y = ((s[:2]+s[2:])//2).tolist(); y=max(30,y-8)
        cv2.putText(out, str(row['id']), (x,y), cv2.FONT_HERSHEY_SIMPLEX, 1, (0,0,0), 6)
        cv2.putText(out, str(row['id']), (x,y), cv2.FONT_HERSHEY_SIMPLEX, 1, color, 2)
    return out


def selected_lines(lines, response):
    if not isinstance(response, dict) or not isinstance(response.get('confidence'), (int,float)) or not .8 <= response['confidence'] <= 1:
        return [], []
    result = []
    for direction in ('horizontal', 'vertical'):
        ids = response.get(direction+'_ids', [])
        if not isinstance(ids, list) or any(type(i) is not int for i in ids):
            return [], []
        indexed = {c['id']:c for c in lines if c['direction']==direction}
        if any(i not in indexed for i in ids):
            return [], []
        result.append([indexed[i] for i in dict.fromkeys(ids)])
    return tuple(result)


def local_jacobian(H, point):
    p = np.asarray(point, float)
    mapped = project([p, p+[.1,0], p+[0,.1]], H)
    return np.stack([(mapped[1]-mapped[0])/.1, (mapped[2]-mapped[0])/.1], axis=1)


def bounded_homography(H, shape, box):
    h,w = shape[:2]; center=(np.asarray(box[:2])+box[2:])/2
    det = np.linalg.det(local_jacobian(H, center))
    if not np.isfinite(det) or det <= 0:
        raise ValueError('wall_transform_flipped')
    scale = 1/np.sqrt(det)
    corners = np.array([[0,0],[w-1,0],[w-1,h-1],[0,h-1]])
    q = np.c_[corners, np.ones(4)]@H.T
    if np.any(q[:,2] <= .3):
        raise ValueError('wall_transform_near_horizon')
    bounds = project(corners,H)*scale
    low = np.floor(bounds.min(axis=0))-2; high=np.ceil(bounds.max(axis=0))+2
    size=(high-low+1).astype(int)
    if max(size)>6000 or np.prod(size)>w*h*2.5:
        raise ValueError('wall_canvas_excessive')
    M=np.array([[scale,0,-low[0]],[0,scale,-low[1]],[0,0,1.]])
    return M@H, M, size.tolist()


def residual(lines,H):
    return [line_angle(project(np.asarray(c['segment']).reshape(2,2),H).ravel()) for c in lines]


def refine(calibration, shape, box, horizontal, vertical):
    if not horizontal or sum(c['length'] for c in horizontal) < shape[1]*.25:
        raise ValueError('wall_horizontal_support_insufficient')
    K=np.asarray(calibration['K']); R=np.asarray(calibration['R']); invK=np.linalg.inv(K)
    base=K@R.T@invK
    before=residual(horizontal,base)
    if np.median(np.abs(before)) < 1.:
        raise ValueError('wall_already_level')
    angles=[];supported=[]
    for c in horizontal:
        p=np.c_[np.asarray(c['segment']).reshape(2,2),np.ones(2)]@invK.T@R
        n=np.cross(p[0],p[1]); direction=np.array([n[2],0,-n[0]])
        if direction[0]<0:direction=-direction
        # A line close to the calibrated horizon cannot constrain yaw reliably.
        level=project(np.asarray(c['segment']).reshape(2,2),base)
        if abs(np.mean(level[:,1])-K[1,2]) < .12*shape[0]:
            continue
        angles.append(math.degrees(math.atan2(direction[2],direction[0])))
        supported.append(c)
    if not angles:
        raise ValueError('wall_yaw_references_disagree')
    # Semantic selection can still include a printed edge. Require a dominant
    # geometric consensus, weighted by actual measured support length.
    angles=np.asarray(angles);weights=np.array([c['length'] for c in supported])
    clusters=[np.abs(angles-a)<=2.5 for a in angles]
    keep=max(clusters,key=lambda m:weights[m].sum())
    if weights[keep].sum()<.6*weights.sum() or weights[keep].sum()<shape[1]*.25:
        raise ValueError('wall_yaw_references_disagree')
    rejected=[c for c,valid in zip(supported,keep) if not valid]
    horizontal=[c for c,valid in zip(supported,keep) if valid]
    angles=angles[keep];weights=weights[keep]
    order=np.argsort(angles)
    yaw=float(angles[order][np.searchsorted(np.cumsum(weights[order]),weights.sum()/2)])
    before=residual(horizontal,base)
    if not 2 < abs(yaw) < 30:
        raise ValueError('wall_yaw_outside_limits')
    a=math.radians(yaw); c,s=math.cos(a),math.sin(a)
    Y=np.array([[c,0,s],[0,1,0],[-s,0,c]])
    H,M,size=bounded_homography(K@Y@R.T@invK,shape,box)
    after=residual(horizontal,H)
    if max(np.abs(after))>1 or np.median(np.abs(after))>=np.median(np.abs(before))*.5:
        raise ValueError('wall_horizontal_residual_not_improved')
    vb=np.abs(np.abs(residual(vertical,base))-90)
    va=np.abs(np.abs(residual(vertical,H))-90)
    if len(va) and (max(va)>max(2.,max(vb)+.5)):
        raise ValueError('wall_vertical_regression')
    singular=[]
    for x in np.linspace(box[0],box[2],3):
        for y in np.linspace(box[1],box[3],3):
            relative=local_jacobian(H,[x,y])@np.linalg.inv(local_jacobian(base,[x,y]))
            singular.append(np.linalg.svd(relative,compute_uv=False))
    singular=np.array(singular)
    anisotropy=float(np.max(singular[:,0]/singular[:,1]))
    variation=float(singular.max()/singular.min())
    if anisotropy>1.18 or variation>1.4:
        raise ValueError('wall_subject_deformation_excessive')
    return H, {'method':'wall-yaw-v1','yaw_deg':yaw,'yaw_candidates_deg':angles.tolist(),
               'horizontal_before_deg':before,'horizontal_after_deg':after,
               'vertical_before_deg':vb.tolist(),'vertical_after_deg':va.tolist(),
               'relative_max_anisotropy':anisotropy,'relative_scale_variation':variation,
               'horizontal_lines':horizontal,'rejected_horizontal_lines':rejected,'vertical_lines':vertical,
               'yaw_rotation':Y.tolist(),'canvas_matrix':M.tolist(),'output_size':size}

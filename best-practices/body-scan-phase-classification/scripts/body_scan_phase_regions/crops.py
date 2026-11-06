"""Translate anatomical windows; never reshape a body or normalize its width."""
from pathlib import Path

import cv2
import numpy as np

from scripts.body_scan.geometry import project
from scripts.body_scan_contracts.images import image_for

REGIONS = ('upper', 'waist', 'legs')
COLORS = {'upper': (60, 150, 40), 'waist': (30, 120, 230), 'legs': (210, 110, 50)}


def landmarks(row):
    kp = np.asarray(row['upstream_report']['pose']['keypoints_source'], float)
    if kp.shape != (17, 3) or not np.isfinite(kp).all():
        raise ValueError('invalid_source_landmarks')
    xy = project(kp[:, :2], np.asarray(row['output']['H_source_to_uniform']))
    pairs = [(s, h) for s, h in ((5, 11), (6, 12)) if min(kp[s, 2], kp[h, 2]) >= .6]
    side = row['upstream_report']['classification']['view'].startswith('side')
    if not pairs or (not side and len(pairs) < 2):
        raise ValueError('unreliable_shoulder_hip_windows')
    if side:
        pairs = [max(pairs, key=lambda p: min(kp[p[0], 2], kp[p[1], 2]))]
    shoulder = np.mean([xy[s] for s, _ in pairs], axis=0)
    hip = np.mean([xy[h] for _, h in pairs], axis=0)
    length = float(np.linalg.norm(hip - shoulder))
    if length < 30 or hip[1] <= shoulder[1]:
        raise ValueError('invalid_torso_geometry')
    return shoulder, hip, length, xy, kp[:, 2]


def crop_window(image, center, width, height, content_edges):
    """Return actual pixels on a common canvas; padding is marked and excluded."""
    x = round(center[0] - width / 2); y = round(center[1] - height / 2)
    rect = [x, y, x + width, y + height]
    l, t, r, b = content_edges
    x1 = max(0, x, int(np.ceil(l))); y1 = max(0, y, int(np.ceil(t)))
    x2 = min(image.shape[1], x + width, int(np.ceil(r)))
    y2 = min(image.shape[0], y + height, int(np.ceil(b)))
    canvas = np.full((height, width, 3), 235, np.uint8)
    coverage = max(0, x2-x1) * max(0, y2-y1) / (width*height)
    if x2 > x1 and y2 > y1:
        canvas[y1-y:y2-y, x1-x:x2-x] = image[y1:y2, x1:x2]
    return canvas, {'rectangle_uniform_xyxy': rect, 'real_pixel_fraction': coverage,
                    'available': coverage >= .85, 'reason': 'ok' if coverage >= .85 else 'region_incomplete'}


def fitted_horizontal_window(center_x, desired_width, common_width, edges):
    """Trim shared background context, not subject scale or per-image width."""
    width = min(desired_width, common_width)
    left, _, right, _ = edges
    center_x = float(np.clip(center_x, left+width/2, right-width/2))
    return center_x, width


def make_pack(item, row, shared_length, common_width):
    source = image_for(item, 'source'); uniform = image_for(item, 'uniform')
    pack = {'source': source, 'uniform': uniform, 'crops': {}, 'regions': {}}
    annotated = uniform.copy()
    try:
        shoulder, hip, length, xy, confidence = landmarks(row)
        if not .65 <= length/shared_length <= 1.55:
            raise ValueError('torso_window_scale_mismatch')
        # Both images use exactly the same window size and resize factor. Body
        # thickness never determines magnification; joints only locate windows.
        windows = {'upper': ((shoulder+hip)/2 - [0, .28*shared_length], 1.8, .95),
                   'waist': (shoulder*.25+hip*.75, 1.7, 1.05),
                   'legs': (hip+[0, .90*shared_length], 1.7, 1.85)}
        for region, (center, wf, hf) in windows.items():
            cx, width = fitted_horizontal_window(center[0], max(32, round(wf*shared_length)),
                                                 common_width, row['group_plan']['uniform_content_edges'])
            crop, meta = crop_window(uniform, (cx, center[1]), width,
                                     max(32, round(hf*shared_length)), row['group_plan']['uniform_content_edges'])
            meta['horizontal_context_shift_pixels'] = float(cx-center[0])
            if region == 'legs' and not any(confidence[i] >= .6 for i in (13, 14)):
                meta.update(available=False, reason='knees_not_reliably_visible')
            pack['crops'][region] = crop; pack['regions'][region] = meta
            x1, y1, x2, y2 = meta['rectangle_uniform_xyxy']
            cv2.rectangle(annotated, (x1, y1), (x2, y2), COLORS[region], 3)
            cv2.putText(annotated, region, (max(0, x1+5), max(25, y1+28)), cv2.FONT_HERSHEY_SIMPLEX, .8, COLORS[region], 2)
        for i, point in enumerate(xy):
            if confidence[i] >= .6:
                cv2.circle(annotated, tuple(np.rint(point).astype(int)), 4, (240, 50, 180), -1)
        pack['window_basis'] = {'shared_torso_pixels': shared_length, 'own_torso_pixels': length,
                                'shared_available_width':common_width,
                                'width_normalization': False, 'pose_warp': False}
    except (ValueError, KeyError) as error:
        pack['regions'] = {r: {'available': False, 'reason': str(error)} for r in REGIONS}
    pack['annotated'] = annotated
    return pack


def board(a, b, title, max_height=850):
    height = max(a.shape[0], b.shape[0]); width = max(a.shape[1], b.shape[1])
    # One scale shared by A and B, including when one input is incomplete.
    scale = min(1., max_height/height, 550/width)
    w, h = max(1, round(width*scale)), max(1, round(height*scale))
    canvas = np.full((h+48, 2*w+16, 3), 249, np.uint8)
    for index, image in enumerate((a, b)):
        sized = cv2.resize(image, (max(1, round(image.shape[1]*scale)), max(1, round(image.shape[0]*scale))))
        x = index*(w+16)+(w-sized.shape[1])//2
        canvas[48:48+sized.shape[0], x:x+sized.shape[1]] = sized
        cv2.putText(canvas, ('A' if index == 0 else 'B')+'  '+title, (index*(w+16)+12, 31),
                    cv2.FONT_HERSHEY_SIMPLEX, .72, (45, 65, 45), 2)
    return canvas


def evidence_images(packs):
    images = [pack[k] for pack in packs for k in ('source', 'uniform')]
    for name in REGIONS:
        placeholder = np.full((150, 200, 3), 235, np.uint8)
        images.append(board(*(p['crops'].get(name, placeholder) for p in packs), name))
    return images


def prepare_pair(items, rows, destination):
    lengths = []
    for row in rows:
        try:
            lengths.append(landmarks(row)[2])
        except (ValueError, KeyError):
            pass
    shared = float(np.mean(lengths)) if lengths else 400.
    common_width = int(np.floor(min(row['group_plan']['uniform_content_edges'][2]-row['group_plan']['uniform_content_edges'][0]
                                   for row in rows)+1e-6))
    if common_width < 32:
        raise ValueError('reference_content_too_narrow')
    packs = [make_pack(item, row, shared, common_width) for item, row in zip(items, rows)]
    dest = Path(destination); dest.mkdir(parents=True, exist_ok=True)
    outputs = {'context': board(*(p['source'] for p in packs), 'original'),
               'reference': board(*(p['annotated'] for p in packs), 'uniform + regions')}
    outputs.update(dict(zip(REGIONS, evidence_images(packs)[4:])))
    for name, im in outputs.items():
        if not cv2.imwrite(str(dest/(name+'.jpg')), im):
            raise OSError('failed_to_write_region_preview')
    metadata = [{'asset_id': item['asset_id'], 'regions': pack['regions'], 'window_basis': pack.get('window_basis')}
                for item, pack in zip(items, packs)]
    return packs, metadata

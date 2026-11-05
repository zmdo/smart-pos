"""Read approved results and bind every downstream item to source/output hashes."""
import hashlib
import json
import re
from pathlib import Path

import cv2
import numpy as np

from scripts.body_scan.geometry import project
from scripts.body_scan.landmarks import member_key


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_inputs(paths):
    items = []; excluded = []; sources = []; seen = set()
    for directory in paths:
        root = Path(directory).resolve()
        config = json.loads((root/'config.json').read_text(encoding='utf-8'))
        if config.get('version') not in ('body-scan-wall-v3', 'body-scan-unified-v2-pinhole'):
            raise ValueError('input_requires_approved_single_photo_results')
        summary = root/'summary.json'
        sources.append({'directory': str(root), 'summary_sha256': digest(summary),
                        'config_sha256': digest(root/'config.json'), 'version': config['version']})
        for row in json.loads(summary.read_text(encoding='utf-8')):
            aid = row['asset_id']
            if not re.fullmatch(r'[A-Za-z0-9_-]+', aid) or aid in seen:
                raise ValueError('invalid_or_duplicate_asset_id: '+aid)
            seen.add(aid)
            if row['status'] != 'rectangular':
                excluded.append({'asset_id': aid, 'status': 'upstream_excluded', 'upstream_status': row['status'],
                                 'reason': row.get('reason'), 'store': row.get('store'), 'member': row.get('member')})
                continue
            member_key(row)
            image_path = root/aid/'aligned.png'
            mask_path = root/aid/'content_mask.png'
            source_path = Path(row['source'])
            if digest(source_path) != row['source_sha256']:
                raise ValueError('original_source_changed: '+aid)
            image = cv2.imread(str(image_path)); mask = cv2.imread(str(mask_path), 0)
            if image is None or mask is None or image.shape[:2] != mask.shape:
                raise ValueError('missing_approved_image_or_mask: '+aid)
            frame = row['frame']; rect = frame['content_rectangle_xyxy']
            x1, y1, x2, y2 = rect
            if (any(type(n) is not int for n in rect)
                    or not (0 <= x1 < x2 <= image.shape[1] and 0 <= y1 < y2 <= image.shape[0])):
                raise ValueError('invalid_approved_content_rectangle: '+aid)
            expected = np.zeros_like(mask); expected[y1:y2, x1:x2] = 255
            if not np.array_equal(mask, expected):
                raise ValueError('approved_content_is_not_rectangular: '+aid)
            H = np.asarray(frame['H_source_to_aligned'], float)
            A = np.asarray(frame['H_corrected_to_aligned'], float)
            if H.shape != (3, 3) or not np.isfinite(H).all() or abs(np.linalg.det(H)) < 1e-10:
                raise ValueError('invalid_approved_transform: '+aid)
            anchor_corrected = frame.get('framing_anchor_corrected', row['pose']['anchor'])
            anchor = project([anchor_corrected], A)[0]
            target_torso = float(frame['torso_target_pixels'])
            if not np.isfinite(target_torso) or target_torso <= 0:
                raise ValueError('invalid_approved_torso_target')
            # Normalize different accepted canvas configurations to the same torso units.
            factor = 483.84/target_torso
            N = np.array([[factor, 0., -factor*anchor[0]], [0., factor, -factor*anchor[1]], [0., 0., 1.]])
            edges = np.asarray(rect, float)-.5
            bounds = np.r_[project([edges[:2]], N)[0], project([edges[2:]], N)[0]]
            kp = np.asarray(row['pose']['keypoints_source'], float)
            points = project(kp[:, :2], N@H)
            selected = sorted({j for pair in row['pose']['selected_pairs'] for j in pair})
            core = np.r_[points[selected].min(axis=0), points[selected].max(axis=0)]
            core += [-8, -8, 8, 8]
            items.append({'asset_id': aid, 'store': row['store'], 'member': row['member'],
                          'input_directory': str(root), 'approved_image': str(image_path),
                          'approved_image_sha256': digest(image_path), 'approved_mask_sha256': digest(mask_path),
                          'approved_content_rectangle': rect, 'source': str(source_path),
                          'source_sha256': row['source_sha256'], 'upstream_report': row,
                          'H_aligned_to_normalized': N.tolist(), 'H_source_to_normalized': (N@H).tolist(),
                          'anchor_policy': 'approved_neutral_shoulder' if frame.get('group_scale') else 'measured_shoulder',
                          'normalized_bounds': bounds.tolist(), 'required_core': core.tolist(),
                          'keypoints_normalized': points.tolist(), 'keypoint_confidence': kp[:, 2].tolist(),
                          'status': 'pending_visibility'})
    return items, excluded, sources


def effective_image(item):
    image = cv2.imread(item['approved_image'])
    x1, y1, x2, y2 = item['approved_content_rectangle']
    return image[y1:y2, x1:x2]


def visible_bounds(item, visibility):
    x1, y1, x2, y2 = item['approved_content_rectangle']
    box = np.asarray(visibility['visible_bbox'])*[x2-x1, y2-y1, x2-x1, y2-y1]+[x1-.5, y1-.5, x1-.5, y1-.5]
    return np.r_[project([box[:2]], item['H_aligned_to_normalized'])[0],
                 project([box[2:]], item['H_aligned_to_normalized'])[0]].tolist()

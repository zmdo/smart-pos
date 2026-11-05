"""Prompted SAM contours for edge evidence, independent of upstream exclusion masks."""
import os

import cv2
import numpy as np

from scripts.body_scan.geometry import project
from scripts.body_scan.localization import mask_quality


class BoundarySegmenter:
    def __init__(self):
        self.model = None

    def __call__(self, image, box, item):
        try:
            import torch
            if self.model is None:
                from sam2.build_sam import build_sam2
                from sam2.sam2_image_predictor import SAM2ImagePredictor
                checkpoint = os.environ.get('CASE_SAM', '/root/autodl-fs/portrait-studio/models/sam2.1_hiera_base_plus.pt')
                config = os.environ.get('CASE_SAM_CONFIG', 'configs/sam2.1/sam2.1_hiera_b+.yaml')
                self.model = SAM2ImagePredictor(build_sam2(config, checkpoint, device='cuda'))
            selected = sorted({j for pair in item['upstream_report']['pose']['selected_pairs'] for j in pair})
            points = project(np.asarray(item['keypoints_normalized'])[selected],
                             np.linalg.inv(item['H_aligned_to_normalized']))-item['approved_content_rectangle'][:2]
            h, w = image.shape[:2]
            if ((points < 0).any() or (points[:, 0] >= w).any() or (points[:, 1] >= h).any()):
                return None, {'error': 'boundary_prompt_outside_image'}
            with torch.inference_mode():
                self.model.set_image(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))
                masks, scores, _ = self.model.predict(box=np.asarray(box, np.float32),
                    point_coords=points.astype(np.float32), point_labels=np.ones(len(points), np.int32),
                    multimask_output=True)
            traces = []; accepted = []
            for index, (mask, score) in enumerate(zip(masks, scores)):
                error = mask_quality(mask, box, image.shape, strict=True)
                coverage = float(mask[points[:, 1].astype(int), points[:, 0].astype(int)].mean())
                traces.append({'candidate': index, 'score': float(score), 'prompt_coverage': coverage, 'error': error})
                if error is None and np.isfinite(score) and score >= .8 and coverage >= .99:
                    accepted.append((float(score), index))
            trace = {'strategy': 'positive_shoulder_hip_points', 'prompt_points': points.tolist(), 'candidates': traces}
            if not accepted:
                return None, {**trace, 'error': 'no_reliable_boundary_mask'}
            _, index = max(accepted)
            return masks[index], {**trace, 'selected_candidate': index}
        except Exception as error:
            return None, {'error': 'boundary_segmentation_unavailable', 'exception_type': type(error).__name__}


def mark_touching_edges(value, guard):
    """Keep edge contact distinct from a semantic assertion that a body part is cut."""
    result = dict(value)
    if guard.get('feet_contact_requires_review') and result['lower_extent'] == 'feet_complete':
        result['lower_extent'] = 'feet_touching_border'
    if guard.get('head_contact_requires_review') and result['head'] == 'complete':
        result['head'] = 'touching_border'
    if result != value:
        result['boundary_completeness_policy'] = 'touching_border_is_not_confirmed_fully_contained'
    return result

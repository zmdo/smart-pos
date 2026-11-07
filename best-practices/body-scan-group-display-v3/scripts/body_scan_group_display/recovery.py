"""Recheck tiny VLM boundary conflicts against pixels, without relaxing the crop."""
import copy
from pathlib import Path

import cv2
import numpy as np

from scripts.body_scan.geometry import project
from .boundary import BoundarySegmenter
from .inputs import digest, effective_image
from .planning import PlanUnavailable, contains, plan_person

CONFLICT = 'common_frame_would_cut_confirmed_head_feet_or_torso'
VERSION = 'common-frame-boundary-recheck-v1'


def candidates(items, error):
    """Only vertical, few-pixel conflicts qualify; torso and canvas stay strict."""
    if str(error) != CONFLICT:
        return []
    common = np.asarray(error.detail['common_rectangle'], float)
    required = np.asarray(error.detail['required_rectangle'], float)
    gap = np.maximum(0, np.r_[common[:2]-required[:2], required[2:]-common[2:]])
    limit = min(4., .003*(common[3]-common[1]))
    if gap[[0, 2]].any() or gap.max() > limit or not gap.any():
        return []
    if any(not contains(common, r['required_core']) for r in items):
        return []
    selected = []
    for item in items:
        body = item['visible_bounds_normalized']
        edges = []
        if error.detail['protected_parts']['head'] and body[1] < common[1]:
            edges.append(1)
        if error.detail['protected_parts']['feet'] and body[3] > common[3]:
            edges.append(3)
        if edges:
            selected.append((item, edges))
    return selected


def plan_with_boundary_review(items, config=None, profiles=None, segmenter=None, evidence_dir=None):
    try:
        return plan_person(items, config, profiles)
    except PlanUnavailable as error:
        selected = candidates(items, error)
        if not selected:
            raise
        original_error = error

    # Commit revised evidence only if the ENTIRE group still satisfies the
    # existing planner. Do not weaken semantics, change scale, or move shoulders.
    proposed = copy.deepcopy(items)
    lookup = {r['asset_id']: r for r in proposed}
    segmenter = segmenter or BoundarySegmenter()
    common = np.asarray(original_error.detail['common_rectangle'], float)
    for item, edges in selected:
        record = {'version': VERSION, 'status': 'rejected',
                  'original_bounds': list(item['visible_bounds_normalized']),
                  'approved_image_sha256': item['approved_image_sha256'],
                  'edges': ['head' if edge == 1 else 'feet' for edge in edges]}
        item['common_frame_boundary_review'] = record
        try:
            if digest(item['approved_image']) != item['approved_image_sha256']:
                raise ValueError('boundary_recheck_image_changed')
            image = effective_image(item)
            h, w = image.shape[:2]
            box = np.asarray(item['visibility']['visible_bbox'])*[w, h, w, h]
            mask, trace = segmenter(image, box, item)
            record['segmentation'] = trace
            selected_mask = next((r for r in trace.get('candidates', [])
                                  if r['candidate'] == trace.get('selected_candidate')), {})
            if (mask is None or mask.shape != (h, w) or not np.any(mask)
                    or selected_mask.get('error') is not None
                    or not np.isfinite(selected_mask.get('score', float('nan')))
                    or selected_mask.get('score', 0) < .9
                    or selected_mask.get('prompt_coverage', 0) < .99):
                raise ValueError('boundary_recheck_requires_reliable_mask')
            ys, xs = np.nonzero(mask)
            # Use ALL foreground, including isolated hair pixels, plus two
            # source-raster pixels of breathing room. Never clamp to the crop.
            margin = 2.
            measured = np.array([xs.min()-.5, ys.min()-.5-margin,
                                 xs.max()+.5, ys.max()+.5+margin])
            N = np.asarray(item['H_aligned_to_normalized'], float)
            if not np.allclose(N, [[N[0, 0], 0, N[0, 2]], [0, N[0, 0], N[1, 2]], [0, 0, 1]]) or N[0, 0] <= 0:
                raise ValueError('boundary_recheck_requires_isotropic_normalization')
            offset = np.asarray(item['approved_content_rectangle'][:2])
            mapped = project(measured.reshape(2, 2)+offset, N).reshape(4)
            new_bounds = list(item['visible_bounds_normalized'])
            change_limit = min(12., .01*h)*N[0, 0]
            record.update(measured_bounds_normalized=mapped.tolist(),
                          minimum_margin_pixels=margin, maximum_boundary_change=change_limit)
            for edge in edges:
                if abs(mapped[edge]-new_bounds[edge]) > change_limit:
                    raise ValueError('boundary_recheck_disagrees_with_visual_evidence')
                if ((edge == 1 and (ys.min() == 0 or mapped[1] < common[1]))
                        or (edge == 3 and (ys.max() == h-1 or mapped[3] > common[3]))):
                    raise ValueError('measured_body_still_outside_common_frame')
                new_bounds[edge] = float(mapped[edge])
            if evidence_dir is not None:
                folder = Path(evidence_dir)
                folder.mkdir(parents=True, exist_ok=True)
                path = folder/(item['asset_id']+'.png')
                if not cv2.imwrite(str(path), mask.astype(np.uint8)*255):
                    raise OSError('boundary_recheck_mask_write_failed')
                record.update(mask_path=str(path.resolve()), mask_sha256=digest(path))
            record.update(status='measured', revised_bounds=new_bounds)
            lookup[item['asset_id']]['visible_bounds_normalized'] = new_bounds
        except (ValueError, OSError) as error:
            record['reason'] = str(error)
            raise original_error from error
    try:
        plan = plan_person(proposed, config, profiles)
    except PlanUnavailable as error:
        for item, _ in selected:
            item['common_frame_boundary_review'].update(status='rejected', reason='rechecked_group_still_infeasible')
        raise original_error from error
    for item, _ in selected:
        item['visible_bounds_normalized'] = lookup[item['asset_id']]['visible_bounds_normalized']
        item['common_frame_boundary_review']['status'] = 'accepted'
    plan['boundary_recheck'] = {'version': VERSION, 'asset_ids': [r['asset_id'] for r, _ in selected],
                               'original_diagnostic': original_error.detail,
                               'policy': 'measured_boundary_with_margin; unchanged_crop_constraints'}
    return plan

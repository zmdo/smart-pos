"""Keep an accepted group presentation when cancelling a scale outlier."""
import copy

import numpy as np

from scripts.body_scan.geometry import project
from .planning import PlanUnavailable, contains, crop_steps

VERSION = 'scale-review-stable-presentation-v1'


def preserve(items, proposed, previous, config):
    if not any(r['upstream_report'].get('person_scale', {}).get('proposal_guard', {}).get('status')
               == 'rejected_worsening_proposal' for r in items):
        return proposed
    if previous is None:
        raise PlanUnavailable('scale_review_requires_reference_presentation', proposed)
    ids = {r['asset_id'] for r in items}
    old = {aid: previous[aid] for aid in ids if aid in previous}
    if set(old) != ids or any(r['status'] != 'displayed' for r in old.values()):
        raise PlanUnavailable('scale_review_reference_members_changed', proposed)
    ref = next(iter(old.values()))['group_plan']
    if set(ref['member_ids']) != ids or any(r['group_plan'] != ref for r in old.values()):
        raise PlanUnavailable('scale_review_reference_has_multiple_frames', proposed)
    crop = ref['crop_rectangle']
    if ref['output_size'][0] != config.width or ref['vertical_stretch'] > config.max_stretch+1e-9:
        raise PlanUnavailable('scale_review_reference_configuration_changed', proposed)
    for row in items:
        prior = old[row['asset_id']]
        if (row['source_sha256'] != prior['source_sha256']
                or row['upstream_report']['geometry'] != prior['upstream_report']['geometry']
                or row['upstream_report']['pose'] != prior['upstream_report']['pose']):
            raise PlanUnavailable('scale_review_reference_source_changed', proposed)
        if not contains(row['normalized_bounds'], crop) or not contains(crop, row['required_core']):
            raise PlanUnavailable('scale_review_reference_frame_no_longer_safe', proposed)
        # Preserve the old visible vertical interval even for partial bodies.
        a = prior['visible_bounds_normalized']; old_crop = prior['group_plan']['crop_rectangle']
        box = [a[0], max(a[1], old_crop[1]), a[2], min(a[3], old_crop[3])]
        H = np.asarray(row['H_source_to_normalized']) @ np.linalg.inv(np.asarray(prior['H_source_to_normalized']))
        mapped = project([[box[0], box[1]], [box[2], box[3]]], H)
        if mapped[:, 1].min() < crop[1]-2 or mapped[:, 1].max() > crop[3]+2:
            raise PlanUnavailable('scale_review_would_reduce_visible_body_in_final_frame', proposed)
        body = row['visible_bounds_normalized']
        if (row['visibility']['head'] == 'complete' and body[1] < crop[1]-1e-6
                or row['visibility']['lower_extent'] == 'feet_complete' and body[3] > crop[3]+1e-6):
            raise PlanUnavailable('scale_review_reference_would_cut_complete_body', proposed)
    if not contains(crop, proposed['required_rectangle']):
        raise PlanUnavailable('scale_review_reference_would_cut_required_body', proposed)
    result = copy.deepcopy(ref)
    common = proposed['common_rectangle']
    loss = 1-(crop[2]-crop[0])*(crop[3]-crop[1])/((common[2]-common[0])*(common[3]-common[1]))
    if loss > config.max_crop_loss+1e-9:
        raise PlanUnavailable('scale_review_reference_exceeds_crop_limit', proposed)
    result.update(common_rectangle=common, required_rectangle=proposed['required_rectangle'],
                  crop_steps=crop_steps(common, crop, config), additional_crop_fraction=loss,
                  input_coverage_counts=proposed['input_coverage_counts'],
                  presentation_stability={'version': VERSION, 'source_asset_ids': sorted(ids),
                      'output_size_crop_stretch_and_shoulders_preserved': True,
                      'visible_body_span_checked_in_source_coordinates': True})
    result.pop('boundary_recheck', None)
    if 'boundary_recheck' in proposed:
        result['boundary_recheck'] = proposed['boundary_recheck']
    return result

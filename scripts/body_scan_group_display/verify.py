"""Check actual artifacts against shared geometry, source hashes and stretch limits."""
import argparse
import json
from pathlib import Path

import cv2
import numpy as np

from scripts.body_scan.pipeline import save_json
from scripts.body_scan.landmarks import member_key
from .inputs import digest
from .planning import contains, Config
from .stability import preserve


def require(value, reason):
    if not value:
        raise ValueError(reason)


def verify_person_groups(rows, groups):
    """Reject multiple formats for a person even if each old-style cohort is valid."""
    keys = set(); seen = set(); formats = []
    for group in groups:
        key = member_key(group)
        require(key not in keys, 'person_split_into_multiple_groups')
        keys.add(key)
        cohorts = group['cohorts']
        require(len(cohorts) <= 1, 'person_split_into_multiple_frames')
        members = [r for r in rows if member_key(r) == key and r['status'] == 'displayed']
        if not members:
            continue
        require(len(cohorts) == 1 and 'plan' in cohorts[0], 'missing_shared_person_plan')
        cohort = cohorts[0]; plan = cohort['plan']
        require(group.get('output_size') == plan['output_size'], 'group_output_size_mismatch')
        for item in members:
            require(item['group_id'] == group['group_id'] and item['cohort_id'] == cohort['cohort_id'], 'person_frame_assignment_mismatch')
            require(item['asset_id'] in cohort['asset_ids'], 'image_not_in_shared_person_plan')
            require(item['group_plan'] == plan, 'person_uses_multiple_crop_or_scale_parameters')
            seen.add(item['asset_id'])
        formats.append({'group_id': group['group_id'], 'store': group['store'], 'member': group['member'],
                        'output_size': plan['output_size'], 'displayed_images': len(members),
                        'single_crop_scale_and_shoulder': True})
    require(seen == {r['asset_id'] for r in rows if r['status'] == 'displayed'}, 'displayed_image_missing_person_group')
    return formats


def verify(out):
    out = Path(out)
    rows = json.loads((out/'summary.json').read_text(encoding='utf-8'))
    groups = json.loads((out/'groups.json').read_text(encoding='utf-8'))
    config = json.loads((out/'config.json').read_text(encoding='utf-8'))
    person_formats = verify_person_groups(rows, groups)
    stable = [g for g in groups if any(c.get('plan', {}).get('presentation_stability') for c in g['cohorts'])]
    if stable:
        ref_path = config.get('reference_display')
        require(ref_path and digest(ref_path) == config.get('reference_display_sha256'), 'reference_presentation_changed')
        previous = {r['asset_id']: r for r in json.loads(Path(ref_path).read_text())}
        settings = Config(**{k: config[k] for k in Config.__dataclass_fields__})
        for group in stable:
            members = [r for r in rows if member_key(r) == member_key(group)]
            actual = group['cohorts'][0]['plan']
            checked = preserve(members, actual, previous, settings)
            for key in ('output_size', 'crop_rectangle', 'vertical_stretch', 'shoulder_target',
                        'H_normalized_to_display', 'H_normalized_to_uniform'):
                require(actual[key] == checked[key], 'reference_presentation_not_preserved')
    plans = {c['cohort_id']: c['plan'] for g in groups for c in g['cohorts'] if 'plan' in c}
    accepted = []
    for row in rows:
        require(digest(row['source']) == row['source_sha256'], 'original_changed')
        require(digest(row['approved_image']) == row['approved_image_sha256'], 'upstream_output_changed')
        if row['status'] != 'displayed':
            continue
        plan = plans[row['cohort_id']]; crop = plan['crop_rectangle']
        recheck = row.get('common_frame_boundary_review', {})
        if recheck.get('status') == 'accepted':
            require(recheck['approved_image_sha256'] == row['approved_image_sha256'], 'boundary_recheck_source_mismatch')
            require(digest(recheck['mask_path']) == recheck['mask_sha256'], 'boundary_recheck_mask_changed')
            require(row['visible_bounds_normalized'] == recheck['revised_bounds'], 'boundary_recheck_bounds_mismatch')
            if 'head' in recheck['edges']:
                require(crop[1] <= recheck['revised_bounds'][1], 'rechecked_head_cut')
            if 'feet' in recheck['edges']:
                require(crop[3] >= recheck['revised_bounds'][3], 'rechecked_feet_cut')
        require(plan == row['group_plan'], 'inconsistent_group_plan')
        require(contains(row['normalized_bounds'], crop), 'crop_outside_approved_rectangle')
        require(contains(crop, plan['required_rectangle']), 'required_body_part_cut')
        sx, sy = plan['scale_x'], plan['scale_y']
        require(1-1e-9 <= sy/sx <= config['max_stretch']+1e-9, 'stretch_limit_exceeded')
        previous = np.asarray(plan['common_rectangle'])
        for step in plan['crop_steps']:
            step = np.asarray(step)
            require(contains(previous, step), 'crop_step_moves_outside_previous')
            removed = 1-(step[2:]-step[:2])/(previous[2:]-previous[:2])
            require((removed <= config['crop_step']+1e-8).all(), 'crop_step_too_large')
            previous = step
        require(np.allclose(previous, crop), 'crop_steps_do_not_reach_final')
        folder = out/'images'/row['asset_id']
        require(digest(folder/'baseline.png') == row['approved_image_sha256'], 'baseline_copy_changed')
        w, h = plan['output_size']
        old_mask = cv2.imread(str(Path(row['input_directory'])/row['asset_id']/'content_mask.png'), 0)
        for variant in ('uniform', 'display'):
            im = cv2.imread(str(folder/(variant+'.png')))
            require(im is not None and im.shape[:2] == (h, w), 'wrong_output_dimensions')
            require(digest(folder/(variant+'.png')) == row['output'][variant+'_sha256'], 'derivative_changed')
            D = np.asarray(plan['H_normalized_to_'+variant])
            if variant == 'uniform':
                require(abs(D[0, 0]-D[1, 1]) < 1e-9, 'reference_not_isotropic')
            source_H = D@np.asarray(row['H_source_to_normalized'])
            require(np.allclose(source_H, row['output']['H_source_to_'+variant]), 'source_transform_mismatch')
            M = D@np.asarray(row['H_aligned_to_normalized'])
            valid = cv2.warpPerspective(old_mask, M, (w, h), flags=cv2.INTER_NEAREST)
            if variant == 'display':
                require((valid == 255).all(), 'display_has_missing_rectangle_pixels')
                require(np.allclose(D[:2, 2], plan['shoulder_target']), 'anchor_mismatch')
            else:
                l, t, r, b = plan['uniform_content_edges']
                xx, yy = np.arange(w)[None, :], np.arange(h)[:, None]
                use = (xx >= l) & (xx < r) & (yy >= t) & (yy < b)
                require((valid[use] == 255).all(), 'reference_has_missing_photo_pixels')
        accepted.append(row['asset_id'])
    result = {'passed': True, 'stable_reference_groups_checked': len(stable),
              'source_hashes_checked': len(rows), 'baseline_copies_checked': len(accepted),
              'person_formats': person_formats,
              'derivative_images_checked': 2*len(accepted), 'displayed_asset_ids': accepted,
              'needs_review_asset_ids': [r['asset_id'] for r in rows if r['status'] != 'displayed'],
              'max_observed_vertical_stretch': max((r['group_plan']['vertical_stretch'] for r in rows if r['status'] == 'displayed'), default=None),
              'checks': ['unchanged original and approved output', 'one output size, crop, scale and shoulder origin per person',
                         'complete rectangular source coverage', 'bounded per-step crop and vertical stretch',
                         'isotropic uniform reference', 'single composed source transform', 'output dimensions and hashes'],
              'presentation_only': True}
    save_json(out/'verification.json', result)
    print(json.dumps(result, ensure_ascii=False), flush=True)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('out', type=Path)
    verify(parser.parse_args().out)

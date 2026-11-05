"""Check actual artifacts against shared geometry, source hashes and stretch limits."""
import argparse
import json
from pathlib import Path

import cv2
import numpy as np

from scripts.body_scan.pipeline import save_json
from .inputs import digest
from .planning import contains


def require(value, reason):
    if not value:
        raise ValueError(reason)


def verify(out):
    out = Path(out)
    rows = json.loads((out/'summary.json').read_text(encoding='utf-8'))
    groups = json.loads((out/'groups.json').read_text(encoding='utf-8'))
    config = json.loads((out/'config.json').read_text(encoding='utf-8'))
    plans = {c['cohort_id']: c['plan'] for g in groups for c in g['cohorts'] if 'plan' in c}
    accepted = []
    for row in rows:
        require(digest(row['source']) == row['source_sha256'], 'original_changed')
        require(digest(row['approved_image']) == row['approved_image_sha256'], 'upstream_output_changed')
        if row['status'] != 'displayed':
            continue
        plan = plans[row['cohort_id']]; crop = plan['crop_rectangle']
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
    result = {'passed': True, 'source_hashes_checked': len(rows), 'baseline_copies_checked': len(accepted),
              'derivative_images_checked': 2*len(accepted), 'displayed_asset_ids': accepted,
              'needs_review_asset_ids': [r['asset_id'] for r in rows if r['status'] != 'displayed'],
              'max_observed_vertical_stretch': max((r['group_plan']['vertical_stretch'] for r in rows if r['status'] == 'displayed'), default=None),
              'checks': ['unchanged original and approved output', 'shared cohort crop and shoulder origin',
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

"""Check provenance, unchanged camera geometry and strictly isotropic new framing."""
import argparse
import json
from pathlib import Path

import cv2
import numpy as np

from scripts.body_scan_group_display.inputs import load_inputs
from scripts.body_scan.pipeline import save_json
from .pipeline import digest
from .grid_consensus import verify_cohorts


def verify(out):
    out = Path(out)
    config = json.loads((out/'config.json').read_text())
    baseline = Path(config['baseline'])
    before = {r['asset_id']: r for r in json.loads((baseline/'summary.json').read_text())}
    rows = json.loads((out/'summary.json').read_text())
    manifest = json.loads((out/'input-manifest.json').read_text())
    if any(digest(p) != sha for p, sha in manifest.items()):
        raise ValueError('input_hash_changed')
    items, excluded, _ = load_inputs([out])
    if {r['asset_id'] for r in rows} != set(before):
        raise ValueError('assets_lost_or_added')
    checked = []
    for row in rows:
        if row['status'] != 'rectangular':
            continue
        aid = row['asset_id']; old = before[aid]; audit = row['person_scale']
        if row['geometry'] != old['geometry'] or row['pose']['keypoints_source'] != old['pose']['keypoints_source']:
            raise ValueError('geometry_or_landmarks_changed: '+aid)
        H = np.asarray(row['frame']['H_corrected_to_aligned'])
        scale = row['frame']['uniform_scale']
        if not np.allclose(H[:2, :2], np.eye(2)*scale) or not np.allclose(H[2], [0, 0, 1]):
            raise ValueError('new_framing_not_isotropic: '+aid)
        if abs(scale/audit['scale']-1) > 1e-8:
            raise ValueError('recorded_scale_mismatch: '+aid)
        if audit['status'] != 'calibrated':
            for name in ('aligned.png', 'available_mask.png', 'content_mask.png'):
                if digest(out/aid/name) != digest(baseline/aid/name):
                    raise ValueError('retained_pixels_changed: '+aid)
        mask = cv2.imread(str(out/aid/'content_mask.png'), 0)
        available = cv2.imread(str(out/aid/'available_mask.png'), 0)
        if np.any((mask > 0) & (available == 0)):
            raise ValueError('invented_content: '+aid)
        checked.append(aid)
    result = {'common_grid_cohorts': verify_cohorts(rows),
              'input_hashes_unchanged': True, 'input_files_checked': len(manifest),
              'geometry_unchanged': True, 'source_landmarks_unchanged': True,
              'new_framing_isotropic': True, 'retained_pixels_identical': True,
              'real_rectangular_content': True, 'rows': len(rows), 'checked_ids': checked,
              'eligible': len(items), 'excluded': len(excluded)}
    save_json(out/'verification.json', result)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    print(verify(parser.parse_args().out))

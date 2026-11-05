"""Verify a real run's geometry, source integrity and optional approved grid baseline."""
import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

import cv2
import numpy as np

from .geometry import project
from .pipeline import save_json


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify(out, grid_baseline=None):
    rows = json.loads((out / 'summary.json').read_text())
    config = json.loads((out / 'config.json').read_text())
    accepted = [r for r in rows if r['status'] == 'rectangular']
    equal_grid_files = []
    for row in rows:
        if 'source_sha256' in row:
            assert sha256(Path(row['source'])) == row['source_sha256'], (row['asset_id'], 'source changed')
    for row in accepted:
        aid = row['asset_id']
        image = cv2.imread(str(out / aid / 'aligned.png'))
        used = cv2.imread(str(out / aid / 'content_mask.png'), 0)
        available = cv2.imread(str(out / aid / 'available_mask.png'), 0)
        assert image.shape == (config['height'], config['width'], 3), aid
        rect = row['frame']['content_rectangle_xyxy']
        x1, y1, x2, y2 = rect
        expected = np.zeros_like(used); expected[y1:y2, x1:x2] = 255
        np.testing.assert_array_equal(used, expected, err_msg=aid)
        assert available[y1:y2, x1:x2].all(), aid
        assert (image[used == 0] == config['background_rgb'][::-1]).all(), aid
        A = np.asarray(row['frame']['H_corrected_to_aligned'])
        H = np.asarray(row['geometry']['H_source_to_corrected'])
        np.testing.assert_allclose(A[:2, :2], np.eye(2)*A[0, 0], err_msg=aid)
        np.testing.assert_allclose(project([row['pose']['anchor']], A)[0],
                                   [config['width']/2-.5, config['height']*config['shoulder_y']-.5], atol=1e-8)
        assert abs(A[0, 0]*row['pose']['torso_length']/config['height'] - config['torso_fraction']) < 1e-12, aid
        np.testing.assert_allclose(row['frame']['H_source_to_aligned'], A@H, err_msg=aid)
        if row['route'] == 'non_grid':
            np.testing.assert_array_equal(H, np.eye(3), err_msg=aid)
            assert row['geometry']['correction_applied'] is False, aid
        elif grid_baseline is not None:
            for name in ('aligned.png', 'content_mask.png'):
                digest = sha256(out / aid / name)
                assert digest == sha256(grid_baseline / aid / name), (aid, name, 'grid regression')
                equal_grid_files.append({'path': aid+'/'+name, 'sha256': digest})
    result = {
        'output_directory': str(out), 'counts': dict(Counter(r['status'] for r in rows)),
        'accepted_routes': dict(Counter(r['route'] for r in accepted)),
        'non_grid_backgrounds': dict(Counter(r['classification']['background'] for r in accepted if r['route'] == 'non_grid')),
        'review': [{'asset_id': r['asset_id'], 'reason': r['reason']} for r in rows if r['status'] == 'needs_review'],
        'new_vlm_requests': sum(r.get('localization', {}).get('vlm', {}).get('request_count', 0) for r in rows),
        'source_integrity': 'all read originals unchanged',
        'geometry_checks': 'all outputs share canvas, torso ratio and shoulder anchor; non-grid H is identity; content is a valid filled rectangle',
        'grid_baseline': str(grid_baseline) if grid_baseline else None,
        'byte_identical_grid_files': equal_grid_files,
    }
    save_json(out / 'validation.json', result)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--grid-baseline', type=Path)
    args = parser.parse_args()
    result = verify(args.out, args.grid_baseline)
    print(json.dumps({k: v for k, v in result.items() if k != 'byte_identical_grid_files'}, ensure_ascii=False, indent=2))
    print('Byte-identical grid files:', len(result['byte_identical_grid_files']))

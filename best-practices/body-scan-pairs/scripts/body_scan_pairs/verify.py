"""Independently check lossless crops, provenance and composed coordinate maps."""
import argparse
import json
from collections import Counter
from pathlib import Path

import cv2
import numpy as np

from scripts.body_scan.geometry import project
from scripts.body_scan.pipeline import save_json
from .boundaries import slice_image, translation
from .pipeline import sha, read_source


def require(condition, message):
    if not condition:
        raise ValueError(message)


def verify(out):
    out = Path(out)
    records = json.loads((out/'summary.json').read_text(encoding='utf-8'))
    job = json.loads((out/'dataset/job.json').read_text(encoding='utf-8'))
    ready = {a['id']: a for a in job['assets']}
    config = json.loads((out/'config.json').read_text(encoding='utf-8'))
    require(sha(config['job']) == config['job_sha256'], 'parent_job_changed')
    children = {}; pairs = []; rejected = []
    for row in records:
        if 'source_sha256' in row:
            require(sha(row['source']) == row['source_sha256'], 'parent_source_changed')
        if row['status'] == 'skipped':
            require(not row['children'], 'excluded_pair_has_children')
            rejected.append({'asset_id': row['asset_id'], 'reason': row.get('reason'),
                             'reason_zh': row.get('reason_zh')})
        if not row['children']:
            continue
        require(row['layout']['seam']['kind'] == 'hard', 'non_hard_pair_was_processed')
        source = read_source(row['source'])
        axis = row['layout']['axis']; rects = row['rectangles_parent_xyxy']
        require(rects[0][axis+2] == rects[1][axis], 'hard_seam_gap_or_overlap')
        accepted = [a for a in row['attempts'] if a.get('accepted')]
        require(len(accepted) == 1, 'missing_unique_accepted_boundary')
        review = accepted[0]['review']['result']
        require(review.get('accept') is True and review.get('independent_photos') is True
                and all(review.get(k) is False for k in ('residual_other_photo', 'residual_blend', 'new_subject_cut')),
                'split_review_failed')
        for child in row['children']:
            aid = child['asset_id']; children[aid] = child
            require(sha(child['source']) == child['source_sha256'], 'child_source_changed')
            image = cv2.imread(child['source'])
            expected = slice_image(source, child['crop_parent_xyxy'])
            np.testing.assert_array_equal(image, expected, err_msg=aid+' is not a lossless parent crop')
            np.testing.assert_array_equal(child['H_parent_to_child'], translation(child['crop_parent_xyxy']))
            np.testing.assert_allclose(np.asarray(child['H_child_to_parent']) @ np.asarray(child['H_parent_to_child']), np.eye(3))
            require((child['status'] == 'ready') == (aid in ready), 'child_job_eligibility_mismatch')
            if aid in ready:
                require(ready[aid]['class'] == child['classification'], 'child_classification_mismatch')
                require(ready[aid]['class']['phase'] == child['phase'], 'chronology_changed')
        pairs.append({'asset_id': row['asset_id'], 'rectangles_parent_xyxy': rects,
                      'source_sha256': row['source_sha256']})
    require(set(ready) <= set(children), 'unverified_child_in_job')
    alignment_checks = []
    if (out/'aligned/summary.json').exists():
        aligned = json.loads((out/'aligned/summary.json').read_text(encoding='utf-8'))
        require({r['asset_id'] for r in aligned} == set(ready), 'alignment_asset_mismatch')
        maps = {r['asset_id']: r for r in json.loads((out/'parent-coordinate-mapping.json').read_text(encoding='utf-8'))}
        for row in aligned:
            aid = row['asset_id']; child = children[aid]
            require(row['source_sha256'] == child['source_sha256'], 'alignment_source_not_child')
            if row['status'] != 'rectangular':
                alignment_checks.append({'asset_id': aid, 'status': row['status'], 'reason': row.get('reason')})
                continue
            H = np.asarray(row['frame']['H_source_to_aligned'])
            C = np.asarray(child['H_parent_to_child'])
            np.testing.assert_allclose(maps[aid]['H_parent_to_aligned'], H@C)
            points = np.asarray(row['pose']['keypoints_source'])[:, :2]
            parent = project(points, np.linalg.inv(C))
            np.testing.assert_allclose(project(parent, H@C), project(points, H), atol=1e-7)
            np.testing.assert_allclose(project(project(parent, H@C), maps[aid]['H_aligned_to_parent']), parent, atol=1e-6)
            frame = row['frame']; x1, y1, x2, y2 = frame['content_rectangle_xyxy']
            used = cv2.imread(str(out/'aligned'/aid/'content_mask.png'), 0)
            available = cv2.imread(str(out/'aligned'/aid/'available_mask.png'), 0)
            expected = np.zeros_like(used); expected[y1:y2, x1:x2] = 255
            np.testing.assert_array_equal(used, expected)
            require(bool(available[y1:y2, x1:x2].all()), 'rectangle_includes_unavailable_pixels')
            image = cv2.imread(str(out/'aligned'/aid/'aligned.png'))
            require(image.shape[:2] == (1792, 768), 'unexpected_canvas_size')
            A = np.asarray(frame['H_corrected_to_aligned'])
            np.testing.assert_allclose(A[:2, :2], np.eye(2)*frame['uniform_scale'])
            if not frame.get('group_scale'):
                np.testing.assert_allclose(project([row['pose']['anchor']], A)[0], [383.5, 1792*.23-.5], atol=1e-7)
                require(abs(row['pose']['torso_length']*frame['uniform_scale']/1792-.27) < 1e-8,
                        'torso_ratio_mismatch')
            alignment_checks.append({'asset_id': aid, 'status': 'verified', 'output_size': [768, 1792],
                                     'parent_coordinate_roundtrip': True, 'valid_rectangle': True,
                                     'aligned_sha256': sha(out/'aligned'/aid/'aligned.png')})
    result = {'version': config['version'], 'output': str(out), 'verified': True,
              'pair_counts': dict(Counter(r['status'] for r in records)), 'verified_lossless_children': len(children),
              'ready_children': len(ready), 'pairs': pairs, 'excluded_pairs': rejected,
              'needs_review_pairs': [{'asset_id': r['asset_id'], 'reason': r.get('reason'),
                                      'reason_zh': r.get('reason_zh')}
                                     for r in records if r['status'] == 'needs_review'],
              'alignment_checks': alignment_checks,
              'code_sha256': {str(p.relative_to(Path(__file__).parent)): sha(p)
                              for p in sorted(Path(__file__).parent.rglob('*.py'))},
              'scope': 'pixel-exact crops and coordinate invariants; semantic judgments are model-reviewed, not ground truth'}
    save_json(out/'validation.json', result)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    print(json.dumps(verify(parser.parse_args().out), ensure_ascii=False, indent=2))

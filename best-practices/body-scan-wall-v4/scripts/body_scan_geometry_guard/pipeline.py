"""Read-only baselines → selectively reframe originals → separate experimental output."""
import copy
import hashlib
import json
import re
import shutil
from collections import Counter
from pathlib import Path

import cv2
import numpy as np

from scripts.body_scan.framing import UniformConfig
from scripts.body_scan.geometry import project
from scripts.body_scan.pipeline import group_records, save_json
from scripts.body_scan.refinement import compose, save_render
from . import VERSION
from .policy import decide

FILES = ('aligned.png', 'available_mask.png', 'content_mask.png')


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def run(inputs, out, members=None):
    out = Path(out).resolve()
    if out.exists():
        raise ValueError('output_directory_already_exists')
    rows = []; lookup = {}; sources = []; configs = {}; all_members = set()
    for directory in inputs:
        root = Path(directory).resolve()
        cfg = json.loads((root/'config.json').read_text())
        if cfg.get('version') != 'body-scan-wall-v3' or cfg.get('geometry_guard_version'):
            raise ValueError('requires_unguarded_wall_v3_results')
        configs[str(root)] = cfg
        sources.append({'directory': str(root), 'summary_sha256': digest(root/'summary.json'),
                        'config_sha256': digest(root/'config.json')})
        for row in json.loads((root/'summary.json').read_text()):
            name = row['store']+'/'+row['member']; all_members.add(name)
            if members and name not in members:
                continue
            aid = row['asset_id']
            if not re.fullmatch(r'[A-Za-z0-9_-]+', aid) or aid in lookup:
                raise ValueError('invalid_or_duplicate_asset_id')
            if row.get('geometry_guard'):
                raise ValueError('already_guarded_input')
            lookup[aid] = (root, copy.deepcopy(row)); rows.append(row)
    if members and set(members)-all_members:
        raise ValueError('unknown_store_member')
    if not rows:
        raise ValueError('empty_guard_selection')
    keys = ('width', 'height', 'torso_fraction', 'shoulder_y', 'background_rgb')
    config_data = {k: next(iter(configs.values()))[k] for k in keys}
    if any(any(cfg[k] != config_data[k] for k in keys) for cfg in configs.values()):
        raise ValueError('incompatible_baseline_framing')
    config = UniformConfig(**config_data)
    # Verify every selected input before creating anything. Preserve skipped/review rows too.
    snapshots = {}
    for row in rows:
        aid = row['asset_id']; root, _ = lookup[aid]
        if row.get('source_sha256') and digest(row['source']) != row['source_sha256']:
            raise ValueError('original_source_changed: '+aid)
        if row['status'] == 'rectangular':
            snapshots[aid] = {name: digest(root/aid/name) for name in FILES+('original.png',)}
    out.mkdir(parents=True)
    # Preserve the single-photo format contract. The guard stage has a separate, explicit version.
    save_json(out/'config.json', {**config_data, 'version': 'body-scan-wall-v3',
              'geometry_guard_version': VERSION, 'sources': sources, 'selected_members': members,
              'experimental': True, 'non_grid_transform': 'evidence_guarded_pinhole'})
    changed = []; retained = []; grids = []
    for row in rows:
        aid = row['asset_id']; root, prior = lookup[aid]
        audit = decide(row)
        audit.update({'input_directory': str(root), 'baseline_file_sha256': snapshots.get(aid, {})})
        row['geometry_guard'] = audit
        target = out/aid
        if row['status'] != 'rectangular':
            target.mkdir(); save_json(target/'report.json', row)
            continue
        # No hard links: a candidate must never modify an old artifact via a shared inode.
        shutil.copytree(root/aid, target)
        if audit['action'] == 'rollback':
            if row['frame'].get('group_scale'):
                # A background registration scale cannot be transferred between coordinate systems.
                # Preserve the approved output for manual review instead of silently losing that alignment.
                audit.update({'action': 'retain_for_review', 'reason': 'group_registration_requires_recompute'})
            else:
                source = cv2.imread(row['source'])
                if source is None:
                    raise ValueError('source_decode_failed')
                result = compose(source, row, np.eye(3), config)
                row['geometry'] = {'method': VERSION, 'action': 'identity_rollback',
                    'correction_applied': False, 'H_source_to_corrected': np.eye(3).tolist(),
                    'output_size': row['size'], 'warnings': [],
                    'previous_geometry': copy.deepcopy(row['geometry']), 'reason': audit['reason']}
                audit['previous_refinement'] = row.get('refinement')
                row['refinement'] = {'status': 'geometry_guard_rollback', 'reason': audit['reason']}
                save_render(out, row, result)
                changed.append(aid)
        if audit['action'] != 'rollback':
            for name in FILES:
                if digest(target/name) != snapshots[aid][name]:
                    raise AssertionError('untargeted_output_changed: '+aid)
            retained.append(aid)
            if row.get('route') == 'grid':
                grids.append(aid)
        save_json(target/'report.json', row)
        print(aid, audit['action'], audit['reason'], flush=True)
        # Validate actual masks and coordinate composition, including recalculated rollback anchors.
        available = cv2.imread(str(target/'available_mask.png'), 0)
        mask = cv2.imread(str(target/'content_mask.png'), 0)
        rect = row['frame']['content_rectangle_xyxy']; x1, y1, x2, y2 = rect
        expected = np.zeros_like(mask); expected[y1:y2, x1:x2] = 255
        np.testing.assert_array_equal(mask, expected)
        assert available[y1:y2, x1:x2].all(), aid
        H = np.asarray(row['geometry']['H_source_to_corrected'])
        A = np.asarray(row['frame']['H_corrected_to_aligned'])
        np.testing.assert_allclose(row['frame']['H_source_to_aligned'], A@H)
        np.testing.assert_array_equal(row['pose']['keypoints_source'], prior['pose']['keypoints_source'])
        if audit['action'] == 'rollback':
            np.testing.assert_allclose(H, np.eye(3))
            np.testing.assert_allclose(A[:2, :2], np.eye(2)*row['frame']['uniform_scale'])
            np.testing.assert_allclose(project([row['pose']['anchor']], A)[0], row['frame']['shoulder_target_xy'])
    # Recheck inputs after processing: raw sources, metadata, old output pixels are immutable.
    for row in rows:
        if row.get('source_sha256'):
            assert digest(row['source']) == row['source_sha256'], row['asset_id']
    for aid, names in snapshots.items():
        for name, sha in names.items():
            assert digest(lookup[aid][0]/aid/name) == sha, (aid, name)
        assert digest(out/aid/'original.png') == names['original.png'], aid
    for entry in sources:
        for name in ('summary', 'config'):
            assert digest(Path(entry['directory'])/(name+'.json')) == entry[name+'_sha256']
    verification = {'version': VERSION, 'counts': dict(Counter(r['status'] for r in rows)),
                    'groups': len({(r['store'], r['member']) for r in rows}),
                    'changed_asset_ids': changed, 'byte_identical_asset_ids': retained,
                    'byte_identical_grid_asset_ids': grids, 'source_and_baseline_unchanged': True,
                    'new_model_requests': 0, 'decisions': dict(Counter(r['geometry_guard']['reason'] for r in rows))}
    save_json(out/'summary.json', rows); save_json(out/'groups.json', group_records(rows))
    save_json(out/'counts.json', verification['counts']); save_json(out/'verification.json', verification)
    return verification

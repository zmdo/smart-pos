"""Read-only adapters for approved display outputs and legacy split manifests."""
import hashlib
import json
import re
from pathlib import Path

import cv2
import numpy as np

from scripts.body_scan.landmarks import member_key
from .policy import panel_phase, text_phase, PHASES


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def bind(path, bindings, expected=None):
    path = Path(path).resolve()
    actual = digest(path)
    if expected is not None and expected != actual:
        raise ValueError('input_fingerprint_changed: '+str(path))
    if str(path) in bindings and bindings[str(path)] != actual:
        raise ValueError('input_changed_during_read')
    bindings[str(path)] = actual
    return path


def split_assignment(asset, job_path, row, bindings, report_override=None):
    """Use real parent rectangles, never a __p01 filename convention."""
    meta = asset['pair_source']
    parent_id = meta['parent_asset_id']
    if not re.fullmatch(r'[A-Za-z0-9_-]+', parent_id):
        raise ValueError('invalid_parent_asset_id')
    report_path = Path(report_override['split_report']) if report_override else job_path.parent.parent/'splits'/parent_id/'report.json'
    parent = read_json(bind(report_path, bindings, report_override['split_report_sha256'] if report_override else None))
    if (parent.get('asset_id') != parent_id or parent.get('status') not in ('split_ready', 'split_with_child_review')
            or parent['layout']['seam']['kind'] != 'hard' or len(parent['children']) != 2):
        raise ValueError('unverified_pair_source')
    if member_key(parent) != member_key(row):
        raise ValueError('pair_member_mismatch')
    accepted = [a for a in parent['attempts'] if a.get('accepted')]
    if len(accepted) != 1:
        raise ValueError('missing_unique_accepted_split')
    review = accepted[0]['review']['result']
    if (review.get('accept') is not True or review.get('independent_photos') is not True
            or any(review.get(k) is not False for k in ('residual_other_photo', 'residual_blend', 'new_subject_cut'))):
        raise ValueError('pair_boundary_review_failed')
    parent_path = bind(parent['source'], bindings, parent['source_sha256'])
    image = cv2.imread(str(parent_path))
    if image is None:
        raise ValueError('unreadable_pair_source')
    axis = {'left_right': 0, 'top_bottom': 1}.get(parent['layout']['layout'])
    if axis is None or parent['layout'].get('axis') != axis:
        raise ValueError('invalid_pair_layout')
    rects = parent['rectangles_parent_xyxy']
    if len(rects) != 2 or rects[0][axis+2] != rects[1][axis]:
        raise ValueError('invalid_ordered_pair_rectangles')
    matched = None
    for index, (child, rect) in enumerate(zip(parent['children'], rects), 1):
        if (len(rect) != 4 or any(type(n) is not int for n in rect)
                or not (0 <= rect[0] < rect[2] <= image.shape[1] and 0 <= rect[1] < rect[3] <= image.shape[0])
                or child['crop_parent_xyxy'] != rect or child['panel_index'] != index):
            raise ValueError('invalid_child_crop')
        child_path = bind(child['source'], bindings, child['source_sha256'])
        crop = cv2.imread(str(child_path))
        if crop is None or not np.array_equal(crop, image[rect[1]:rect[3], rect[0]:rect[2]]):
            raise ValueError('child_is_not_lossless_parent_crop')
        if child['asset_id'] == row['asset_id']:
            same_source = child_path == Path(row['source']).resolve()
            if report_override and not same_source:
                # The workflow may copy a verified child into a combined job.
                # Bind both files and demand identical source bytes; never trust a filename.
                relocated = bind(row['source'], bindings, child['source_sha256'])
                same_source = digest(relocated) == child['source_sha256']
            if (child['status'] != 'ready' or not same_source
                    or child['source_sha256'] != row['source_sha256']
                    or meta['crop_parent_xyxy'] != rect or meta['panel_index'] != index):
                raise ValueError('split_child_provenance_mismatch')
            phase, evidence = panel_phase(parent['layout']['layout'], index, child)
            matched = (phase, {**evidence, 'parent_asset_id': parent_id,
                              'parent_source_sha256': parent['source_sha256'],
                              'report': str(report_path), 'report_sha256': digest(report_path),
                              'crop_parent_xyxy': rect})
    if matched is None:
        raise ValueError('split_child_missing_from_parent')
    return matched


def load(directory, source_manifest=None):
    directory = Path(directory).resolve()
    bindings = {}; items = []; excluded = []; seen = set(); jobs = {}
    config = read_json(bind(directory/'config.json', bindings))
    explicit_sources = read_json(bind(source_manifest, bindings)) if source_manifest else None
    if explicit_sources is not None and (explicit_sources.get('schema') != 'body-scan-source-jobs-v1' or not isinstance(explicit_sources.get('assets'), dict)):
        raise ValueError('invalid_source_job_manifest')
    if config.get('version') != 'body-scan-group-display-v2':
        raise ValueError('requires_approved_group_display_v2')
    for row in read_json(bind(directory/'summary.json', bindings)):
        aid = row['asset_id']
        if not re.fullmatch(r'[A-Za-z0-9_-]+', aid) or aid in seen:
            raise ValueError('invalid_or_duplicate_asset_id')
        seen.add(aid)
        if row['status'] != 'displayed':
            excluded.append({'asset_id': aid, 'reason': row.get('reason'), 'upstream_status': row['status']})
            continue
        store, member = member_key(row)
        source = bind(row['source'], bindings, row['source_sha256'])
        uniform = bind(directory/'images'/aid/'uniform.png', bindings, row['output']['uniform_sha256'])
        classification = row['upstream_report']['classification']
        if classification.get('kind') != 'body_scan' or classification.get('view') not in ('front', 'back', 'side', 'side_left', 'side_right'):
            raise ValueError('invalid_body_scan_view')
        item = {'asset_id': aid, 'store': store, 'member': member, 'view': classification['view'],
                'source': str(source), 'source_sha256': row['source_sha256'],
                'uniform': str(uniform), 'uniform_sha256': row['output']['uniform_sha256'],
                'upstream_phase': classification.get('phase', 'unknown'),
                'phase': 'unknown', 'phase_source': 'unresolved', 'status': 'needs_review',
                'confidence': None, 'reason': 'no_same_view_counterpart', 'evidence': {},
                'verified_chronology': False}
        source_entry = explicit_sources['assets'].get(aid) if explicit_sources is not None else None
        if explicit_sources is not None and not source_entry:
            raise ValueError('source_job_manifest_missing_asset')
        standard_config = Path(row['input_directory'])/'config.json'
        job_key = source_entry['job'] if source_entry else str(standard_config)
        if job_key not in jobs:
            cfg = read_json(bind(standard_config, bindings))
            job_path = bind(source_entry['job'], bindings, source_entry['job_sha256']) if source_entry else bind(cfg['job'], bindings)
            job = read_json(job_path)
            ids = [a['id'] for a in job['assets']]
            if len(ids) != len(set(ids)):
                raise ValueError('duplicate_job_asset_ids')
            jobs[job_key] = job_path, {a['id']: a for a in job['assets']}
        job_path, assets = jobs[job_key]
        if source_entry and digest(job_path) != source_entry['job_sha256']:
            raise ValueError('source_job_manifest_hash_mismatch')
        asset = assets[aid]
        if (member_key(asset) != (store, member)
                or (job_path.parent/'input'/asset['path']).resolve() != source):
            raise ValueError('job_source_or_member_mismatch')
        phase = 'unknown'; evidence = {}
        if asset.get('pair_source'):
            if source_entry and not all(source_entry.get(k) for k in ('split_report','split_report_sha256')):
                raise ValueError('source_job_manifest_missing_split_report')
            phase, evidence = split_assignment(asset, job_path, row, bindings, source_entry)
        if phase == 'unknown':
            # Only literal markers or explicit evidence qualify; legacy class.phase alone is not proof.
            literal = text_phase(source.stem)
            explicit = asset.get('phase_evidence', {})
            observed = text_phase(explicit.get('label_text')) if explicit.get('source') == 'explicit_marker' else 'unknown'
            if literal in PHASES and observed in PHASES and literal != observed:
                item.update(reason='explicit_markers_conflict', blocked=True)
            elif literal in PHASES or observed in PHASES:
                phase = literal if literal in PHASES else observed
                evidence = {'source': 'explicit_marker', 'label_text': source.stem if literal in PHASES else explicit['label_text']}
        if phase in PHASES:
            item.update(phase=phase, phase_source=evidence['source'], status='labeled', evidence=evidence,
                        reason='按已验证拼图位置规则标注' if evidence['source'] == 'comparison_position_rule' else '明确训练前后文字标记')
        items.append(item)
    upstream_excluded = directory/'upstream-excluded.json'
    if upstream_excluded.exists():
        excluded.extend(read_json(bind(upstream_excluded, bindings)))
    return items, excluded, bindings

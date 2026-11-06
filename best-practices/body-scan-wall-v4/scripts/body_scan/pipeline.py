"""Classified originals → background geometry → shared pose and framing."""
import hashlib
import json
import re
from collections import Counter, defaultdict
from dataclasses import asdict
from pathlib import Path

import cv2
import numpy as np

from .framing import (UniformConfig, uniform_plan, compose_full_source,
                      required_subject_rectangle, select_rectangle, rectangular_image)
from .grid import grid_transform
from .classification import apply_audit
from .background_screening import BackgroundScreening, VERSION as BACKGROUND_SCREENING_VERSION, apply_screening
from .landmarks import member_key
from .localization import LocalizationError
from .non_grid import NonGridTransform


VERSION = 'body-scan-unified-v2-pinhole'
VIEW_ORDER = {'front': 0, 'back': 1, 'side_left': 2, 'side_right': 3, 'side': 4}


def save_json(path, value):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temporary.replace(path)


def eligibility(classification):
    """Use the existing VLM labels; never equate detection-box count with people."""
    c = classification or {}
    if c.get('phase') == 'both' or c.get('is_comparison') is True:
        return 'comparison_or_multiple_people'
    if c.get('kind') != 'body_scan':
        return 'not_body_scan'
    if isinstance(c.get('people'), (int, float)) and c['people'] > 1:
        return 'comparison_or_multiple_people'
    if c.get('people') != 1:
        return 'single_person_not_confirmed'
    if c.get('wall_background') is False or c.get('background') in ('mirror', 'outdoor'):
        return 'not_wall_body_scan'
    if c.get('body_scan_pose') is False or c.get('training_activity') is True:
        return 'not_static_body_scan'
    if c.get('wall_background') is not True or c.get('body_scan_pose') is not True:
        return 'wall_classification_refresh_required'
    return None


def render(source, subject, classification, pose_estimator, config, non_grid_transform=None, progress=None):
    route = 'grid' if classification.get('background') == 'grid_board' else 'non_grid'
    transform = grid_transform if route == 'grid' else (non_grid_transform or NonGridTransform())
    H, geometry = transform(source, subject)
    if progress is not None:
        progress.update({'route': route, 'geometry': {**geometry, 'H_source_to_corrected': H.tolist()}})
    localization = pose_estimator.locate(source, subject.box, H, classification.get('view'))
    pose = localization['pose']
    plan = uniform_plan(pose, config)
    A = np.asarray(plan['H_corrected_to_aligned'])
    combined = A @ H
    full, available, coverage = compose_full_source(source, combined, config)
    rect, metrics = select_rectangle(available, required_subject_rectangle(pose, A, config))
    output, used = rectangular_image(full, available, rect, config.background_rgb)
    report = {
        'route': route, 'geometry': {**geometry, 'H_source_to_corrected': H.tolist()},
        'pose_localization': localization, 'pose': pose,
        'frame': {**plan, **coverage, **metrics, 'H_source_to_aligned': combined.tolist(),
                  'content_rectangle_xyxy': rect, 'available_pixels': int(np.count_nonzero(available)),
                  'used_pixels': int(np.count_nonzero(used)),
                  'padding_fraction': float(np.mean(used == 0))},
    }
    return output, available, used, report


def process(asset, input_dir, out, localizer, pose_estimator, config, non_grid_transform=None,
            background_screening=None):
    classification = asset.get('class') or {}
    report = {'asset_id': asset['id'], 'store': asset.get('store'), 'member': asset.get('member'),
              'classification': classification, 'status': 'skipped'}
    if 'classification_evidence' in asset:
        report['classification_evidence'] = asset['classification_evidence']
    for key in ('pair_source', 'phase_evidence'):
        if key in asset:
            report[key] = asset[key]
    reason = eligibility(classification)
    if reason:
        return {**report, 'reason': reason,
                'status': 'needs_review' if reason == 'wall_classification_refresh_required' else 'skipped'}
    try:
        member_key(asset)
        if classification.get('view') not in VIEW_ORDER:
            raise ValueError('view_not_confirmed')
        if not classification.get('background'):
            raise ValueError('background_not_classified')
        source_path = (input_dir / asset['path']).resolve()
        if not source_path.is_relative_to(input_dir.resolve()):
            raise ValueError('source_outside_input_directory')
        source = cv2.imread(str(source_path))
        if source is None:
            raise ValueError('unreadable_image')
        report.update({'source': str(source_path), 'size': [source.shape[1], source.shape[0]],
                       'source_sha256': hashlib.sha256(source_path.read_bytes()).hexdigest()})
        if not apply_screening(report, source, background_screening or BackgroundScreening()):
            dest = out / asset['id']
            dest.mkdir()
            save_json(dest / 'report.json', report)
            return report
        subject = localizer.localize(source, classification)
        report.update({'subject_box': subject.box, 'localization': subject.trace})
        image, available, used, measurements = render(source, subject, classification, pose_estimator, config,
                                                     non_grid_transform, report)
        report.update(measurements)
        dest = out / asset['id']
        dest.mkdir()
        for name, value in [('original.png', source), ('aligned.png', image),
                            ('available_mask.png', available), ('content_mask.png', used)]:
            if not cv2.imwrite(str(dest / name), value):
                raise OSError('image_write_failed')
        report['status'] = 'rectangular'
        save_json(dest / 'report.json', report)
    except (ValueError, OSError) as error:
        report.update({'status': 'needs_review', 'reason': str(error)})
        if isinstance(error, LocalizationError):
            report['localization'] = error.trace
        if hasattr(error, 'attempts'):
            report['pose_attempts'] = error.attempts
        if hasattr(error, 'geometry'):
            report.update({'route': 'non_grid', 'geometry': error.geometry})
    return report


def group_records(records):
    members = defaultdict(list)
    for record in records:
        if eligibility(record['classification']) is None and record.get('store') and record.get('member'):
            members[member_key(record)].append(record)
    groups = []
    for number, ((store, member), rows) in enumerate(sorted(members.items()), 1):
        rows.sort(key=lambda r: (VIEW_ORDER.get(r['classification'].get('view'), 5), r['asset_id']))
        accepted = [r['asset_id'] for r in rows if r['status'] == 'rectangular']
        excluded = [r['asset_id'] for r in rows if r['status'] != 'rectangular']
        groups.append({'group_id': f'g{number:03d}', 'store': store, 'member': member,
                       'requested_asset_ids': [r['asset_id'] for r in rows],
                       'asset_ids': accepted, 'excluded_asset_ids': excluded,
                       'status': 'complete' if not excluded else ('partial' if accepted else 'needs_review')})
    return groups


def run(job_path, out, localizer, pose_estimator, config=None, asset_ids=None, background='all',
        non_grid_transform=None, classification_audit=None, background_screening=None):
    config = config or UniformConfig()
    job_path, out = Path(job_path), Path(out)
    assets = json.loads(job_path.read_text(encoding='utf-8'))['assets']
    ids = [a['id'] for a in assets]
    if len(set(ids)) != len(ids) or any(not re.fullmatch(r'[A-Za-z0-9_-]+', aid) for aid in ids):
        raise ValueError('invalid_or_duplicate_asset_ids')
    if asset_ids is not None:
        missing = set(asset_ids) - set(ids)
        if missing:
            raise ValueError('unknown_asset_ids: ' + ','.join(sorted(missing)))
        assets = [a for a in assets if a['id'] in asset_ids]
    audit_info = None
    if classification_audit is not None:
        assets, audit_info = apply_audit(assets, job_path.parent/'input', classification_audit)
    if background not in ('all', 'grid', 'non-grid'):
        raise ValueError('invalid_background_filter')
    if background != 'all':
        assets = [a for a in assets if ((a.get('class') or {}).get('background') == 'grid_board') == (background == 'grid')]
    out.mkdir(parents=True, exist_ok=False)
    non_grid_transform = non_grid_transform or NonGridTransform()
    background_screening = background_screening or BackgroundScreening()
    save_json(out / 'config.json', {'version': VERSION, **asdict(config), 'job': str(job_path),
                                  'background_filter': background, 'asset_ids': [a['id'] for a in assets],
                                  'classification_source': 'verified_wall_audit' if audit_info else 'existing_job_vlm_labels',
                                  'classification_audit': audit_info, 'non_grid_transform': non_grid_transform.mode,
                                  'background_screening_version': BACKGROUND_SCREENING_VERSION})
    records = []
    save_json(out / 'summary.json', records)
    for asset in assets:
        row = process(asset, job_path.parent / 'input', out, localizer, pose_estimator, config, non_grid_transform,
                      background_screening)
        records.append(row)
        save_json(out / 'summary.json', records)
        print(asset['id'], row['status'], row.get('reason', row.get('route', '')), flush=True)
    groups = group_records(records)
    save_json(out / 'groups.json', groups)
    counts = dict(Counter(row['status'] for row in records))
    save_json(out / 'counts.json', counts)
    return records, groups

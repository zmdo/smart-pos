"""Experimental scale node between approved geometry and shared group framing."""
import copy
import hashlib
import json
import shutil
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import cv2
import numpy as np

from scripts.body_scan.framing import UniformConfig
from scripts.body_scan.landmarks import member_key
from scripts.body_scan.pipeline import group_records, save_json
from scripts.body_scan.refinement import compose, save_render
from scripts.body_scan.segmentation import SamSegmenter
from scripts.body_scan_full_eval.client import MeasuredClient
from scripts.body_scan_phase_sessions.client import ModelCallFailure
from scripts.body_scan_group_display.boundary import BoundarySegmenter
from scripts.body_scan_group_display.inputs import effective_image
from . import VERSION
from .background import extract
from .coverage import check as check_coverage, measure_bounds
from .evidence import PROMPT, validate
from .measurements import measure
from .solve import plan


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def render_plan(row, audit, config):
    scale = audit['scale']
    shoulder_y = config.height*config.shoulder_y-.5
    if audit['raised_arms']:
        hip_y = shoulder_y+audit['neutral_torso_pixels']
        anchor_basis = 'hip_and_group_neutral_torso; actual_shoulders_not_flattened'
    else:
        hip_y = shoulder_y+scale*(row['pose']['hip_anchor'][1]-row['pose']['anchor'][1])
        anchor_basis = 'actual_shoulder_anchor'
    return {'method': VERSION, 'uniform_scale': scale, 'target_hip_y': hip_y,
            'anchor_basis': anchor_basis, 'reference_method': audit['method']}


def run(baseline, out, settings, cache, baseline_display, workers=3):
    baseline, out = Path(baseline).resolve(), Path(out).resolve()
    if out.exists():
        raise ValueError('output_directory_already_exists')
    if baseline in out.parents:
        raise ValueError('output_must_be_outside_input_directory')
    config_data = json.loads((baseline/'config.json').read_text())
    if config_data.get('version') not in ('body-scan-wall-v3', 'body-scan-unified-v2-pinhole'):
        raise ValueError('requires_approved_standardization_input')
    rows = json.loads((baseline/'summary.json').read_text())
    previous_display = {r['asset_id']: r for r in json.loads((Path(baseline_display)/'summary.json').read_text())}
    if len({r['asset_id'] for r in rows}) != len(rows):
        raise ValueError('duplicate_asset_id')
    manifest = {str(baseline/name): digest(baseline/name) for name in ('summary.json', 'config.json')}
    manifest[str(Path(baseline_display)/'summary.json')] = digest(Path(baseline_display)/'summary.json')
    groups = defaultdict(list)
    for row in rows:
        aid = row['asset_id']
        if Path(aid).name != aid or aid in ('.', '..'):
            raise ValueError('invalid_asset_id')
        if row['status'] != 'rectangular':
            continue
        if digest(row['source']) != row['source_sha256']:
            raise ValueError('original_source_changed: '+aid)
        manifest[row['source']] = row['source_sha256']
        for name in ('aligned.png', 'available_mask.png', 'content_mask.png', 'report.json'):
            manifest[str(baseline/aid/name)] = digest(baseline/aid/name)
        prior = previous_display.get(aid, {})
        if (prior.get('status') != 'displayed' or prior.get('source_sha256') != row['source_sha256']
                or prior.get('approved_image_sha256') != digest(baseline/aid/'aligned.png')
                or prior.get('upstream_report', {}).get('frame') != row['frame']):
            raise ValueError('requires_matching_previous_display_and_visibility: '+aid)
        groups[member_key(row)].append(row)
    config = UniformConfig(**{k: config_data[k] for k in ('width', 'height', 'torso_fraction', 'shoulder_y', 'background_rgb')})
    out.mkdir(parents=True)
    save_json(out/'input-manifest.json', manifest)
    save_json(out/'config.json', {**config_data, 'experimental': True, 'person_scale_version': VERSION,
        'baseline': str(baseline), 'baseline_display': str(Path(baseline_display).resolve()),
        'scale_policy': 'one_person_reference_one_isotropic_scale_per_image',
        'camera_geometry_changed': False, 'upstream_best_practice_version': config_data.get('best_practice_version')})
    for row in rows:
        src, dest = baseline/row['asset_id'], out/row['asset_id']
        if src.exists():
            shutil.copytree(src, dest)
        else:
            dest.mkdir()
    client = MeasuredClient(settings, cache, provider='qwen')

    def inspect(pair):
        key, members = pair
        members.sort(key=lambda r: r['asset_id'])
        images = [cv2.imread(r['source']) for r in members]
        if any(im is None for im in images):
            raise ValueError('source_image_unreadable')
        record = {'store': key[0], 'member': key[1], 'asset_ids': [r['asset_id'] for r in members]}
        try:
            answer, trace = client.ask(images, PROMPT, VERSION+'-eligibility-v1')
            record['evidence'] = {'result': answer, **trace}
            semantics = validate(answer, {f'I{i+1}': r['asset_id'] for i, r in enumerate(members)})
            contexts = [{'row': r, 'source': im, 'semantic': semantics[r['asset_id']],
                         'measurement': measure(r, semantics[r['asset_id']])} for r, im in zip(members, images)]
            print('/'.join(key), 'semantics_ready', flush=True)
            return contexts, record
        except (ValueError, ModelCallFailure) as error:
            record.update(status='retained_for_review', reason=str(error))
            if hasattr(error, 'evidence'):
                record['evidence'] = error.evidence
            return [], record

    segmenter = SamSegmenter(); boundary_segmenter = BoundarySegmenter(); audits = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        inspected = list(pool.map(inspect, sorted(groups.items())))
    for contexts, record in inspected:
        audits.append(record)
        if contexts:
            for context in contexts:
                row = context['row']
                person = segmenter(context['source'], [row['subject_box']])[0]
                context['background'] = extract(context['source'], row, person)
                context['background']['mask_fallback'] = segmenter.last_fallback
            try:
                plans, reference = plan(contexts)
                record.update(status='planned', reference=reference)
            except ValueError as error:
                record.update(status='retained_for_review', reason=str(error))
                plans = {}
            for context in contexts:
                row = context['row']; aid = row['asset_id']
                audit = plans.get(aid, {'status': 'retained_for_review', 'reason': record.get('reason'),
                                       'scale': row['frame']['uniform_scale'], 'relative_scale': 1.})
                audit.update(version=VERSION, semantic=context['semantic'], measurement=context['measurement'],
                    background={k: v for k, v in context['background'].items() if k != 'features'},
                    previous_frame=copy.deepcopy(row['frame']))
                if audit['status'] == 'calibrated':
                    try:
                        result = compose(context['source'], row, np.asarray(row['geometry']['H_source_to_corrected']),
                                         config, render_plan(row, audit, config))
                        prior = previous_display[aid]
                        prior_image = effective_image(prior)
                        h, w = prior_image.shape[:2]
                        box = np.asarray(prior['visibility']['visible_bbox'])*[w, h, w, h]
                        boundary_mask, trace = boundary_segmenter(prior_image, box, prior)
                        audit['boundary_measurement'] = trace
                        if boundary_mask is None:
                            raise ValueError('reliable_previous_body_boundary_unavailable')
                        bounds = measure_bounds(boundary_mask, row['frame']['content_rectangle_xyxy'])
                        audit['boundary_measurement']['bounds_aligned'] = bounds
                        if not cv2.imwrite(str(out/aid/'previous_body_mask.png'), boundary_mask.astype(np.uint8)*255):
                            raise OSError('boundary_mask_write_failed')
                        audit['coverage_guard'] = check_coverage(prior, row['frame'], result[4], bounds)
                        if audit['coverage_guard']['reason']:
                            raise ValueError(audit['coverage_guard']['reason'])
                        if result[4]['padding_fraction'] > row['frame']['padding_fraction']+.04:
                            raise ValueError('new_padding_above_four_percentage_points')
                    except ValueError as error:
                        audit.update(status='retained_for_review', reason=str(error),
                            proposed_scale=audit['scale'], scale=audit['base_scale'], relative_scale=1.)
                    else:
                        # I/O failures abort the experiment instead of claiming a partial write was retained.
                        save_render(out, row, result)
                row['person_scale'] = audit
                save_json(out/aid/'report.json', row)
                print(aid, audit['status'], round(audit['relative_scale'], 4), audit['reason'], flush=True)
        else:
            for row in groups[(record['store'], record['member'])]:
                row['person_scale'] = {'version': VERSION, 'status': 'retained_for_review', 'reason': record['reason'],
                    'scale': row['frame']['uniform_scale'], 'relative_scale': 1.}
                save_json(out/row['asset_id']/'report.json', row)
        save_json(out/'summary.json', rows)
        save_json(out/'scale-groups.json', audits)
    save_json(out/'summary.json', rows)
    save_json(out/'groups.json', group_records(rows))
    save_json(out/'counts.json', dict(Counter(r.get('person_scale', {}).get('status', r['status']) for r in rows)))
    unchanged = all(digest(path) == value for path, value in manifest.items())
    if not unchanged:
        raise ValueError('input_changed_during_experiment')
    save_json(out/'verification.json', {'input_hashes_unchanged': True, 'input_files_checked': len(manifest),
        'geometry_unchanged': all(r['geometry'] == next(b['geometry'] for b in json.loads((baseline/'summary.json').read_text())
                                if b['asset_id'] == r['asset_id']) for r in rows if r['status'] == 'rectangular'),
        'rows': len(rows), 'groups': len(groups)})
    return rows

"""Read-only input adapter → capture sessions → observations → group resolution."""
import copy
import json
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from itertools import combinations
from pathlib import Path

import cv2
from PIL import Image

from scripts.body_scan.pipeline import save_json
from scripts.body_scan_phase.inputs import load, bind, digest
from scripts.body_scan_phase.policy import PHASES
from . import VERSION
from .evidence import SessionEvidence, family
from .resolution import make_units, resolve


def capture_metadata(path):
    """EXIF camera time only, never filesystem/download timestamps."""
    try:
        with Image.open(path) as im:
            exif = im.getexif()
            nested = exif.get_ifd(34665) if 34665 in exif else {}
            raw = nested.get(36867) or exif.get(36867)
        if not isinstance(raw, str):
            return None
        timestamp = datetime.strptime(raw.strip('\x00 '), '%Y:%m:%d %H:%M:%S')
        return {'datetime_original': timestamp.isoformat(), 'independently_verified': False}
    except (ValueError, TypeError, OSError, SyntaxError):
        return None


def image_for(item, field):
    path = Path(item[field])
    if digest(path) != item[field+'_sha256']:
        raise ValueError('input_changed_during_model_read')
    image = cv2.imread(str(path))
    if image is None:
        raise ValueError('unreadable_model_image')
    return image


def process_group(group_id, items, evidence):
    items = copy.deepcopy(items)
    # Content-derived ordering avoids implicitly presenting filename order as chronology.
    active = sorted((r for r in items if not r.get('blocked')), key=lambda r: (r['source_sha256'], r['asset_id']))
    group = {'group_id': group_id, 'store': items[0]['store'], 'member': items[0]['member'],
             'asset_ids': [r['asset_id'] for r in items], 'session_candidates': [], 'session_audit': {}}
    for item in items:
        item['capture_metadata'] = capture_metadata(item['source'])
        item['group_id'] = group_id
    if len(active) > 12:
        for item in items:
            if item['phase'] == 'unknown':
                item['reason'] = 'too_many_member_images'
        group['units'] = make_units(items, [], group_id); group['relations'] = []; group['comparisons'] = []
        group['reason'] = 'too_many_member_images'
        return items, group
    if len(active) > 1 and any(r['phase'] == 'unknown' for r in active):
        candidates, audit = evidence.sessions(active, [image_for(r, 'source') for r in active])
        group['session_audit'] = audit
        lookup = {r['asset_id']: r for r in items}
        for session in candidates:
            times = [datetime.fromisoformat(lookup[k]['capture_metadata']['datetime_original'])
                     for k in session['members'] if lookup[k]['capture_metadata']]
            if len(times) >= 2 and (max(times)-min(times)).total_seconds() > 6*3600:
                session.update(reliable=False, reliability_reason='camera_times_disagree')
        group['session_candidates'] = candidates
    units = make_units(items, group['session_candidates'], group_id)
    comparisons = []
    for a, b in combinations(active, 2):
        if family(a['view']) != family(b['view']) or a['session_id'] == b['session_id']:
            continue
        if a['phase'] in PHASES and b['phase'] in PHASES:
            continue
        pair = {'pair_id': f'{group_id}c{len(comparisons)+1:02d}', 'asset_ids': [a['asset_id'], b['asset_id']],
                'upstream_views': [a['view'], b['view']], 'view_family': family(a['view'])}
        if a['source_sha256'] == b['source_sha256']:
            pair.update(decision={'after': None, 'strength': 'none', 'markers': {}, 'reason': 'identical_sources'}, audit={})
        else:
            images = [image_for(r, key) for r in (a, b) for key in ('source', 'uniform')]
            pair['decision'], pair['audit'] = evidence.compare(images)
        comparisons.append(pair)
        for item in (a, b):
            if item['phase'] == 'unknown':
                item['reason'] = pair['decision']['reason']
        print(pair['pair_id'], group['member'], pair['decision'].get('after'), pair['decision']['strength'], flush=True)
    # Independent text readings in both presentations can label individual photos.
    marker_proposals = defaultdict(set); marker_pairs = defaultdict(list)
    lookup = {r['asset_id']: r for r in items}
    for pair in comparisons:
        for key, phase in pair['decision'].get('markers', {}).items():
            aid = pair['asset_ids'][0 if key == 'A' else 1]
            marker_proposals[aid].add(phase); marker_pairs[aid].append(pair['pair_id'])
    for aid, phases in marker_proposals.items():
        row = lookup[aid]
        if row['phase'] in PHASES:
            if phases != {row['phase']}:
                row['phase_warning'] = 'visible_text_conflicts_with_source_rule'
        elif len(phases) == 1:
            row.update(phase=next(iter(phases)), status='labeled', phase_source='vlm_explicit_markers',
                       reason='same_literal_marker_in_both_presentations', evidence={'comparison_ids': marker_pairs[aid]})
        else:
            row.update(blocked=True, reason='conflicting_visible_markers')
    relations = resolve(items, units, comparisons)
    group.update(units=units, relations=relations, comparisons=comparisons)
    return items, group


def request_counts(groups):
    counts = Counter()
    for group in groups:
        audits = [group['session_audit'], *(p['audit'] for p in group['comparisons'])]
        for audit in audits:
            for stage in ('primary', 'reversed', 'swapped'):
                call = audit.get(stage)
                if call:
                    counts['recorded_new_requests'] += call.get('request_count', 0)
                    counts['cached_responses'] += int(call.get('cached', False))
                    counts['failed_stages'] += int('error' in call)
    return dict(counts)


def run(directory, out, evidence=None, workers=3, baseline=None):
    if type(workers) is not int or not 1 <= workers <= 4:
        raise ValueError('invalid_worker_count')
    items, excluded, bindings = load(directory)
    original = {r['asset_id']: copy.deepcopy(r) for r in items}
    out = Path(out).resolve(); out.mkdir(parents=True, exist_ok=False)
    config = {'version': VERSION, 'input': str(Path(directory).resolve()), 'workers': workers,
              'policy': 'fixed rules > repeated literal markers > session-aware observations',
              'confidence_is_informational': True, 'max_images_per_member': 12,
              'inference_inputs': ['source', 'uniform'], 'baseline': str(Path(baseline).resolve()) if baseline else None}
    save_json(out/'config.json', config)
    baseline_rows = None
    if baseline:
        path = bind(Path(baseline)/'summary.json', bindings)
        baseline_rows = json.loads(path.read_text(encoding='utf-8'))
        if {r['asset_id'] for r in baseline_rows} != set(original):
            raise ValueError('baseline_asset_ids_differ')
        for row in baseline_rows:
            if row['source_sha256'] != original[row['asset_id']]['source_sha256']:
                raise ValueError('baseline_sources_differ')
    save_json(out/'sources.json', bindings)
    grouped = defaultdict(list)
    for item in items:
        grouped[(item['store'], item['member'])].append(item)
    evidence = evidence or SessionEvidence('/root/autodl-fs/case-studio/cache/training-phase-sessions')
    rows = []; groups = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        pending = {pool.submit(process_group, f'g{i:03d}', group, evidence): key
                   for i, (key, group) in enumerate(sorted(grouped.items()), 1)}
        for future in as_completed(pending):
            result, group = future.result()
            rows.extend(result); groups.append(group)
            save_json(out/'progress.json', {'completed_groups': len(groups), 'total_groups': len(grouped)})
            (out/'groups').mkdir(exist_ok=True)
            save_json(out/'groups'/(group['group_id']+'.json'), group)
            print(group['group_id'], group['member'], dict(Counter(r['phase'] for r in result)), flush=True)
    rows.sort(key=lambda r: r['asset_id']); groups.sort(key=lambda g: g['group_id'])
    for path, expected in bindings.items():
        if digest(path) != expected:
            raise ValueError('input_changed_during_annotation')
    if len(rows) != len(original) or {r['asset_id'] for r in rows} != set(original):
        raise ValueError('incomplete_output_coverage')
    for row in rows:
        initial = original[row['asset_id']]
        if initial['phase'] in PHASES and row['phase'] != initial['phase']:
            raise ValueError('reliable_source_phase_was_changed')
    save_json(out/'summary.json', rows); save_json(out/'groups.json', groups)
    save_json(out/'upstream-excluded.json', excluded)
    slots = defaultdict(lambda: {'before': [], 'after': [], 'unknown': []})
    for row in rows:
        slots[(row['store'], row['member'], row['view'])][row['phase']].append(row['asset_id'])
    save_json(out/'slots.json', [{'store': k[0], 'member': k[1], 'view': k[2], **v} for k, v in sorted(slots.items())])
    counts = {'total': len(rows), 'groups': len(groups), 'phases': dict(Counter(r['phase'] for r in rows)),
              'phase_sources': dict(Counter(r['phase_source'] for r in rows)),
              'unknown_reasons': dict(Counter(r['reason'] for r in rows if r['phase'] == 'unknown')),
              'tentative_suggestions': sum('suggestion' in r for r in rows),
              'reviewed_multi_image_sessions': sum(u['membership'] == 'reviewed_session' for g in groups for u in g['units']),
              'comparisons': sum(len(g['comparisons']) for g in groups), 'model': request_counts(groups),
              'upstream_excluded': len(excluded)}
    save_json(out/'counts.json', counts)
    if baseline_rows is not None:
        old = {r['asset_id']: r for r in baseline_rows}
        save_json(out/'baseline-comparison.json', {'before': dict(Counter(r['phase'] for r in baseline_rows)),
                  'after': counts['phases'], 'changes': [{'asset_id': r['asset_id'], 'old_phase': old[r['asset_id']]['phase'],
                  'new_phase': r['phase'], 'new_source': r['phase_source']} for r in rows if r['phase'] != old[r['asset_id']]['phase']]})
    save_json(out/'verification.json', {'input_files_unchanged': len(bindings), 'complete_input_coverage': True,
               'fixed_phase_labels_preserved': True, 'no_display_stretch_used_for_inference': True,
               'verified_chronology': False, 'scope': 'Input integrity and policy checks, not semantic ground truth.'})
    return counts

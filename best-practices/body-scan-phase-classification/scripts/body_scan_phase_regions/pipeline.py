"""All eligible store photos, unchanged session policy, three evidence ablations."""
import copy
import json
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from itertools import combinations
from pathlib import Path

from PIL import Image

from scripts.body_scan_contracts.io import save as save_json
from scripts.body_scan_phase.inputs import load, bind, digest
from scripts.body_scan_phase.policy import PHASES
from scripts.body_scan_phase_sessions.evidence import SessionEvidence, family
from scripts.body_scan_contracts.images import capture_metadata, image_for
from scripts.body_scan_phase_sessions.resolution import make_units, resolve
from scripts.body_scan_contracts.client import MeasuredClient
from . import VERSION
from .crops import prepare_pair
from .evidence import compare
from .fusion import fuse
from scripts.body_scan_contracts.bundles import load_reports
from scripts.body_scan_phase_classification.report_evidence import expected_changes


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def inputs(directory, overrides, source_manifest=None):
    bindings = {}; selected = {}; metadata = {}; excluded = []
    for index, path in enumerate([directory, *overrides]):
        if index == 0:
            rows, omitted, sources = load(path, source_manifest)
        else:
            # Newer approved display snapshots inherit several upstream jobs.
            # The base adapter already verified each original and split rule;
            # overlays may replace only the reference image, never identity,
            # source pixels or fixed phases. No synthetic job file is needed.
            sources = {}; rows = []; omitted = []
            cfg = read(bind(Path(path)/'config.json', sources))
            if cfg.get('version') != 'body-scan-group-display-v2':
                raise ValueError('unsupported_override_display')
            originals = read(bind(Path(path)/'summary.json', sources))
            if len({r['asset_id'] for r in originals}) != len(originals):
                raise ValueError('duplicate_override_id')
            for raw in originals:
                aid = raw['asset_id']
                if aid not in selected:
                    raise ValueError('override_not_in_base_input')
                if raw['status'] != 'displayed':
                    omitted.append({'asset_id':aid, 'reason':'override_not_displayed_base_retained'}); continue
                old = selected[aid]; cls = raw['upstream_report']['classification']
                if (any(old[k] != raw[k] for k in ('source_sha256','store','member'))
                        or cls.get('kind') != 'body_scan' or cls.get('view') != old['view']):
                    raise ValueError('override_changes_source_or_identity: '+aid)
                row = copy.deepcopy(old)
                row['source'] = str(bind(raw['source'], sources, raw['source_sha256']))
                row['uniform'] = str(bind(Path(path)/'images'/aid/'uniform.png', sources, raw['output']['uniform_sha256']))
                row['uniform_sha256'] = raw['output']['uniform_sha256']
                rows.append(row)
        for source, sha in sources.items():
            if source in bindings and bindings[source] != sha:
                raise ValueError('source_changed_between_inputs')
            bindings[source] = sha
        originals = {r['asset_id']: r for r in read(Path(path)/'summary.json')}
        excluded.extend({**r, 'input': str(Path(path).resolve())} for r in omitted)
        for row in rows:
            aid = row['asset_id']
            if not row['store'].endswith('店'):
                raise ValueError('non_store_member_in_input')
            if index:
                if aid not in selected or any(selected[aid][key] != row[key] for key in
                    ('source_sha256','store','member','view','phase','phase_source')):
                    raise ValueError('override_changes_source_or_identity: '+aid)
            selected[aid] = row; metadata[aid] = originals[aid]
            row['display_input'] = str(Path(path).resolve())
    return list(selected.values()), metadata, excluded, bindings


def apply_markers(items, comparisons):
    proposals = defaultdict(set)
    for pair in comparisons:
        for label, phase in pair['decision'].get('markers', {}).items():
            proposals[pair['asset_ids'][0 if label == 'A' else 1]].add(phase)
    for row in items:
        phases = proposals[row['asset_id']]
        if row['phase'] in PHASES:
            if phases and phases != {row['phase']}:
                row['phase_warning'] = 'visible_marker_conflicts_with_fixed_rule'
        elif len(phases) > 1:
            row.update(blocked=True, reason='conflicting_visible_markers')
        elif len(phases) == 1 and not row.get('blocked'):
            row.update(phase=next(iter(phases)), status='labeled', phase_source='vlm_explicit_markers',
                       reason='same_literal_marker_in_both_presentations')


def process_group(gid, original, metadata, reports, client, baseline, out):
    items = copy.deepcopy(original)
    active = sorted((r for r in items if not r.get('blocked')), key=lambda r: (r['source_sha256'], r['asset_id']))
    evidence = SessionEvidence(client.cache); evidence.ask = client.ask
    group = {'group_id': gid, 'store': items[0]['store'], 'member': items[0]['member'],
             'asset_ids': [r['asset_id'] for r in items], 'report_ids': [r['report_id'] for r in reports],
             'session_candidates': [], 'session_audit': {}, 'comparisons': []}
    for row in items:
        row['capture_metadata'] = capture_metadata(row['source']); row['group_id'] = gid
    if len(active) <= 12 and len(active) > 1 and any(r['phase'] == 'unknown' for r in active):
        candidates, audit = evidence.sessions(active, [image_for(r, 'source') for r in active])
        lookup = {r['asset_id']: r for r in items}
        for candidate in candidates:
            times = [datetime.fromisoformat(lookup[k]['capture_metadata']['datetime_original'])
                     for k in candidate['members'] if lookup[k]['capture_metadata']]
            if len(times) >= 2 and (max(times)-min(times)).total_seconds() > 6*3600:
                candidate.update(reliable=False, reliability_reason='camera_times_disagree')
        group.update(session_candidates=candidates, session_audit=audit)
    units = make_units(items, group['session_candidates'], gid)
    if len(active) > 12:
        group['reason'] = 'too_many_member_images'
    else:
        for a, b in combinations(active, 2):
            if family(a['view']) != family(b['view']) or a['session_id'] == b['session_id'] or a['phase'] in PHASES and b['phase'] in PHASES:
                continue
            pid = f'{gid}c{len(group["comparisons"])+1:02d}'
            pair = {'pair_id': pid, 'asset_ids': [a['asset_id'], b['asset_id']], 'view_family': family(a['view'])}
            packs, crop_meta = prepare_pair([a, b], [metadata[a['asset_id']],metadata[b['asset_id']]], out/'pairs'/pid)
            pair['crop_metadata'] = crop_meta
            old = baseline['pairs'].get(tuple(pair['asset_ids']))
            same_refs = old and all(baseline['rows'].get(r['asset_id'], {}).get('uniform_sha256') == r['uniform_sha256'] for r in (a,b))
            if a['source_sha256'] == b['source_sha256']:
                pair['baseline_decision'] = {'after':None, 'strength':'none', 'reason':'identical_sources', 'markers':{}}
                pair['baseline_audit'] = {}
            elif same_refs:
                pair['baseline_decision'] = copy.deepcopy(old['decision'])
                pair['baseline_audit'] = {'reused_verified_baseline': True, 'pair_id': old['pair_id']}
            else:
                pair['baseline_decision'], pair['baseline_audit'] = evidence.compare(
                    [image_for(r, k) for r in (a,b) for k in ('source','uniform')])
            pair['regional_decision'], pair['regional_audit'] = compare(client, packs, a['source_sha256'] == b['source_sha256'])
            pair['fused_decision'] = fuse(pair['regional_decision'], reports)
            group['comparisons'].append(pair)
            save_json(out/'pairs'/pid/'evidence.json', pair)
            print(pid, group['member'], 'old=', pair['baseline_decision']['after'],
                  'region=', pair['regional_decision']['after'], 'report=', pair['fused_decision']['after'], flush=True)
    strategies = {}
    for strategy, field in (('baseline','baseline_decision'),('regional','regional_decision'),('fused','fused_decision')):
        rows = copy.deepcopy(items); local_units = copy.deepcopy(units)
        pairs = [{**p, 'decision': copy.deepcopy(p[field])} for p in group['comparisons']]
        for row in rows:
            relevant = [p for p in pairs if row['asset_id'] in p['asset_ids']]
            if relevant and row['phase'] == 'unknown':
                row['comparison_reasons'] = [{'pair_id':p['pair_id'], 'reason':p['decision']['reason']} for p in relevant]
                row['reason'] = ' / '.join(sorted({p['decision']['reason'] for p in relevant}))
        apply_markers(rows, pairs)
        edges = resolve(rows, local_units, pairs)
        for row in rows:
            initial = next(r for r in original if r['asset_id'] == row['asset_id'])
            row['evidence_kind'] = ('source_rule' if initial['phase'] in PHASES else
                                    'explicit_text' if row['phase_source'] == 'vlm_explicit_markers' else
                                    'inferred' if row['phase'] in PHASES else 'needs_review')
            row['verified_chronology'] = False
            row['strategy'] = strategy
            if len(active) > 12 and row['phase'] == 'unknown':
                row['reason'] = 'too_many_member_images'
        strategies[strategy] = {'rows': rows, 'units': local_units, 'relations': edges}
    group['strategies'] = {key: {k:v for k,v in value.items() if k != 'rows'} for key,value in strategies.items()}
    return group, {k:v['rows'] for k,v in strategies.items()}


def run(args):
    out = args.out.resolve(); out.mkdir(parents=True, exist_ok=False)
    items, metadata, excluded, bindings = inputs(args.input, args.override, getattr(args,'source_manifest',None))
    if args.member:
        chosen = set(args.member)
        if chosen - {r['member'] for r in items}:
            raise ValueError('requested_member_not_in_input')
        items = [r for r in items if r['member'] in chosen]
    save_json(out/'config.json', {'version': VERSION, 'input': str(args.input.resolve()),
        'overrides': [str(p.resolve()) for p in args.override], 'members': args.member,
        'baseline': str(args.baseline.resolve()) if args.baseline else None,
        'report_bundle': str(args.reports.resolve()) if args.reports else None,
        'provider': args.provider, 'workers': args.workers, 'inference_inputs': ['source','uniform','translated_region_windows'],
        'reports_hidden_from_visual_model': True, 'verified_chronology': False})
    baseline = {'rows':{}, 'pairs':{}}
    if args.baseline:
        baseline_rows = read(bind(args.baseline/'summary.json', bindings))
        baseline_groups = read(bind(args.baseline/'groups.json', bindings))
        baseline = {'rows': {r['asset_id']:r for r in baseline_rows},
                    'pairs': {tuple(p['asset_ids']):p for g in baseline_groups for p in g['comparisons']}}
        for r in items:
            old = baseline['rows'].get(r['asset_id'])
            if not old or any(old.get(k) != r.get(k) for k in ('source_sha256','store','member','view')):
                raise ValueError('baseline_originals_differ')
    client = MeasuredClient(args.settings, args.cache, args.provider)
    grouped = defaultdict(list)
    for item in items:
        grouped[(item['store'],item['member'])].append(item)
    reports = load_reports(args.reports, bindings) if args.reports else []
    inventory = read(args.reports/'inventory.json') if args.reports else []
    reports = [{**r, 'expected_changes':expected_changes(r)} for r in reports
               if (r['store'],r.get('member')) in grouped]
    save_json(out/'reports/reports.json',reports)
    save_json(out/'reports/inventory.json',inventory)
    save_json(out/'report-link.json',{'path':str(args.reports.resolve()) if args.reports else None,
        'sha256':digest(args.reports/'bundle.json') if args.reports else None})
    for report in reports:
        save_json(out/'reports'/report['report_id']/'report.json',report)
    by_member = defaultdict(list)
    for report in reports:
        by_member[(report['store'],report['member'])].append(report)
    groups = []; all_rows = {k:[] for k in ('baseline','regional','fused')}
    (out/'groups').mkdir(exist_ok=True)
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        jobs = [pool.submit(process_group, f'g{i:03d}', rows, metadata, by_member[key], client, baseline, out)
                for i,(key,rows) in enumerate(sorted(grouped.items()),1)]
        for future in as_completed(jobs):
            group, results = future.result(); groups.append(group)
            for key, rows in results.items():
                all_rows[key].extend(rows)
            save_json(out/'groups'/(group['group_id']+'.json'), group)
            save_json(out/'progress.json', {'complete_groups':len(groups), 'total_groups':len(grouped)})
    controls = []
    if args.controls:
        for view in ('front','back','side'):
            candidates = sorted((r for r in items if family(r['view']) == view), key=lambda r:r['source_sha256'])
            if not candidates:
                continue
            row = candidates[0]
            packs, crop_meta = prepare_pair([row,row], [metadata[row['asset_id']]]*2, out/'controls'/view)
            result, audit = compare(client, packs, identical=True, probe_identical=True)
            controls.append({'view':view, 'asset_id':row['asset_id'], 'decision':result, 'audit':audit, 'crop_metadata':crop_meta})
    save_json(out/'controls.json', controls)
    for row in items:
        dest = out/'images'/row['asset_id']; dest.mkdir(parents=True, exist_ok=True)
        for name in ('source','uniform'):
            with Image.open(row[name]) as im:
                im = im.convert('RGB'); im.thumbnail((600,1100)); im.save(dest/(name+'.jpg'),quality=92)
    count = {}
    originals = {r['asset_id']:r for r in items}
    for key, rows in all_rows.items():
        rows.sort(key=lambda r:r['asset_id'])
        if len(rows) != len(items) or {r['asset_id'] for r in rows} != set(originals):
            raise ValueError('output_coverage_changed')
        if any(originals[r['asset_id']]['phase'] in PHASES and r['phase'] != originals[r['asset_id']]['phase'] for r in rows):
            raise ValueError('fixed_rule_was_changed')
        count[key] = {'phases':dict(Counter(r['phase'] for r in rows)),
                      'evidence_kinds':dict(Counter(r['evidence_kind'] for r in rows)),
                      'tentative':sum('suggestion' in r for r in rows)}
        save_json(out/('summary.json' if key == 'fused' else key+'-summary.json'), rows)
    groups.sort(key=lambda g:g['group_id']); save_json(out/'groups.json', groups)
    pairs = [p for g in groups for p in g['comparisons']]
    count.update(total=len(items), groups=len(groups), comparisons=len(pairs),
                 reports={'matched':len(reports), 'verified_transcriptions':sum(r['status']=='verified_transcription' for r in reports),
                          'unmatched_store_reports':sum(e.get('status') != 'excluded' and (e.get('store'),e.get('member')) not in grouped for e in inventory)},
                 pair_decisions={s:dict(Counter(p[s+'_decision']['after'] or 'unknown' for p in pairs)) for s in ('baseline','regional','fused')},
                 negative_controls=len(controls), original_source_rules=sum(r['phase'] in PHASES for r in items),
                 note='Adoption and evidence coverage, not accuracy: true photo chronology is not available.')
    audits = []
    for group in groups:
        audits.extend(group['session_audit'].get(stage,{}) for stage in ('primary','reversed'))
        for pair in group['comparisons']:
            for kind in ('baseline_audit','regional_audit'):
                audits.extend(pair[kind].get(stage,{}) for stage in ('primary','swapped'))
    for control in controls:
        audits.extend(control['audit'].get(stage,{}) for stage in ('primary','swapped'))
    count['model_calls'] = {'new_requests':sum(a.get('request_count',0) for a in audits),
                            'cached_stages':sum(bool(a.get('cached')) for a in audits),
                            'failed_stages':sum('error' in a for a in audits),
                            'reused_baseline_pairs':sum(p['baseline_audit'].get('reused_verified_baseline',False) for p in pairs)}
    save_json(out/'counts.json', count); save_json(out/'upstream-excluded.json', excluded)
    save_json(out/'sources.json', bindings)
    changed = [p for p,sha in bindings.items() if digest(p) != sha]
    if changed:
        raise ValueError('input_files_changed_during_experiment')
    save_json(out/'verification.json', {'input_files_unchanged':len(bindings), 'all_eligible_rows_accounted_for':True,
        'fixed_rule_labels_preserved':True, 'no_display_png_used':True, 'reports_blinded_from_visual_calls':True,
        'negative_controls_blocked':all(c['decision']['after'] is None for c in controls),
        'verified_photo_chronology':False, 'coverage':'all supplied eligible stores' if not args.member else 'explicit member subset'})
    from .preview import preview
    preview(out)
    return count

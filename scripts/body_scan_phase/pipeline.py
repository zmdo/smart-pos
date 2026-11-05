"""Phase annotation is additive: original and approved images remain untouched."""
from collections import Counter, defaultdict
from itertools import combinations
from pathlib import Path

import cv2

from scripts.body_scan.pipeline import save_json
from . import VERSION
from .evidence import PhaseEvidence, validate
from .inputs import load, bind, digest
from .policy import PHASES


def resolve(items, comparisons):
    """Conflicting pairwise proposals never overwrite stronger source labels."""
    lookup = {r['asset_id']: r for r in items}
    proposals = defaultdict(list); conflicts = set()
    for pair in comparisons:
        before = pair['decision']['before']
        if before == 'unknown':
            continue
        ids = pair['asset_ids']; labels = ['before', 'after'] if before == 'A' else ['after', 'before']
        mismatch = any(lookup[aid]['phase'] in PHASES and lookup[aid]['phase'] != label for aid, label in zip(ids, labels))
        if mismatch:
            pair['resolution'] = 'conflicts_with_reliable_marker'
            conflicts.update(aid for aid in ids if lookup[aid]['phase'] == 'unknown')
            continue
        pair['resolution'] = 'consistent'
        for aid, label in zip(ids, labels):
            proposals[aid].append((label, pair))
    for item in items:
        if item['phase'] in PHASES or item.get('blocked'):
            continue
        aid = item['asset_id']; proposed = proposals[aid]
        labels = {label for label, _ in proposed}
        if aid in conflicts or len(labels) > 1:
            item['reason'] = 'pairwise_assignments_conflict'
        elif len(labels) == 1:
            pair_ids = [p['pair_id'] for _, p in proposed]
            sources = {p['decision']['source'] for _, p in proposed}
            item.update(phase=next(iter(labels)), status='labeled',
                        phase_source=next(iter(sources)) if len(sources) == 1 else 'mixed_model_evidence',
                        confidence=min(p['decision']['confidence'] for _, p in proposed),
                        reason='；'.join(dict.fromkeys(p['decision']['reason'] for _, p in proposed)),
                        evidence={'comparison_ids': pair_ids})
    return items


def suggestions(items, comparisons):
    """Expose the model's tentative choice without promoting it to a slot label."""
    hints = defaultdict(list)
    for pair in comparisons:
        audit = pair.get('evidence', {})
        raw = audit.get('primary', {}).get('result', {})
        if (pair.get('resolution') == 'conflicts_with_reliable_marker'
                or audit.get('failed_stage') == 'primary'
                or pair['decision'].get('reason') in ('appearance_signals_conflict', 'visible_marker_conflict')):
            continue
        try:
            validate(raw)
        except ValueError:
            continue
        before = raw.get('before')
        if before not in ('A', 'B') or not all(raw.get(k) is True for k in ('comparable', 'same_view', 'same_pose')):
            continue
        swapped = audit.get('swapped', {}).get('result', {})
        if swapped.get('before') in ('A', 'B') and swapped['before'] == before:
            continue
        labels = ['before', 'after'] if before == 'A' else ['after', 'before']
        for aid, phase in zip(pair['asset_ids'], labels):
            hints[aid].append({'phase': phase, 'confidence': raw.get('confidence'),
                               'reason': raw.get('reason', ''), 'pair_id': pair['pair_id']})
    for item in items:
        candidates = hints[item['asset_id']]
        if item['phase'] == 'unknown' and not item.get('blocked') and len({c['phase'] for c in candidates}) == 1:
            item['suggestion'] = {'phase': candidates[0]['phase'], 'requires_review': True,
                                  'evidence': candidates}


def run(directory, out, evidence=None, threshold=.8):
    if not .5 <= threshold <= 1:
        raise ValueError('invalid_confidence_threshold')
    items, excluded, bindings = load(directory)
    out = Path(out).resolve(); out.mkdir(parents=True, exist_ok=False)
    save_json(out/'config.json', {'version': VERSION, 'input': str(Path(directory).resolve()),
                                'confidence_threshold': threshold, 'max_same_view_group': 6,
                                'comparison_inputs': ['original', 'uniform'],
                                'policy': 'position_rule > explicit_marker > paired_appearance; swapped_review'})
    save_json(out/'sources.json', bindings)
    evidence = evidence or PhaseEvidence('/root/autodl-fs/case-studio/cache/training-phase')
    grouped = defaultdict(list); comparisons = []
    for item in items:
        grouped[(item['store'], item['member'], item['view'])].append(item)
    for key, group in sorted(grouped.items()):
        group = sorted(group, key=lambda r: r['asset_id'])
        active = [r for r in group if not r.get('blocked')]
        if len(active) > 6:
            for item in active:
                if item['phase'] == 'unknown':
                    item['reason'] = 'too_many_same_view_candidates'
            continue
        for a, b in combinations(active, 2):
            if a['phase'] in PHASES and b['phase'] in PHASES:
                continue
            pair = {'pair_id': f'c{len(comparisons)+1:04d}', 'store': key[0], 'member': key[1],
                    'view': key[2], 'asset_ids': [a['asset_id'], b['asset_id']]}
            try:
                images = []
                for item in (a, b):
                    for field in ('source', 'uniform'):
                        path = bind(item[field], bindings, item[field+'_sha256'])
                        image = cv2.imread(str(path))
                        if image is None:
                            raise ValueError('unreadable_comparison_image')
                        images.append(image)
                if a['source_sha256'] == b['source_sha256']:
                    raise ValueError('identical_source_images')
                pair['decision'], pair['evidence'] = evidence.compare(images, key[2], threshold)
            except (ValueError, OSError) as error:
                pair['decision'] = {'before': 'unknown', 'reason': str(error), 'source': 'unresolved', 'confidence': 0.}
            comparisons.append(pair)
            for item in (a, b):
                if item['phase'] == 'unknown':
                    item['reason'] = pair['decision']['reason']
            save_json(out/'comparisons.json', comparisons)
            print(pair['pair_id'], '/'.join(key), pair['decision']['before'], flush=True)
    resolve(items, comparisons)
    suggestions(items, comparisons)
    for path, expected in bindings.items():
        if digest(path) != expected:
            raise ValueError('input_changed_during_annotation: '+path)
    save_json(out/'summary.json', items)
    save_json(out/'comparisons.json', comparisons)
    save_json(out/'upstream-excluded.json', excluded)
    counts = {'total': len(items), 'phases': dict(Counter(r['phase'] for r in items)),
              'sources': dict(Counter(r['phase_source'] for r in items)), 'upstream_excluded': len(excluded),
              'comparisons': len(comparisons), 'model_requests': sum(
                  p.get('evidence', {}).get(stage, {}).get('request_count', 0)
                  for p in comparisons for stage in ('primary', 'swapped')),
              'failed_model_calls': sum('failed_stage' in p.get('evidence', {}) for p in comparisons)}
    counts['tentative_suggestions'] = sum('suggestion' in r for r in items)
    save_json(out/'counts.json', counts)
    # Slot lists remain lists: do not arbitrarily select one of several candidates.
    slots = []
    for (store, member, view), group in sorted(grouped.items()):
        slots.append({'store': store, 'member': member, 'view': view,
                      **{phase: [r['asset_id'] for r in group if r['phase'] == phase] for phase in (*PHASES, 'unknown')}})
    save_json(out/'slots.json', slots)
    save_json(out/'verification.json', {'input_files_unchanged': len(bindings), 'complete_input_coverage': True,
                                      'original_and_uniform_only': True, 'verified_chronology': False,
                                      'scope': '文件来源与规则一致性校验，不是训练时间或模型语义正确率验证'})
    return counts

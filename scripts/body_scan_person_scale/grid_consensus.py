"""Recover a demonstrably worsening body-scale proposal using one physical grid."""
import copy

import numpy as np

VERSION = 'common-grid-scale-recovery-v1'


def spread(values):
    return float(max(values)/min(values)-1)


def reconcile(contexts, plans):
    # Restrict this fallback to one measured, confidently shared, nearby board.
    # Mixed backgrounds, unreliable grids and uncalibrated legacy groups keep
    # their original route. Never choose a person's body width as a ruler.
    if len(contexts) < 3:
        return None
    groups = set(); pitches = {}
    for c in contexts:
        row = c['row']; semantic = c.get('semantic', {}); bg = c.get('background', {})
        pitch = bg.get('grid_pitch')
        if (row.get('route') != 'grid' or not semantic.get('near_wall')
                or semantic.get('confidence', 0) < .9 or not semantic.get('background_group')
                or pitch is None or not np.isfinite(pitch) or pitch <= 0):
            return None
        measured = bg.get('grid_measurement', {})
        if any(not 0 <= measured.get(axis, {}).get('spacing_error_fraction', float('inf')) <= .07
               for axis in ('vertical', 'horizontal')):
            return None
        groups.add(semantic['background_group']); pitches[row['asset_id']] = pitch
    if len(groups) != 1 or sum(c['measurement']['neutral'] for c in contexts) < 2:
        return None
    base = [pitches[aid]*plans[aid]['base_scale'] for aid in pitches]
    proposed = [pitches[aid]*plans[aid]['scale'] for aid in pitches]
    conflicting = [aid for aid in pitches if plans[aid]['status'] == 'calibrated'
                   and plans[aid].get('method') == 'multiple_body_segments'
                   and abs(plans[aid]['relative_scale']-1) > .02
                   and (plans[aid].get('body_background_disagreement') or 0) > .12]
    if not conflicting or spread(proposed) <= spread(base)+.03:
        return None
    # The median old image scale is a group gauge, not a ground-truth body size.
    # It minimizes disturbance to the group instead of inheriting either of
    # the conflicting neutral-reference gauges. One exact pitch for ALL photos.
    target = float(np.median(base))
    scales = {aid: target/pitch for aid, pitch in pitches.items()}
    record = {'version': VERSION, 'background_group': next(iter(groups)),
              'asset_ids': sorted(pitches), 'trigger_asset_ids': conflicting,
              'baseline_pitch_spread': spread(base), 'proposed_pitch_spread': spread(proposed),
              'target_grid_pitch': target, 'target_basis': 'median_baseline_grid_pitch',
              'expected_pitch_spread': spread([pitches[a]*s for a, s in scales.items()])}
    if any(not .8 <= scales[aid]/plans[aid]['base_scale'] <= 1.25 for aid in pitches):
        record['status'] = 'rejected_excessive_change'
        return record
    record['status'] = 'proposed'
    for aid, scale in scales.items():
        audit = plans[aid]
        audit['prior_decision'] = {k: copy.deepcopy(audit.get(k)) for k in
            ('status', 'reason', 'method', 'scale', 'relative_scale', 'body_background_disagreement')}
        audit.update(status='calibrated', reason='worsening_body_scales_replaced_by_common_grid',
                     method=VERSION, scale=scale, relative_scale=scale/audit['base_scale'],
                     requires_review=True, grid_common_scale={**record, 'input_grid_pitch': pitches[aid],
                                                             'applied': False})
        body = list(audit['body_votes'].values())
        disagreement = float(abs(np.median(body)/scale-1)) if body else None
        audit.update(body_background_disagreement=disagreement, body_selected_scale_disagreement=disagreement)
        audit['review_reasons'].append('physical_grid_used_after_body_scale_conflict')
    return record


def finalize(plans, pending):
    """A shared scale is adopted for the whole cohort or for none of it."""
    cohorts = {}
    for aid, audit in plans.items():
        if audit.get('grid_common_scale'):
            cohorts[tuple(audit['grid_common_scale']['asset_ids'])] = True
    for ids in cohorts:
        failures = [aid for aid in ids if aid not in pending or plans[aid]['status'] != 'calibrated']
        reasons = {aid: plans[aid]['reason'] for aid in failures}
        for aid in ids:
            audit = plans[aid]
            audit['grid_common_scale'].update(applied=not failures, coverage_failure_asset_ids=failures,
                                              coverage_failure_reasons=reasons)
            if failures:
                pending.pop(aid, None)
                audit.update(proposed_scale=audit.get('proposed_scale', audit['scale']),
                             scale=audit['base_scale'], relative_scale=1., status='retained_for_review',
                             reason='common_grid_group_coverage_failed', requires_review=True)


def refine_coverage(contexts, plans, pending, evaluate):
    """Try one shared zoom near the median; never optimize photos independently."""
    lookup = {c['row']['asset_id']: c for c in contexts}
    cohorts = {tuple(a['grid_common_scale']['asset_ids']) for a in plans.values() if a.get('grid_common_scale')}
    for ids in cohorts:
        if all(aid in pending for aid in ids):
            continue
        if any('bounds_aligned' not in plans[aid].get('boundary_measurement', {}) for aid in ids):
            continue
        target = plans[ids[0]]['grid_common_scale']['target_grid_pitch']
        attempts = []
        for zoom in (1.01, .99, 1.02, .98, 1.03, .97, 1.04, .96, 1.05, .95):
            trials = {}; rendered = {}; failures = {}
            for aid in ids:
                audit = copy.deepcopy(plans[aid]); common = audit['grid_common_scale']
                scale = target*zoom/common['input_grid_pitch']
                audit.update(scale=scale, relative_scale=scale/audit['base_scale'], status='calibrated',
                             reason='worsening_body_scales_replaced_by_common_grid')
                audit.pop('proposed_scale', None)
                common.update(initial_target_grid_pitch=target, target_grid_pitch=target*zoom, coverage_zoom=zoom)
                body = list(audit['body_votes'].values())
                disagreement = float(abs(np.median(body)/scale-1)) if body else None
                audit.update(body_background_disagreement=disagreement, body_selected_scale_disagreement=disagreement)
                try:
                    if not .8 <= audit['relative_scale'] <= 1.25:
                        raise ValueError('scale_conflict_or_excessive_change')
                    rendered[aid] = evaluate(lookup[aid], audit)
                    trials[aid] = audit
                except ValueError as error:
                    failures[aid] = str(error)
            attempts.append({'shared_zoom': zoom, 'failures': failures})
            if not failures:
                for aid in ids:
                    trials[aid]['grid_common_scale']['coverage_trials'] = attempts
                    # Keep the audit identity already attached to the source row.
                    plans[aid].clear(); plans[aid].update(trials[aid])
                    pending[aid] = rendered[aid]
                break
        else:
            for aid in ids:
                plans[aid]['grid_common_scale']['coverage_trials'] = attempts


def verify_cohorts(rows):
    selected = [r for r in rows if r.get('person_scale', {}).get('grid_common_scale', {}).get('applied')]
    lookup = {r['asset_id']: r for r in rows}; results = []
    done = set()
    for row in selected:
        audit = row['person_scale']; record = audit['grid_common_scale']
        ids = tuple(record['asset_ids'])
        if ids in done:
            continue
        done.add(ids); actual = []
        for aid in ids:
            a = lookup[aid]['person_scale']; common = a.get('grid_common_scale', {})
            if (a['status'] != 'calibrated' or not common.get('applied')
                    or common.get('target_grid_pitch') != record['target_grid_pitch']):
                raise ValueError('partial_common_grid_scale_application')
            pitch = common['input_grid_pitch']*lookup[aid]['frame']['uniform_scale']
            if abs(pitch/record['target_grid_pitch']-1) > 1e-8:
                raise ValueError('common_grid_scale_mismatch')
            actual.append(pitch)
        results.append({'asset_ids': list(ids), 'grid_pitch': record['target_grid_pitch'],
                        'actual_pitch_spread': spread(actual), 'applied_atomically': True})
    return results

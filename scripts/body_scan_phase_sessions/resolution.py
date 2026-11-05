"""Fuse complementary views without majority voting or guessing two timepoints."""
from collections import defaultdict

from scripts.body_scan_phase.policy import PHASES


def make_units(items, candidates, group_id):
    lookup = {r['asset_id']: r for r in items}; units = []; used = set()
    for index, candidate in enumerate(candidates, 1):
        candidate['candidate_id'] = f'{group_id}s{index:02d}'
        for aid in candidate['members']:
            lookup[aid]['candidate_session_id'] = candidate['candidate_id']
        if candidate['reliable'] and len(candidate['members']) > 1:
            unit = {'unit_id': candidate['candidate_id'], 'members': candidate['members'],
                    'membership': 'reviewed_session', 'session_evidence': candidate}
            units.append(unit); used.update(candidate['members'])
    for item in items:
        if item['asset_id'] not in used:
            units.append({'unit_id': f"{group_id}i-{item['asset_id']}", 'members': [item['asset_id']],
                          'membership': 'single_image'})
    for unit in units:
        for aid in unit['members']:
            lookup[aid]['session_id'] = unit['unit_id']
            lookup[aid]['session_membership'] = unit['membership']
    return units


def resolve(items, units, comparisons):
    lookup = {r['asset_id']: r for r in items}
    unit_of = {aid: u['unit_id'] for u in units for aid in u['members']}
    fixed = defaultdict(set); marker_ids = defaultdict(list); proposals = defaultdict(list)
    for row in items:
        if row['phase'] in PHASES:
            fixed[unit_of[row['asset_id']]].add(row['phase'])
            marker_ids[unit_of[row['asset_id']]].append(row['asset_id'])
    relations = defaultdict(list); vetoes = []
    for pair in comparisons:
        a, b = pair['asset_ids']; ua, ub = unit_of[a], unit_of[b]
        if ua == ub:
            pair['resolution'] = 'same_session_not_chronological_comparison'
            continue
        decision = pair['decision']
        if decision['after'] is None:
            pair['resolution'] = decision['reason']
            if decision['reason'] == 'observation_directions_conflict':
                vetoes.append({'unit_ids': sorted((ua,ub)), 'comparison_ids': [pair['pair_id']],
                               'views': [pair['view_family']], 'status': 'observation_directions_conflict'})
            continue
        after = a if decision['after'] == 'A' else b
        pair['after_asset_id'] = after
        pair['after_unit_id'] = unit_of[after]
        relations[tuple(sorted((ua, ub)))].append(pair)
    edges = list(vetoes)
    conflict_units = {unit for unit, phases in fixed.items() if len(phases) > 1}
    conflict_units.update(uid for edge in vetoes for uid in edge['unit_ids'])
    for key, pairs in sorted(relations.items()):
        directions = {p['after_unit_id'] for p in pairs}
        edge = {'unit_ids': list(key), 'comparison_ids': [p['pair_id'] for p in pairs],
                'views': sorted({p['view_family'] for p in pairs}), 'status': 'tentative'}
        if len(directions) > 1:
            edge['status'] = 'cross_view_conflict'
            conflict_units.update(key)
        else:
            after = next(iter(directions)); before = next(u for u in key if u != after)
            edge.update(after_unit=after, before_unit=before)
            if any(fixed[u] and fixed[u] != {phase} for u, phase in ((before, 'before'), (after, 'after'))):
                edge['status'] = 'reliable_marker_conflict'; conflict_units.update(key)
            elif any(p['decision']['strength'] == 'clear' for p in pairs):
                edge['status'] = 'accepted_single_clear'
            elif len(edge['views']) >= 2:
                edge['status'] = 'accepted_multi_view'
            if edge['status'].startswith('accepted'):
                for unit, phase in ((before, 'before'), (after, 'after')):
                    proposals[unit].append((phase, edge))
        for p in pairs:
            p['resolution'] = edge['status']
        edges.append(edge)
    for unit, values in proposals.items():
        if len({phase for phase, _ in values} | fixed[unit]) > 1:
            conflict_units.add(unit)
    # A conflict anywhere in a connected comparison component blocks automatic
    # inference for that component. A majority cannot erase contradictory views.
    changed = True
    while changed:
        previous = set(conflict_units)
        for edge in edges:
            if set(edge['unit_ids']) & conflict_units:
                conflict_units.update(edge['unit_ids'])
        changed = previous != conflict_units
    for edge in edges:
        if set(edge['unit_ids']) & conflict_units and edge['status'].startswith('accepted'):
            edge['status'] = 'connected_assignment_conflict'
            for pair in comparisons:
                if pair['pair_id'] in edge['comparison_ids']:
                    pair['resolution'] = edge['status']
    for unit in units:
        uid = unit['unit_id']; values = proposals[uid]
        sources = [edge for _, edge in values]
        desired = next(iter(fixed[uid])) if len(fixed[uid]) == 1 else values[0][0] if values else None
        blocked = uid in conflict_units
        unit.update(phase='unknown' if blocked or desired is None else desired,
                    status='needs_review' if blocked or desired is None else 'labeled',
                    reason='session_assignment_conflict' if blocked else 'no_accepted_phase_evidence' if desired is None else
                           'reliable_session_marker' if fixed[uid] else 'consistent_visual_evidence',
                    evidence={'marker_asset_ids': marker_ids[uid], 'relations': sources})
        for aid in unit['members']:
            row = lookup[aid]
            if row['phase'] in PHASES or row.get('blocked'):
                if blocked:
                    row['phase_warning'] = 'session_assignment_conflict'
                continue
            if blocked:
                row['reason'] = 'session_assignment_conflict'
                continue
            if desired is not None:
                pair_ids = sorted({pid for edge in sources for pid in edge['comparison_ids']})
                involved = [p for p in comparisons if p['pair_id'] in pair_ids]
                direct = any(aid in p['asset_ids'] for p in involved)
                directly_clear = any(aid in p['asset_ids'] and p['decision']['strength'] == 'clear' for p in involved)
                source = ('session_marker_propagation' if fixed[uid] else
                          'session_visual_propagation' if not direct else 'multi_view_observation' if
                          any(e['status'] == 'accepted_multi_view' for e in sources) else
                          'paired_clear_observation' if directly_clear else 'session_visual_propagation')
                row.update(phase=desired, status='labeled', phase_source=source,
                           confidence=min((p['decision']['confidence'] for p in involved), default=None),
                           reason=unit['reason'], evidence={'session_id': uid, **unit['evidence']})
            else:
                proposed = [e for e in edges if uid in e['unit_ids'] and e['status'] == 'tentative']
                choices = {'after' if e['after_unit'] == uid else 'before' for e in proposed}
                if len(choices) == 1:
                    row['suggestion'] = {'phase': next(iter(choices)), 'requires_review': True,
                                         'reason': 'single_subtle_view', 'relations': proposed}
                    row['reason'] = 'single_subtle_view'
    return edges

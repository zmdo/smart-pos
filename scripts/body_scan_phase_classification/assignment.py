"""Generation labels are separate from the unchanged scientific/visual analysis."""
import copy
import itertools

from scripts.body_scan_contracts.labels import PHASES, PHASE_NAMES, family, decorate

def candidates(group):
    result={aid:[] for aid in group['asset_ids']}
    for pair in group['comparisons']:
        decision=pair['fused_decision']; score=decision.get('confidence')
        if decision.get('after') not in ('A','B') or type(score) not in (int,float) or not 0<=score<=1:
            continue
        after=pair['asset_ids'][0 if decision['after']=='A' else 1]
        for aid in pair['asset_ids']:
            result[aid].append({'phase':'after' if aid==after else 'before','score':score,
                'source':'stable_pair','pair_id':pair['pair_id'],'reason':decision['reason']})
    return result


def initial(row, proposals):
    phase=row['phase']; kind='pending'; reason='highest_available_score'
    if phase in PHASES:
        kind='rule' if row['evidence_kind'] in ('source_rule','explicit_text') else 'inferred'
        reason='existing_analysis_assignment'
    elif row.get('suggestion',{}).get('phase') in PHASES:
        phase=row['suggestion']['phase'];kind='inferred';reason='existing_tentative_inference'
    return {'asset_id':row['asset_id'],'store':row['store'],'member':row['member'],'view':row['view'],
            'group_id':row['group_id'],'source_sha256':row['source_sha256'],
            'analysis_phase':row['phase'],'analysis_reason':row['reason'],'analysis_source':row['phase_source'],
            'phase':phase,'label_kind':kind,'assignment_reason':reason,'candidates':copy.deepcopy(proposals),
            'confidence':row.get('confidence') if phase in PHASES else None,
            'confidence_semantics':'model_self_reported_support_not_calibrated_probability',
            'review_flags':[row['phase_warning']] if row.get('phase_warning') else [],
            'human_review':None}


def units_for(group, rows):
    lookup={r['asset_id']:r for r in rows};used=set();units=[]
    for unit in group['strategies']['fused']['units']:
        members=[k for k in unit['members'] if k in lookup]
        locked={lookup[k]['phase'] for k in members if lookup[k]['phase'] in PHASES}
        if unit['membership']=='reviewed_session' and len(locked)<=1:
            units.append(members);used.update(members)
        elif len(locked)>1:
            for aid in members:lookup[aid]['review_flags'].append('inferred_labels_conflict_inside_session')
    units.extend([[r['asset_id']] for r in rows if r['asset_id'] not in used])
    return units


def required_ranking(group, original):
    proposals=candidates(group)
    rows=[initial(r,proposals[r['asset_id']]) for r in original]
    lookup={r['asset_id']:r for r in rows};required=[]
    for unit in units_for(group,rows):
        if not any(lookup[k]['phase'] in PHASES or lookup[k]['candidates'] for k in unit):
            required.extend(unit)
    return required


def assign(group, original, ranked=None):
    proposals=candidates(group);rows=[initial(r,proposals[r['asset_id']]) for r in original]
    lookup={r['asset_id']:r for r in rows};ranked=ranked or {}
    for row in rows:
        if row['asset_id'] in ranked:
            rank=ranked[row['asset_id']]
            if rank.get('after_score') is not None:
                for phase in PHASES:
                    row['candidates'].append({'phase':phase,'score':rank['after_score'] if phase=='after' else 1-rank['after_score'],
                        'source':'review_only_model_ranking','reason':rank['reason'],'order_gap':rank['order_gap']})
            else:
                row['review_flags'].append(rank.get('reason','ranking_unavailable'))
    units=units_for(group,rows);choices=[]
    for unit in units:
        fixed={lookup[k]['phase'] for k in unit if lookup[k]['phase'] in PHASES}
        choices.append(tuple(fixed) if fixed else PHASES)
    if len(units)>20:
        raise ValueError('too_many_generation_units')
    scores={}
    for row in rows:
        scores[row['asset_id']]={phase:max((c['score'] for c in row['candidates'] if c['phase']==phase),default=0.) for phase in PHASES}
    best=None;best_assignment=None;tie_count=0
    for values in itertools.product(*choices):
        by_id={aid:phase for unit,phase in zip(units,values) for aid in unit}
        coverage=0
        for view in ('front','side','back'):
            per_view=[r for r in rows if family(r['view'])==view]
            before={r['source_sha256'] for r in per_view if by_id[r['asset_id']]=='before'}
            after={r['source_sha256'] for r in per_view if by_id[r['asset_id']]=='after'}
            coverage+=int(any(a!=b for a in before for b in after))
        support=sum(scores[aid][phase] for aid,phase in by_id.items())
        objective=(coverage,round(support,8))
        if best is None or objective>best:
            best=objective;best_assignment=by_id;tie_count=1
        elif objective==best:
            tie_count+=1
    for unit in units:
        unit_candidates=[c for aid in unit for c in lookup[aid]['candidates']]
        unit_fixed=any(lookup[aid]['phase'] in PHASES for aid in unit)
        for aid in unit:
            row=lookup[aid]
            if row['phase'] not in PHASES:
                row['phase']=best_assignment[aid]
                supports=[c for c in row['candidates'] if c['phase']==row['phase']]
                inherited=[c for c in unit_candidates if c['phase']==row['phase']]
                row['confidence']=max((c['score'] for c in supports or inherited),default=None)
                if unit_fixed:
                    row['label_kind']='inferred';row['assignment_reason']='reliable_session_propagation'
                elif not unit_candidates:
                    row['assignment_reason']='no_directional_evidence_deterministic_placeholder'
                else:
                    row['assignment_reason']='highest_support_with_session_and_pair_constraints'
                if row['candidates'] and scores[aid][row['phase']]<max(scores[aid].values()):
                    row['review_flags'].append('paired_or_session_constraint_overrode_individual_maximum')
                if tie_count>1:
                    row['review_flags'].append('ranking_tie_deterministic_order_not_chronology')
            if row['confidence'] is None and row['label_kind']=='inferred':
                row['confidence']=max((c['score'] for c in row['candidates'] if c['phase']==row['phase']),default=None)
            decorate(row)
    return rows,{'objective':{'available_view_pairs':best[0],'support_sum':best[1]},'equally_ranked_assignments':tie_count,
                 'units':units,'policy':'Keep rules/inferences; maximize usable distinct pairs, then summed maximum phase support. Ties are provisional.'}

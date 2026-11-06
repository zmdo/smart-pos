"""Reports constrain interpretation; they never manufacture visual evidence."""
import copy

from .evidence import decision


def fuse(observation, reports):
    result = copy.deepcopy(observation)
    result['report_assistance'] = {'status': 'not_used', 'reason': 'no_report_for_member'}
    if not reports:
        return result
    if len(reports) != 1:
        result['report_assistance']['reason'] = 'multiple_reports_without_photo_stage_link'
        return result
    report = reports[0]; expected = report['expected_changes']
    audit = {'status': 'not_used', 'report_id': report['report_id'], 'expected': expected,
             'photo_batch_link': 'unverified', 'reason': 'no_matching_stable_visual_cue'}
    result['report_assistance'] = audit
    if expected['status'] != 'available' or observation['reason'] in (
            'identical_sources', 'model_response_unavailable', 'swapped_response_unavailable', 'observation_directions_conflict'):
        audit['reason'] = 'report_unusable_or_visual_evidence_blocked'; return result
    compatible = {}
    for name, phase in expected['directions'].items():
        value = observation.get('stable_cues', {}).get(name)
        if value:
            compatible[name] = {**value, 'image': value['image'] if phase == 'after' else {'A':'B','B':'A'}[value['image']]}
    if not compatible:
        return result
    # A report that omits muscle measurements does not invalidate a separately
    # reliable visual muscle cue. Preserve it as VISUAL evidence; only report
    # covered cues acquire a documented before/after polarity.
    combined = {**observation.get('stable_cues', {}), **compatible}
    conditioned = decision(combined)
    if conditioned['after'] is None or any(v['image'] != conditioned['after'] for v in compatible.values()):
        audit.update(status='conflict', reason='report_linked_cues_conflict')
        result.update(after=None, strength='none', reason='observation_directions_conflict'); return result
    # Do not promote subtle evidence, count report numbers as votes, or infer a
    # batch membership. The unchanged session resolver still applies afterwards.
    audit.update(status='compatible_inference', reason='report_pattern_matches_independent_visual_observation',
                 supporting_cues=sorted(compatible), visual_only_cues=sorted(set(combined)-set(compatible)),
                 verified_chronology=False)
    result.update(conditioned, reason='report_conditioned_visual_inference')
    return result

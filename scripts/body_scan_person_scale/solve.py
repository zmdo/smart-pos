"""One person-wide reference; one isotropic scale per image with auditable votes."""
import numpy as np

from .background import relative


def spread(values):
    return float(max(values)/min(values)-1) if values else None


def reference_template(contexts):
    refs = [c for c in contexts if c['measurement']['neutral']]
    if len(refs) < 2:
        raise ValueError('fewer_than_two_reliable_neutral_references')
    # Establish a common group gauge from neutral poses only; previous side compensation cannot bias it.
    samples = {k: [c['measurement']['lengths'][k]*c['row']['frame']['uniform_scale'] for c in refs
                   if k in c['measurement']['lengths']] for k in ('torso', 'thigh', 'shin')}
    template = {k: float(np.median(v)) for k, v in samples.items() if len(v) >= 2}
    if 'torso' not in template:
        raise ValueError('neutral_reference_segments_insufficient')
    targets = {}; rejected = []
    for c in refs:
        votes = {k: template[k]/value for k, value in c['measurement']['lengths'].items() if k in template}
        mid = float(np.median(list(votes.values())))
        consistent = {k: v for k, v in votes.items() if abs(v/mid-1) <= .06}
        if not consistent or ('torso' not in consistent and len(consistent) < 2):
            rejected.append(c['row']['asset_id']); continue
        targets[c['row']['asset_id']] = float(np.median(list(consistent.values())))
    refs = [c for c in refs if c['row']['asset_id'] in targets]
    if len(refs) < 2:
        raise ValueError('neutral_references_disagree')
    return refs, targets, {'reference_ids': list(targets), 'target_segment_pixels': template,
                          'neutral_target_scales': targets, 'rejected_reference_ids': rejected,
                          'scale_basis': 'neutral_segment_consensus; never body width or head size'}


def plan(contexts):
    refs, ref_scales, reference = reference_template(contexts)
    template = reference['target_segment_pixels']; output = {}
    for c in contexts:
        row = c['row']; aid = row['asset_id']; base = row['frame']['uniform_scale']
        body = {k: template[k]/v for k, v in c['measurement']['lengths'].items() if k in template}
        background = []; rejected = []
        for ref in refs:
            if ref is c:
                continue
            try:
                ratio, proof = relative(ref, c)
                background.append({'reference_id': ref['row']['asset_id'],
                    'scale': ref_scales[ref['row']['asset_id']]/ratio, **proof})
            except ValueError as error:
                rejected.append({'reference_id': ref['row']['asset_id'], 'reason': str(error)})
        audit = {'body_votes': body, 'background_votes': background, 'rejected_background_votes': rejected,
                 'base_scale': base, 'raised_arms': c['measurement']['raised_arms'], 'review_reasons': []}
        numeric = [v['scale'] for v in background]
        body_values = list(body.values())
        chosen = None; method = None
        if aid in ref_scales and numeric and spread(numeric+[ref_scales[aid]]) <= .08:
            # Use its independently measured neutral-body vote too. Omitting it
            # would make two references exchange their scale errors on reruns.
            chosen = float(np.median(numeric+[ref_scales[aid]])); method = 'neutral_body_and_background_consensus'
        elif len(numeric) >= 2 and spread(numeric) <= .08:
            chosen = float(np.median(numeric)); method = 'two_neutral_background_references'
        elif len(numeric) == 1 and body_values and abs(np.median(body_values)/numeric[0]-1) <= .08:
            chosen = float(numeric[0]); method = 'background_plus_body_crosscheck'
        elif len(body_values) >= 2 and spread(body_values) <= .08:
            chosen = float(np.median(body_values)); method = 'multiple_body_segments'
        if chosen is None:
            audit.update(status='retained_for_review', reason='insufficient_or_conflicting_scale_votes', scale=base)
        else:
            disagreement = float(abs(np.median(body_values)/chosen-1)) if body_values else None
            audit['body_background_disagreement'] = disagreement
            if disagreement is not None and disagreement > .05:
                audit['review_reasons'].append('segment_scale_difference_above_5_percent')
            # Independent gross conflict never gets averaged into a forced output.
            if (disagreement is not None and disagreement > .12) or not .8 <= chosen/base <= 1.25:
                audit.update(status='retained_for_review', reason='scale_conflict_or_excessive_change', scale=base)
            elif abs(chosen/base-1) <= .02 and not (c['measurement']['raised_arms'] and not row['frame'].get('group_scale')):
                audit.update(status='retained', reason='within_two_percent_deadband', scale=base, method=method)
            else:
                audit.update(status='calibrated', reason='consistent_scale_references', scale=chosen, method=method)
        audit['relative_scale'] = audit['scale']/base
        audit['neutral_torso_pixels'] = template['torso']
        output[aid] = audit
    return output, reference

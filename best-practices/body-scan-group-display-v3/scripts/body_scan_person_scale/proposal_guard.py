"""Veto a worsening proposal; background evidence never assigns a new scale."""
import copy

import numpy as np

VERSION = 'independent-scale-proposal-guard-v1'


def reliable_grid(context):
    semantic = context.get('semantic', {})
    background = context.get('background', {})
    pitch = background.get('grid_pitch')
    if (context['row'].get('route') != 'grid' or not semantic.get('near_wall')
            or semantic.get('confidence', 0) < .9 or not semantic.get('background_group')
            or pitch is None or not np.isfinite(pitch) or pitch <= 0):
        return False
    measured = background.get('grid_measurement', {})
    return all(0 <= measured.get(axis, {}).get('spacing_error_fraction', float('inf')) <= .07
               for axis in ('vertical', 'horizontal'))


def apply(contexts, plans):
    """Use unchanged peers as an uncertainty interval, not a common grid target.

    A reliable torso must dissent from the proposed change AND independent
    background evidence must show it moving farther away from stable peers.
    This only cancels an unsupported adjustment, retaining the input image.
    It cannot manufacture a smaller/larger replacement scale from the grid.
    """
    original = copy.deepcopy(plans)
    rejected = []
    for context in contexts:
        aid = context['row']['asset_id']; audit = plans[aid]; proposal = original[aid]
        if proposal['status'] != 'calibrated' or abs(proposal['relative_scale']-1) <= .02:
            continue
        if not reliable_grid(context) or not context['measurement']['neutral']:
            continue
        torso = context['measurement']['lengths'].get('torso')
        if torso is None or torso <= 0:
            continue
        peers = [c for c in contexts if c['row']['asset_id'] != aid and reliable_grid(c)
                 and c['semantic']['background_group'] == context['semantic']['background_group']
                 and original[c['row']['asset_id']]['status'] != 'calibrated']
        if len(peers) < 2:
            continue
        pitches = [c['background']['grid_pitch']*original[c['row']['asset_id']]['base_scale'] for c in peers]
        low, high = min(pitches), max(pitches)
        if high/low > 1.20:
            continue
        middle = float(np.median(pitches))
        distance = lambda value: max(low-value, value-high, 0.)/middle
        base = proposal['base_scale']; scale = proposal['scale']
        target = proposal['neutral_torso_pixels']; pitch = context['background']['grid_pitch']
        body_before = abs(torso*base/target-1); body_after = abs(torso*scale/target-1)
        background_before = distance(pitch*base); background_after = distance(pitch*scale)
        record = {'version': VERSION, 'status': 'observed',
                  'peer_asset_ids': [c['row']['asset_id'] for c in peers],
                  'peer_pitch_interval': [low, high], 'background_is_soft_evidence': True,
                  'torso_error_before': body_before, 'torso_error_after': body_after,
                  'background_distance_before': background_before, 'background_distance_after': background_after}
        audit['proposal_guard'] = record
        if (body_before <= .03 and body_after > body_before+.05
                and background_after > max(.08, background_before+.02)):
            record['status'] = 'rejected_worsening_proposal'
            record['proposed_scale'] = scale
            audit.update(status='retained_for_review', reason='independent_evidence_rejects_worsening_scale',
                         proposed_scale=scale, scale=base, relative_scale=1., requires_review=True)
            audit['review_reasons'].append('conflicting_scale_proposal_cancelled_without_new_numeric_estimate')
            rejected.append(aid)
    return {'version': VERSION, 'rejected_asset_ids': rejected,
            'policy': 'veto_only; stable_peers_unchanged; no_common_grid_target'}

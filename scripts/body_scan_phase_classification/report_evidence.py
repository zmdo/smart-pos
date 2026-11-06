"""Interpret verified report changes only inside phase classification."""

def expected_changes(report):
    """Do not equate lower weight with better; use documented independent fields."""
    if not report or report.get('status') != 'verified_transcription' or report.get('date_issue'):
        return {'status': 'unavailable', 'reason': 'report_or_dates_unverified', 'directions': {}}
    metrics = report['metrics']; directions = {}; evidence = {}
    signs = []
    for key in ('fat', 'waist'):
        metric = metrics.get(key)
        if metric and metric['usable'] and abs(metric['computed_delta'][0]) >= .1:
            signs.append(1 if metric['computed_delta'][0] < 0 else -1)
            evidence[key] = metric['computed_delta']
    if len(signs) == 2 and len(set(signs)) == 1:
        # Only waist_shape relates to waist and body-fat fields. Thigh width is
        # not inferred from waist/weight; arm/chest circumferences aren't muscle.
        directions['waist_shape'] = 'after' if signs[0] == 1 else 'before'
    muscle = metrics.get('muscle')
    if muscle and muscle['usable'] and abs(muscle['computed_delta'][0]) >= .1:
        for key in ('upper_muscle','lower_muscle'):
            directions[key] = 'after' if muscle['computed_delta'][0] > 0 else 'before'
        evidence['muscle'] = muscle['computed_delta']
    return {'status': 'available' if directions else 'unavailable', 'directions': directions, 'evidence': evidence,
            'reason': 'documented_changes_only' if directions else 'missing_or_conflicting_independent_metrics',
            'not_independent_votes': ['weight_and_bmi', 'original_and_its_crops'],
            'photo_batch_link': 'unverified'}


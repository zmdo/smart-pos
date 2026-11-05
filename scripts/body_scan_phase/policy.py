"""User ordering policy. These labels are not verified capture chronology."""
import re

PHASES = ('before', 'after')
RULE = 'left_before_right_after-v1'


def text_phase(text):
    if not isinstance(text, str):
        return 'unknown'
    if re.search(r'(训练|减脂|调整|改善)前[与和/、\s]*后', text):
        return 'unknown'
    before = re.search(r'训练前|减脂前|调整前|改善前|\bbefore\b', text, re.I)
    after = re.search(r'训练后|减脂后|调整后|改善后|\bafter\b', text, re.I)
    return ('before' if before else 'after') if bool(before) != bool(after) else 'unknown'


def panel_phase(layout, index, panel):
    """Called only after verified, ordered two-panel splitting."""
    observed = text_phase(panel.get('label_text'))
    if layout == 'left_right' and index in (1, 2):
        phase = PHASES[index-1]
        return phase, {'source': 'comparison_position_rule', 'policy': RULE,
                       'position': 'left' if index == 1 else 'right',
                       'label_text': panel.get('label_text', ''), 'observed_phase': observed,
                       'marker_conflict': observed not in ('unknown', phase),
                       'verified_chronology': False}
    if observed in PHASES:
        return observed, {'source': 'explicit_marker', 'label_text': panel['label_text'],
                          'verified_chronology': False}
    return 'unknown', {'source': 'unresolved', 'verified_chronology': False}

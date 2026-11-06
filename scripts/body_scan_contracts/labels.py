"""Pure label formatting: no inference, model calls or assignment."""
PHASES = ('before','after')
PHASE_NAMES = {'before':'训练前','after':'训练后'}


def family(view):
    return 'side' if view.startswith('side') else view


def decorate(row):
    badge = {'inferred':'（推断）','pending':'（待审）'}.get(row['label_kind'],'')
    row['label'] = PHASE_NAMES[row['phase']]+badge
    row['requires_review'] = row['label_kind'] in ('inferred','pending') or bool(row.get('review_flags'))
    return row


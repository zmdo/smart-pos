"""Select the approved nine display metrics without modifying source data."""

DISPLAY_POLICY = 'core_nine_available_rows_fixed_height_v1'
CORE_METRICS = (
    ('date', '时间'), ('height', '身高'), ('weight', '体重'),
    ('fat_percent', '体脂率'), ('bmi', 'BMI'), ('waist', '腰围'),
    ('hip', '臀围'), ('chest', '胸围'), ('arm', '臂围'),
)
EMPTY_VALUES = {'', '—', '--', '-', '未提供', '未测', '缺失'}


def has_value(value):
    return value is not None and str(value).strip() not in EMPTY_VALUES


def select_display_rows(rows):
    by_key = {}
    labels = {label: key for key, label in CORE_METRICS}
    allowed = set(labels.values())
    for row in rows:
        key = row.get('key') or labels.get(row.get('type'))
        if key not in allowed:
            continue
        if key in by_key:
            raise ValueError('duplicate_display_metric:' + key)
        if has_value(row.get('before')) or has_value(row.get('after')):
            by_key[key] = row
    return [by_key[key] for key, _ in CORE_METRICS if key in by_key]

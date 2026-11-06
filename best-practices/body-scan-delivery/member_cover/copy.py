"""Evidence-based cover copy with explicit user overrides."""
import re
from datetime import date

FIELDS = {'title':12, 'subtitle':36, 'headline':40, 'story':280,
          'coach':40, 'address':70, 'brand_name':35}


def metric(report, key):
    value = (report or {}).get('metrics', {}).get(key, {})
    if not value.get('usable'):
        return None
    a, b = value.get('before_values', []), value.get('after_values', [])
    if len(a) != 1 or len(b) != 1 or value.get('computed_delta') != [round(b[0]-a[0], 4)]:
        return None
    return {'before':a[0], 'after':b[0], 'delta':round(b[0]-a[0], 4),
            'unit':value['unit'], 'source_row':value.get('source_row'), 'page':value.get('page')}


def compose(member, nickname, report, coach=None, overrides=None):
    overrides = overrides or {}
    if set(overrides)-set(FIELDS)-{'highlights'}:
        raise ValueError('unknown_cover_copy_field')
    for key, value in overrides.items():
        if key in FIELDS and (not isinstance(value, str) or len(value) > FIELDS[key]
                              or key in ('title','subtitle','headline','story') and not value.strip()):
            raise ValueError('invalid_cover_copy_'+key)
    coach = overrides.get('coach', coach)
    facts = {key:metric(report, key) for key in ('weight','fat','waist','hip')}
    w, f, waist = (facts[k] for k in ('weight','fat','waist'))
    num = lambda v: f'{v:g}'
    subtitle = '记录每个阶段的自己'
    duration = None
    if report and not report.get('date_issue'):
        try:
            elapsed = (date.fromisoformat(report['after_date'])-date.fromisoformat(report['before_date'])).days
            if elapsed > 0 and elapsed == report.get('stated_days') and 'stated_duration_differs_from_dates' not in report.get('warnings', []):
                duration = elapsed
                subtitle = f'记录 {elapsed} 天的改变'
        except (KeyError, ValueError, TypeError):
            pass
    if w and w['delta'] < 0:
        title, headline = '蜕变正发生', f'成功减重 {num(-w["delta"]*2)} 斤'
    elif f and f['delta'] < 0:
        title, headline = '重塑好状态', f'体脂率下降 {num(-f["delta"])} 个百分点'
    elif waist and waist['delta'] < 0:
        title, headline = '改变看得见', f'腰围减少 {num(-waist["delta"])} cm'
    else:
        title, headline = '每一步都算数', '把改变，留在镜头里'
    segments = [{'text':'每一次记录，都是重新认识自己的起点。', 'emphasis':False}]
    if coach:
        segments.append({'text':f'在 {coach} 教练的陪伴下，{nickname}把阶段变化留在了这份训练记录里。', 'emphasis':True})
    else:
        segments.append({'text':f'对{nickname}来说，从起点到下一次记录，一张照片、一次复测，都能让抽象的目标变得具体。', 'emphasis':False})
    lines = []
    for key, label, unit in (('weight','体重','kg'), ('fat','体脂率','%'), ('waist','腰围','cm')):
        value = facts[key]
        if value:
            lines.append(f'{label}从 {num(value["before"])}{unit} 到 {num(value["after"])}{unit}')
    if lines:
        segments.append({'text':'；'.join(lines)+'。', 'emphasis':True})
        segments.append({'text':'数字勾勒出变化的轨迹，镜头留下当下的模样。让每一份坚持都有迹可循，把每个阶段都变成值得回看的成长记录。', 'emphasis':False})
    else:
        segments.append({'text':'两张正面体测照，留下不同阶段的自己。把关注放回当下，用记录代替想象，让每一次回看都成为继续向前的起点。', 'emphasis':False})
    if 'story' in overrides:
        highlights = overrides.get('highlights', [])
        if not isinstance(highlights, list) or any(not isinstance(s,str) or not s or len(s)>80 for s in highlights):
            raise ValueError('invalid_highlights')
        parts = re.split('('+'|'.join(re.escape(s) for s in highlights)+')', overrides['story']) if highlights else [overrides['story']]
        segments = [{'text':s, 'emphasis':s in highlights} for s in parts if s]
    result = {'title':title, 'subtitle':subtitle, 'headline':headline,
              'story':''.join(s['text'] for s in segments), 'segments':segments, 'coach':coach,
              'facts':facts, 'duration_days':duration, 'report_id':report['report_id'] if report else None,
              'copy_origin':'user_override' if overrides else 'report_based_editorial',
              'user_overrides':list(overrides), 'personal_history_invented':False}
    for key in ('title','subtitle','headline','address','brand_name'):
        if key in overrides:
            result[key] = overrides[key]
    return result

"""Presentation configuration and report cells, without OCR or phase inference."""
import copy
import math
import re
from pathlib import Path

from scripts.body_scan_contracts.io import read, bind, sha

METRICS = {'waist':'腰围', 'hip':'臀围', 'arm':'臂围', 'chest':'胸围', 'weight':'体重', 'fat':'体脂率'}
COMPOUND_SURNAMES = ('欧阳','司马','上官','诸葛','夏侯','东方','皇甫','尉迟','公孙','慕容','司徒','司空')


def load_presentation(path, bindings):
    config = read(bind(path, bindings)) if path else {}
    base = Path(path).resolve().parent if path else Path.cwd()
    width = config.get('width', 1080)
    if type(width) is not int or not 540 <= width <= 4320:
        raise ValueError('presentation_width_must_be_540_to_4320')
    metrics = config.get('metrics', ['waist','hip','arm'])
    if not isinstance(metrics,list) or not 1 <= len(metrics) <= 6 or len(set(metrics)) != len(metrics) or set(metrics)-METRICS.keys():
        raise ValueError('invalid_presentation_metrics')
    for key in ('stores','members'):
        if not isinstance(config.get(key,{}),dict):raise ValueError('invalid_presentation_'+key)
    config = copy.deepcopy(config)
    config.update(width=width, metrics=metrics)
    config.pop('logo_path',None);config.pop('logo_sha256',None)
    if config.get('image_root'):
        root = (base/config['image_root']).resolve()
        folders = [p for p in root.iterdir() if p.is_dir() and p.name.lower()=='logo']
        if len(folders)>1:raise ValueError('multiple_logo_directories')
        logo_dir = folders[0] if folders else root/'logo'
        candidates = sorted(p for p in logo_dir.rglob('*') if p.is_file() and p.suffix.lower() in ('.png','.jpg','.jpeg','.webp'))
        if config.get('logo_file'):
            chosen = (logo_dir/config['logo_file']).resolve()
            if not chosen.is_relative_to(logo_dir.resolve()) or not chosen.is_file():raise ValueError('invalid_logo_file')
        else:
            if len(candidates)>1:raise ValueError('multiple_logos_select_logo_file')
            chosen = candidates[0] if candidates else None
        if chosen:
            config['logo_path']=str(bind(chosen,bindings));config['logo_sha256']=sha(chosen)
    elif config.get('logo_file'):
        raise ValueError('logo_requires_image_root')
    return config


def nickname(member, profile):
    surname = profile.get('surname') or next((s for s in COMPOUND_SURNAMES if member.startswith(s)),member[:1])
    honorific = profile.get('honorific')
    if honorific is not None and honorific not in ('先生','女士','会员'):
        raise ValueError('invalid_member_honorific')
    if not honorific:honorific = {'男':'先生','女':'女士'}.get(profile.get('gender'),'会员')
    if not re.fullmatch(r'[\u3400-\u9fff]+',member) and not profile.get('surname'):
        surname = member
    return surname+honorific


def metric_display(key, report):
    value = {'key':key,'name':METRICS[key],'available':False,'text':METRICS[key]+'：未提供'}
    metric = (report or {}).get('metrics',{}).get(key,{})
    if not metric.get('usable'):return value
    before,after = metric.get('before_values',[]),metric.get('after_values',[])
    if (not before or len(before)!=len(after) or len(before)>2 or
        any(type(v) not in (int,float) or not math.isfinite(v) for v in before+after)):
        return value
    deltas = [round(b-a,4) for a,b in zip(before,after)]
    if metric.get('computed_delta') != deltas:return value
    unit = metric.get('delta_unit',metric.get('unit'))
    expected = 'kg' if key=='weight' else 'percentage_points' if key=='fat' else 'cm'
    if unit!=expected:return value
    def number(v):return ('+' if v>0 else '')+f'{v:g}'
    # Preserve both values in metadata. Only collapse an identical bilateral change.
    shown = deltas[:1] if len(set(deltas))==1 else deltas
    value.update(available=True,before=before,after=after,delta=deltas,unit=unit,
                 text=METRICS[key]+'：'+'/'.join(map(number,shown))+('个百分点' if key=='fat' else unit),
                 report_id=report['report_id'],source=report['source'],source_sha256=report['source_sha256'],
                 row_label=metric.get('row_label'),page=metric.get('page'),
                 bilateral=len(deltas)==2)
    return value


def resolve(product, config=None, reports=None):
    config = config or {};reports=reports or []
    store,member = product['store'],product['member']
    profile = config.get('members',{}).get(store+'/'+member,{})
    store_config = config.get('stores',{}).get(store,{})
    candidates = [r for r in reports if (r.get('store'),r.get('member'))==(store,member)
                  and r.get('status')=='verified_transcription' and not r.get('date_issue')]
    if profile.get('report_id'):candidates=[r for r in candidates if r['report_id']==profile['report_id']]
    report = candidates[0] if len(candidates)==1 else None
    merged_profile = {**({'gender':report['gender']} if report and report.get('gender') in ('男','女') else {}),**profile}
    metrics = [metric_display(k,report) for k in config.get('metrics',['waist','hip','arm'])]
    address = profile.get('address') or store_config.get('address') or config.get('address') or store
    warnings=[]
    if not config.get('logo_path'):warnings.append('logo_missing_text_placeholder')
    if not (profile.get('honorific') or merged_profile.get('gender')):warnings.append('honorific_missing_neutral_member')
    if address==store:warnings.append('address_missing_store_only')
    if report is None:warnings.append('report_ambiguous' if len(candidates)>1 else 'verified_report_missing')
    if any(not m['available'] for m in metrics):warnings.append('some_measurements_unavailable')
    return {'width':config.get('width',1080),'logo_path':config.get('logo_path'),
            'logo_sha256':config.get('logo_sha256'),'brand_name':config.get('brand_name','LOGO'),
            'nickname':nickname(member,merged_profile),'address':address,'metrics':metrics,
            'consent_text':config.get('consent_text',''),
            'report_id':report['report_id'] if report else None,
            'before_date':report.get('before_date') if report else None,
            'after_date':report.get('after_date') if report else None,
            'photo_batch_link':report.get('photo_batch_link','unverified') if report else 'unverified',
            'warnings':warnings}


def public_presentation(context):
    return {k:v for k,v in context.items() if k!='logo_path'}

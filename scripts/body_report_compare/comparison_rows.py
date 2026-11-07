"""Original readings first; summary cells only fill gaps; every delta is computed."""
import re
from collections import defaultdict
from datetime import date
from decimal import Decimal
from .table_data import canonical, cell_number, fmt, metric_key, LABELS, valid_date

ORDER=['height','weight','skeletal_muscle','fat_mass','fat_percent','bmi','waist','hip','chest','arm',
       '大腿围','小腿围','腿围','whr','water','lean_mass','bmr','visceral','muscle']
DEFAULT_UNITS={'height':'cm','weight':'kg','skeletal_muscle':'kg','fat_mass':'kg','fat_percent':'%',
               'bmi':'kg/m²','waist':'cm','hip':'cm','chest':'cm','arm':'cm','大腿围':'cm','小腿围':'cm','腿围':'cm'}

def unit_for(key,unit):
    if key=='bmi':return 'kg/m²'
    return unit or DEFAULT_UNITS.get(key,'')

def summary_value(value,unit,key):
    unit=unit_for(key,unit)
    n=cell_number(value,unit)
    if n is not None:
        n,u=canonical(fmt(n),unit)
        return {'components':{'value':n},'unit':u,'text':fmt(n),'ordered_only':False}
    # Explicit L/R measurements can repeat for thigh/calf; preserve named components.
    s=value.replace('：',':').replace('−','-')
    pattern=r'(大腿|小腿)?\s*:?\s*([LlRr左右])\s*:?\s*([+-]?\d+(?:\.\d+)?)\s*(cm|kg|厘米|公斤)?'
    found=list(re.finditer(pattern,s))
    components={};section=''
    if found and len(re.findall(r'\d+(?:\.\d+)?',s))==len(found):
        units=set()
        for m in found:
            section=m[1] or section;side='左' if m[2].lower() in ('l','左') else '右';label=section+side
            if label in components:return None
            n,u=canonical(m[3],m[4] or unit);units.add(u);components[label]=n
        if len(units)==1:return {'components':components,'unit':units.pop(),'text':value,'ordered_only':False}
    parts=re.split(r'[/／]',s)
    if 1<len(parts)<=2:
        values=[cell_number(p,unit) for p in parts]
        if all(n is not None for n in values):
            return {'components':{f'第{i+1}项':canonical(fmt(n),unit)[0] for i,n in enumerate(values)},
                    'unit':canonical('1',unit)[1],'text':value,'ordered_only':True}
    return None

def original_value(record,key):
    if not record:return None
    metrics=[m for m in record['metrics'] if m['key']==key]
    if len(metrics)!=1 or not metrics[0]['usable']:return None
    m=metrics[0];n=Decimal(m['canonical_value'])
    return {'components':{'value':n},'unit':unit_for(key,m['canonical_unit']),'text':fmt(n),
            'ordered_only':False,'source_id':record['source_id'],'source_sha256':record['source_sha256'],
            'source_kind':'measurement','raw_value':m['value'],'raw_unit':m['unit'],'evidence':m['evidence']}

def summary_reading(table,row,side,key):
    if not row or not row[side]:return None
    value=summary_value(row[side],row['unit'],key)
    if value is None:return None
    return {**value,'source_id':table['source_id'],'source_sha256':table['source_sha256'],
            'source_kind':'summary','raw_value':row[side],'raw_unit':row['unit'],'evidence':row['evidence']}

def export_reading(reading):
    if reading is None:return None
    return {**reading,'components':{k:fmt(v) for k,v in reading['components'].items()}}

def rebuild_rows(before,after,table,pair,as_of):
    """Use matched original dates/readings, preserve raw summary only as provenance."""
    rows=[];corrections=[];skipped=[];warnings=[]
    before_day=valid_date(pair['before_date'],as_of) if pair else valid_date(table.get('before_date'),as_of) if table else None
    after_day=valid_date(pair['after_date'],as_of) if pair else valid_date(table.get('after_date'),as_of) if table else None
    if before_day and after_day and before_day<=after_day:
        days=(date.fromisoformat(after_day)-date.fromisoformat(before_day)).days
        rows.append({'type':'时间','key':'date','before':before_day,'after':after_day,'delta':str(days),'computed_delta':str(days),
          'unit':'天','origin':'computed','value_source_kind':'dates','warnings':[],
          'sources':{'before':{'source_id':before['source_id'] if before and before['measurement_date']==before_day else table['source_id'] if table else None},
                     'after':{'source_id':after['source_id'] if after and after['measurement_date']==after_day else table['source_id'] if table else None}},
          'delta_semantics':'elapsed_calendar_days_after_minus_before'})
    else:
        days=None;warnings.append('缺少有效前后日期，未填造日期或间隔天数')
    if table:
        for r in table['rows']:
            if r['type'] in ('时间','日期','测试日期'):
                corrections.append({'type':'时间','source_id':table['source_id'],
                    'original':{k:r[k] for k in ('before','after','delta','unit')},
                    'resolved':{'before':before_day,'after':after_day,'delta':days,'unit':'天'},
                    'reason':'原始报告日期优先；天数按有效日期相减'})
    summaries=defaultdict(list)
    if table:
        for r in table['rows']:
            if r['type'] not in ('时间','日期','测试日期'):summaries[metric_key(r['type'])].append(r)
    keys=set(summaries)
    for rec in (before,after):
        if rec:keys.update(m['key'] for m in rec['metrics'])
    for key in sorted(keys,key=lambda k:(ORDER.index(k) if k in ORDER else 100,k)):
        candidates=summaries[key];r=candidates[0] if len(candidates)==1 else None
        raw_b=summary_reading(table,r,'before',key) if table else None
        raw_a=summary_reading(table,r,'after',key) if table else None
        b=original_value(before,key) or raw_b;a=original_value(after,key) or raw_a
        if not b and not a:
            skipped.append(key+': 两侧数值缺失、重复或无法可靠解析');continue
        issues=[];delta='';label=LABELS.get(key,r['type'] if r else key)
        for side,current,old in [('before',b,raw_b),('after',a,raw_a)]:
            if current and old and current['source_kind']=='measurement' and (
                    current['components']!=old['components'] or current['unit']!=old['unit']):
                corrections.append({'type':label,'side':side,'original_summary':export_reading(old),
                                    'resolved':export_reading(current),'reason':'采用原始体测报告实测值'})
        if b and a and b['unit']==a['unit'] and set(b['components'])==set(a['components']):
            changes={k:a['components'][k]-b['components'][k] for k in b['components']}
            delta=fmt(changes['value'],True) if set(changes)=={'value'} else '；'.join(k+':'+fmt(v,True) for k,v in changes.items())
        else:issues.append('两侧数值或单位不完整，变化量留空')
        if (b and b['ordered_only']) or (a and a['ordered_only']):issues.append('双项按原表顺序比对，未推断左右')
        if (b and b['source_kind']=='summary') or (a and a['source_kind']=='summary'):
            if r and r['warnings']:issues.append('补充指标的原表存在识别或填写疑点，需核对')
        kind='original' if b and a and b['source_kind']==a['source_kind']=='measurement' else 'summary_supplement'
        row={'type':label,'key':key,'before':b['text'] if b else '', 'after':a['text'] if a else '',
             'delta':delta,'computed_delta':delta or None,'unit':(b or a)['unit'] or '—',
             'origin':'computed','value_source_kind':kind,'warnings':issues,
             'sources':{'before':export_reading(b),'after':export_reading(a)},
             'delta_semantics':'percentage_points' if (b or a)['unit']=='%' else 'after_minus_before'}
        if r:row['original_summary_cells']={k:r[k] for k in ('before','after','delta','unit')}
        rows.append(row)
    if not any(r['key']!='date' for r in rows):rows=[]
    return rows,corrections,skipped,warnings

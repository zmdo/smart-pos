"""Five-column report data; deterministic arithmetic, pairing and provenance."""
import re
from collections import defaultdict
from datetime import date, datetime
from zoneinfo import ZoneInfo
from decimal import Decimal, InvalidOperation

SCHEMA = 'body-report-five-column-v1'
HEADERS = ['类型', '初始数据（训练前）', '阶段数据（训练后）', '变化量（+/-）', '单位']
ALIASES = {'身体质量指数':'bmi','BMI':'bmi','体质指数':'bmi','体重':'weight','身高':'height',
 '骨骼肌':'skeletal_muscle','骨骼肌量':'skeletal_muscle','体脂肪':'fat_mass','体脂肪量':'fat_mass',
 '体脂率':'fat_percent','体脂百分比':'fat_percent','腰臀比':'whr','身体水分含量':'water',
 '去脂体重':'lean_mass','基础代谢':'bmr','基础代谢率':'bmr','内脏脂肪等级':'visceral',
 '腰围':'waist','臀围':'hip','胸围':'chest','臂围':'arm','肌肉量':'muscle'}
LABELS = {'bmi':'BMI','weight':'体重','height':'身高','skeletal_muscle':'骨骼肌量','fat_mass':'体脂肪量',
 'fat_percent':'体脂率','whr':'腰臀比','water':'身体水分含量','lean_mass':'去脂体重','bmr':'基础代谢',
 'visceral':'内脏脂肪等级','waist':'腰围','hip':'臀围','chest':'胸围','arm':'臂围','muscle':'肌肉量'}

def text(v):
    return v.strip() if isinstance(v, str) else ''

def number(v):
    s = text(v).replace('−','-').replace('＋','+').replace('，',',')
    if ',' in s:
        if not re.fullmatch(r'[+-]?\d{1,3}(?:,\d{3})+(?:\.\d+)?',s):return None
        s=s.replace(',','')
    if not re.fullmatch(r'[+-]?\d+(?:\.\d+)?',s): return None
    try:
        d = Decimal(s)
        return d if d.is_finite() else None
    except InvalidOperation: return None

def cell_number(value, unit):
    direct=number(value)
    if direct is not None:return direct
    matched=re.fullmatch(r'([+-]?\d+(?:\.\d+)?)\s*(kg|g|cm|mm|m|%|公斤|千克|厘米|毫米|米|斤|千卡)',text(value).replace('−','-'),re.I)
    if not matched:return None
    n,u=canonical(matched[1],matched[2]);_,expected=canonical('1',unit)
    if u!=expected:return None
    # Return values in the row's declared unit, without changing the raw cell.
    factor,_=canonical('1',unit)
    return n/factor if factor else None

def fmt(v, signed=False):
    s = format(v.normalize(),'f')
    return '+'+s if signed and v > 0 else s

def metric_key(label):
    clean = re.sub(r'\s+','',label)
    return ALIASES.get(clean, clean)

def canonical(value, unit):
    n=number(value); u=text(unit).lower().replace('㎏','kg').replace('％','%')
    aliases={'公斤':'kg','千克':'kg','厘米':'cm','毫米':'mm','米':'m','斤':'jin','克':'g','千卡':'kcal',
             '无':'','无量纲':'','—':'','-':''}
    u=aliases.get(u,u)
    if n is None:return None,u
    factor,target={'g':(Decimal('.001'),'kg'),'jin':(Decimal('.5'),'kg'),
                   'm':(Decimal('100'),'cm'),'mm':(Decimal('.1'),'cm')}.get(u,(Decimal(1),u))
    return n*factor,target

def today_cn():
    return datetime.now(ZoneInfo('Asia/Shanghai')).date()

def valid_date(value,as_of=None):
    as_of=as_of or today_cn()
    try:
        if not isinstance(value,str) or not re.fullmatch(r'20\d{2}-\d{2}-\d{2}',value):return None
        day=date.fromisoformat(value)
        return day.isoformat() if day<=as_of else None
    except (ValueError,TypeError):return None

def date_from_text(value,as_of=None):
    # Parse the actual cell, never extract a valid-looking year from 20266.
    compact=re.sub(r'\s+','',text(value))
    found=re.findall(r'(?<!\d)(20\d{2})[年./-](\d{1,2})[月./-](\d{1,2})(?:日)?(?!\d)',compact)
    if len(found)!=1:return None
    y,m,d=map(int,found[0])
    return valid_date(f'{y:04d}-{m:02d}-{d:02d}',as_of)

def normalize(raw, source, as_of=None):
    if not isinstance(raw,dict): raise ValueError('invalid_transcription')
    kind=raw.get('kind')
    if kind not in ('comparison_table','measurement','other'):raise ValueError('unknown_report_kind')
    rec={**source,'kind':kind,'printed_member':text(raw.get('member')),'printed_store':text(raw.get('store')),
         'warnings':[text(x) for x in raw.get('issues',[]) if text(x)],'rows':[], 'metrics':[],
         'measurement_date':valid_date(raw.get('measurement_date'),as_of),
         'before_date':valid_date(raw.get('before_date'),as_of),'after_date':valid_date(raw.get('after_date'),as_of),
         'date_evidence':text(raw.get('date_evidence')),'identity_ok':True}
    rec['raw_dates']={k:raw.get(k) for k in ('measurement_date','before_date','after_date')}
    rec['date_rejections']=[{'field':k,'value':raw.get(k),'reason':'日期须为有效的20xx年日期，且不得晚于处理日期'} for k in rec['raw_dates'] if raw.get(k) and not rec.get(k)]
    # User rule: report identity is authoritative; directory remains the grouping key.
    name=rec['printed_member']; expected=source['member']
    if name and name not in expected and expected not in name:
        rec['warnings'].append('目录名与报告会员姓名不同，按原目录分组并保留报告姓名供核对')
    printed_store=re.sub(r'\s+','',rec['printed_store'])
    if printed_store and '店' in printed_store and source['store'] not in printed_store:
        rec['warnings'].append('报告门店与目录不同：展示以报告为准，目录保留供查找')
    if kind=='comparison_table':
        columns=raw.get('columns',{})
        if '训练前' not in text(columns.get('before')) or '训练后' not in text(columns.get('after')):
            rec['warnings'].append('缺少明确的训练前后列头');rec['identity_ok']=False
        rec['columns']=columns
        for i,r in enumerate(raw.get('rows',[])):
            if not isinstance(r,dict) or not text(r.get('type')):continue
            row={k:text(r.get(k)) for k in ('type','before','after','delta','unit')}
            row.update(row_id=i+1,source_id=source['source_id'],origin='transcribed',warnings=[],
                       evidence=text(r.get('evidence')))
            if not row['before'] and not row['after']:continue
            if r.get('uncertain') or not row['before'] or not row['after']:
                row['warnings'].append('原表单元格缺失或识别待核对')
            b,a=cell_number(row['before'],row['unit']),cell_number(row['after'],row['unit'])
            row['computed_delta']=fmt(a-b,True) if b is not None and a is not None else None
            declared=cell_number(row['delta'],row['unit'])
            if declared is not None and row['computed_delta'] is not None and abs(declared-(a-b))>Decimal('.011'):
                row['warnings'].append('原填变化量与后减前不一致，保留原填值')
            rec['rows'].append(row)
        date_rows=[r for r in rec['rows'] if r['type'] in ('时间','日期','测试日期')]
        if len(date_rows)==1:
            for side in ('before','after'):
                cell=date_rows[0][side];field=side+'_date'
                rec[field]=date_from_text(cell,as_of)
                if cell and not rec[field]:rec['date_rejections'].append({'field':field,'value':cell,'reason':'原始日期单元格不合法或晚于处理日'})
        if not rec['rows']:rec['warnings'].append('未识别到可用表格行')
    elif kind=='measurement':
        for r in raw.get('metrics',[]):
            if not isinstance(r,dict) or not text(r.get('type')):continue
            value=text(r.get('value'));unit=text(r.get('unit'));n,u=canonical(value,unit)
            rec['metrics'].append({'type':text(r['type']),'key':metric_key(text(r['type'])),'value':value,
               'unit':unit,'canonical_value':fmt(n) if n is not None else None,'canonical_unit':u,
               'usable':n is not None and not r.get('uncertain',False),'evidence':text(r.get('evidence'))})
        if not rec['measurement_date']:rec['warnings'].append('测试日期不清楚，不能据此确定前后顺序')
    return rec

def derive(before,after):
    left=defaultdict(list);right=defaultdict(list)
    for m in before['metrics']:left[m['key']].append(m)
    for m in after['metrics']:right[m['key']].append(m)
    rows=[]; skipped=[]
    for key in left.keys()|right.keys():
        if len(left[key])!=1 or len(right[key])!=1:
            skipped.append(key+': 单侧缺失或同名指标重复');continue
        b,a=left[key][0],right[key][0]
        if not b['usable'] or not a['usable'] or b['canonical_unit']!=a['canonical_unit']:
            skipped.append(key+': 数值不清或单位不能匹配');continue
        bv,av=Decimal(b['canonical_value']),Decimal(a['canonical_value'])
        rows.append({'type':LABELS.get(key,b['type']),'before':fmt(bv),'after':fmt(av),'delta':fmt(av-bv,True),
           'computed_delta':fmt(av-bv,True),'unit':b['canonical_unit'] or '—','origin':'computed',
           'sources':[{'source_id':before['source_id'],**b},{'source_id':after['source_id'],**a}],
           'warnings':[], 'delta_semantics':'percentage_points' if b['canonical_unit']=='%' else 'after_minus_before'})
    order=list(LABELS.values());rows.sort(key=lambda r:order.index(r['type']) if r['type'] in order else 100)
    return rows,skipped

def pair_by_table_values(measurements,table):
    """Missing printed dates: match explicit phase columns, never better/worse values."""
    if not table or not table['before_date'] or not table['after_date'] or table['before_date']>=table['after_date']:return None
    discriminating=[]
    for row in table['rows']:
        b,a=cell_number(row['before'],row['unit']),cell_number(row['after'],row['unit'])
        if b is None or a is None or b==a or row['warnings'] and '原表单元格缺失或识别待核对' in row['warnings']:continue
        bv,u=canonical(fmt(b),row['unit']);av,_=canonical(fmt(a),row['unit'])
        discriminating.append((metric_key(row['type']),bv,av,u))
    candidates={}; evidence={}
    for index,side in enumerate(('before','after')):
        hits=[]
        for rec in measurements:
            if not rec['identity_ok']:continue
            if rec['measurement_date'] and rec['measurement_date']!=table[side+'_date']:continue
            matches=[];conflicts=[]
            metrics=defaultdict(list)
            for m in rec['metrics']:metrics[m['key']].append(m)
            for key,b,a,unit in discriminating:
                ms=metrics[key]
                if len(ms)!=1 or not ms[0]['usable']:continue
                m=ms[0]
                if key!='bmi' and m['canonical_unit']!=unit:continue
                expected=b if index==0 else a
                if abs(Decimal(m['canonical_value'])-expected)<=Decimal('.051'):matches.append(key)
                else:conflicts.append(key)
            if len(matches)>=2 and not conflicts:hits.append((rec,matches))
        if len(hits)!=1:return None
        candidates[side]=hits[0][0]['source_id'];evidence[side]=hits[0][1]
    if candidates['before']==candidates['after']:return None
    return {**candidates,'before_date':table['before_date'],'after_date':table['after_date'],
            'basis':'matches_explicit_table_values','matched_metrics':evidence}

def choose_pair(measurements,table=None):
    usable=[r for r in measurements if r['identity_ok'] and r['measurement_date'] and any(m['usable'] for m in r['metrics'])]
    days=defaultdict(list)
    for r in usable:days[r['measurement_date']].append(r)
    warnings=[]
    if len(days)<2:
        matched=pair_by_table_values(measurements,table)
        if matched:return matched,['部分报告日期不清，已按原表明确前后列中的多个实测指标唯一匹配；显示日期取自原表，请核对']
        return None,['不足两个不同日期的可用体测报告，未生成前后报告拼图']
    dates=sorted(days)
    if table and table['before_date'] in days and table['after_date'] in days and table['before_date']<table['after_date']:
        dates=[table['before_date'],table['after_date']];basis='matches_explicit_table_dates'
    else:
        dates=[dates[0],dates[-1]];basis='measurement_dates_earliest_latest'
        if table and (table['before_date'],table['after_date'])!=tuple(dates):
            warnings.append('报告图片日期与表格周期未完全匹配，请审核；未按数值好坏调整顺序')
    selected=[]
    for d in dates:
        candidates=sorted(days[d],key=lambda r:(-sum(m['usable'] for m in r['metrics']),r['source_id']))
        selected.append(candidates[0])
        if len(candidates)>1:warnings.append(d+' 存在多份报告，已选指标最完整的一份')
    return {'before':selected[0]['source_id'],'after':selected[1]['source_id'],'before_date':dates[0],
            'after_date':dates[1],'basis':basis},warnings

def build_cases(records,as_of=None):
    from .comparison_rows import rebuild_rows
    as_of=as_of or today_cn()
    groups=defaultdict(list)
    for r in records:groups[(r['store'],r['member'])].append(r)
    cases=[]
    for i,((store,member),recs) in enumerate(sorted(groups.items()),1):
        tables=[r for r in recs if r.get('kind')=='comparison_table' and r.get('identity_ok') and r.get('rows')]
        tables.sort(key=lambda r:(sum(bool(x['warnings']) for x in r['rows']),-len(r['rows']),r['source_id']))
        table=tables[0] if tables else None
        measurements=[r for r in recs if r.get('kind')=='measurement']
        pair,warnings=choose_pair(measurements,table)
        byid={r['source_id']:r for r in measurements}
        before=byid[pair['before']] if pair else None;after=byid[pair['after']] if pair else None
        rows,corrections,skipped,row_warnings=rebuild_rows(before,after,table,pair,as_of)
        warnings.extend(row_warnings)
        if any(r['value_source_kind']=='summary_supplement' for r in rows):
            warnings.append('原始报告缺失的指标由阶段汇总表补充，来源记录在逐行数据中')
        if not rows:warnings.append('没有可用于对比的前后实测值或补充数据，不输出表格')
        if corrections:warnings.append('已按原始报告重建日期和实测值，并重新计算天数及变化量；原填值保留供追溯')
        if any(r['warnings'] for r in rows):warnings.append('部分补充指标需要核对，详见逐行说明')
        names={r['printed_member'] for r in recs if r.get('identity_ok') and r.get('printed_member')}
        if len(names)>1:warnings.append('同目录报告存在多个会员姓名，请审核归属')
        chosen_name=(table.get('printed_member') if table else None) or (next(iter(names)) if len(names)==1 else member)
        compact=re.sub(r'\s+','',(table.get('printed_store') if table else '') or '')
        store_names=re.findall(r'[\u4e00-\u9fff]{2,6}店',compact)
        chosen_store=store if store in compact or not store_names else store_names[-1]
        cases.append({'case_id':f'c{i:03d}','store':store,'member':member,'headers':HEADERS,
          'table_origin':'computed' if rows else 'none','table_source_id':table['source_id'] if table else None,
          'source_policy':'original_measurements_first_summary_fills_gaps','as_of':as_of.isoformat(),
          'rows':rows,'pair':pair,'corrections':corrections,'warnings':list(dict.fromkeys(warnings)),'skipped_metrics':skipped,
          'display_member':chosen_name,'display_store':chosen_store,'identity_authority':'report',
          'source_ids':[r['source_id'] for r in recs],'alternative_table_sources':[r['source_id'] for r in tables[1:]],
          'requires_review':bool(warnings),'transcription_method':'visual_model_or_document_text; not human verified'})
    return cases

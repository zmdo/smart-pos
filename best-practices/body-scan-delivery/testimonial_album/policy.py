"""Deterministic evidence checks, transparent scoring and layout selection."""
import math
import re

WEIGHTS={'length':30,'specificity':35,'emotional_expression':20,'readability':15}
SENTIMENTS={'positive','neutral','mixed','negative','unclear'}

def number(value,low,high):
    n=float(value)
    if not math.isfinite(n) or not low<=n<=high:raise ValueError('score_out_of_range')
    return n

def box(value):
    if not isinstance(value,list) or len(value)!=4:raise ValueError('invalid_bbox')
    x1,y1,x2,y2=[number(v,0,1000) for v in value]
    if x2-x1<20 or y2-y1<10:raise ValueError('empty_or_tiny_bbox')
    return [x1,y1,x2,y2]

def score(message):
    length=len(re.sub(r'[\W_]+','',message['text'],flags=re.UNICODE))
    # Length saturates; a long repetitive message cannot dominate by length alone.
    parts={'length':round(min(1,length/350)*WEIGHTS['length'],2)}
    for k in ('specificity','emotional_expression','readability'):
        parts[k]=round(number(message.get(k),0,5)/5*WEIGHTS[k],2)
    return length,parts,round(sum(parts.values()),2)

def normalize(raw,source):
    if not isinstance(raw,dict):raise ValueError('invalid_evidence')
    record=dict(source,status='rejected',reason=str(raw.get('reason','')),messages=[],issues=[str(x) for x in raw.get('issues',[])])
    if raw.get('is_testimonial') is not True:return record
    context=box(raw.get('context_bbox'));messages=[]
    for i,m in enumerate(raw.get('messages',[])):
        if m.get('role')!='member':continue
        text=str(m.get('text','')).strip()
        if not text:continue
        bounds=box(m.get('bbox'));length,parts,total=score(m)
        msg=dict(m,message_id=source['asset_id']+f'-m{i+1:02}',text=text,bbox=bounds,
                 role_confidence=number(m.get('role_confidence'),0,1),bbox_confidence=number(m.get('bbox_confidence'),0,1),
                 text_line_height=number(m.get('text_line_height',0),0,1000),char_count=length,score_parts=parts,score=total)
        msg['sentiment']=m.get('sentiment') if m.get('sentiment') in SENTIMENTS else 'unclear'
        msg['requires_review']=msg['role_confidence']<.85 or msg['bbox_confidence']<.85 or bool(m.get('cut_off'))
        messages.append(msg)
        context=[min(context[0],bounds[0]),min(context[1],bounds[1]),max(context[2],bounds[2]),max(context[3],bounds[3])]
    if not messages:record['reason']='未找到可读的会员反馈文字';return record
    record.update(status='accepted',messages=messages,context_bbox=context)
    return record

def rank_messages(records):
    rows=[]
    for r in records:
        for m in r.get('messages',[]):
            rows.append(dict(m,asset_id=r['asset_id']))
    # Only confidently attributed complete feedback can be the first-choice hero.
    return sorted(rows,key=lambda m:(m['requires_review'],-m['score'],-m['char_count'],m['message_id']))

def choose_layout(message):
    if message['char_count']>=300 and message['score']>=70:return 'long_story'
    if message['char_count']>=120:return 'focused_story'
    return 'short_reply'

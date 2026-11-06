"""Create cover images and an offline review gallery from approved data."""
import copy
import json
import re
import shutil
import unicodedata
from collections import defaultdict
from pathlib import Path
from PIL import Image

from scripts.body_scan_contracts.io import bind, sha, read, save
from scripts.body_scan_contracts.bundles import load_reports
from scripts.body_scan_delivery.pipeline import current, digest_json
from scripts.body_scan_delivery.presentation import resolve
from scripts.body_scan_delivery.render import priority
from . import VERSION
from .copy import compose
from .framing import coverage_rank, plan_pair, crop_photo
from .render import draw_cover


def coach_from_report(report, directory, bindings):
    if not report or not directory:
        return None, None
    rid=report['report_id'];root=Path(directory)
    text=root/rid/'extracted.txt';record=root/rid/'report.json'
    if not text.exists() or not record.exists():return None,None
    identity=read(bind(record,bindings))
    if any(identity.get(k)!=report.get(k) for k in ('source_sha256','store','member')):
        raise ValueError('coach_transcript_report_identity_mismatch')
    raw=read(bind(text,bindings))
    content=raw.get('paragraphs','')+'\n'+'\n'.join(p['text'] for p in raw.get('pages',[]))
    content=unicodedata.normalize('NFKC',content)
    names=re.findall(r'(?:^|\n)\s*(?:专属)?教练\s*[:：]\s*([^\n]{1,40})',content)
    names=[s.strip() for s in names if s.strip() not in ('无','未填写','/','待定')]
    if len(set(names))!=1:return None,None
    return names[0],{'report_id':rid,'source_sha256':report['source_sha256'],
                     'transcript_sha256':sha(text),'evidence':'教练：'+names[0]}


def metadata_for(row, path, bindings, cache):
    root=Path(path).parents[2];summary=root/'summary.json'
    if summary not in cache:
        cache[summary]={r['asset_id']:r for r in read(bind(summary,bindings))}
    meta=cache[summary][row['asset_id']]
    if any(meta[k]!=row[k] for k in ('store','member','source_sha256')):
        raise ValueError('cover_display_identity_mismatch')
    if meta.get('status')!='displayed' or meta['output']['display_sha256']!=sha(path):
        raise ValueError('cover_pose_does_not_match_photo')
    with Image.open(path) as im:
        if list(im.size)!=meta['group_plan']['output_size']:
            raise ValueError('cover_pose_canvas_mismatch')
    return meta


def run(delivery, out, config_path=None):
    delivery=Path(delivery).resolve();out=Path(out).resolve()
    if out.exists():raise FileExistsError(out)
    original,revision=current(delivery)
    source=read(delivery/'private-inputs.json');bindings=copy.deepcopy(source['bindings'])
    if digest_json(bindings)!=original['source_manifest_sha256']:
        raise ValueError('cover_source_manifest_changed')
    if any(sha(p)!=h for p,h in bindings.items()):raise ValueError('cover_source_changed')
    bind(revision/'result.json',bindings)
    config=read(bind(config_path,bindings)) if config_path else {}
    if set(config)-{'defaults','members','default_case'} or not all(isinstance(config.get(k,{}),dict) for k in ('defaults','members')):
        raise ValueError('invalid_cover_config')
    reports=load_reports(source['report_bundle'],bindings) if source.get('report_bundle') else []
    by_report={r['report_id']:r for r in reports}
    grouped=defaultdict(list)
    for row in original['items']:grouped[(row['group_id'],row['store'],row['member'])].append(row)
    out.mkdir(parents=True);(out/'media').mkdir();cache={};cases=[];gaps=[]
    original_pairs={p['group_id']:p['asset_ids'] for p in original['outputs'] if p['kind']=='vs' and p['view']=='front'}
    for (gid,store,member),rows in sorted(grouped.items()):
        try:
            fronts=[r for r in rows if r['view']=='front']
            meta={r['asset_id']:metadata_for(r,source['photos'][r['asset_id']],bindings,cache) for r in fronts}
            before=[r for r in fronts if r['phase']=='before'];after=[r for r in fronts if r['phase']=='after']
            options=[(a,b) for a in before for b in after if a['source_sha256']!=b['source_sha256']]
            if not options:
                gaps.append({'group_id':gid,'store':store,'member':member,'reason':'缺少两张不同原图的正面训练前后照'});continue
            def score(pair):
                ranks=[coverage_rank(meta[r['asset_id']]) for r in pair]
                return (sum(r[0] for r in ranks),min(r[1] for r in ranks),sum(r[1] for r in ranks),
                        sum(r[2] for r in ranks),[r['asset_id'] for r in pair]==original_pairs.get(gid),
                        priority(pair[0]),priority(pair[1]))
            pair=max(options,key=score)
            product={'group_id':gid,'store':store,'member':member}
            presentation=resolve(product,source.get('presentation'),reports)
            report=by_report.get(presentation['report_id'])
            coach,evidence=coach_from_report(report,source.get('report_bundle'),bindings)
            override={**config.get('defaults',{}),**config.get('members',{}).get(store+'/'+member,{})}
            words=compose(member,presentation['nickname'],report,coach,override)
            words.setdefault('address',presentation['address'])
            words.setdefault('brand_name',presentation['brand_name'])
            if 'brand_name' in words:presentation['brand_name']=words['brand_name']
            paths=[source['photos'][r['asset_id']] for r in pair]
            sizes=[]
            for p in paths:
                with Image.open(p) as im:sizes.append(im.size)
            plans=plan_pair([meta[r['asset_id']] for r in pair],sizes)
            crops=[crop_photo(p,f) for p,f in zip(paths,plans)]
            image,layout=draw_cover(crops,words,presentation,source['font'],store)
            filename=f'media/{gid}-cover.jpg';image.save(out/filename,quality=94,subsampling=0)
            notes=[]
            if not report:notes.append('暂无匹配的已核验体测报告，当前封面不写数字成果。')
            if report and 'stated_duration_differs_from_dates' in report.get('warnings',[]):
                notes.append('报告填写天数与日期跨度不一致，封面不写具体训练天数。')
            if any(p['head_already_incomplete'] for p in plans):notes.append('部分输入照片头部本来不完整，本版以上半身取景。')
            if any(r['requires_review'] for r in pair):notes.append('照片前后阶段沿用现有推断或待审结果，可回原任务修正。')
            cases.append({**product,'file':filename,'sha256':sha(out/filename),'width':1080,'height':1440,
                          'asset_ids':[r['asset_id'] for r in pair],
                          'labels':[{k:r[k] for k in ('asset_id','phase','label','requires_review')} for r in pair],
                          'requires_review':any(r['requires_review'] for r in pair),
                          'copy':words,'coach_evidence':evidence,'framing':plans,'layout':layout,
                          'report_source_sha256':report['source_sha256'] if report else None,
                          'notes':notes,'selection':'prefer_full_body_front_then_complete_head_then_existing_pair',
                          'report_available':bool(report)})
            print(gid,member,'cover_generated','report' if report else 'no_report',flush=True)
        except (ValueError,KeyError,OSError) as error:
            gaps.append({'group_id':gid,'store':store,'member':member,'reason':str(error)})
    if any(sha(p)!=h for p,h in bindings.items()):raise ValueError('cover_input_changed_during_generation')
    cases.sort(key=lambda c:(not c['report_available'],c['store'],c['member']))
    default=config.get('default_case','g013')
    if not any(c['group_id']==default for c in cases):default=cases[0]['group_id'] if cases else None
    data={'version':VERSION,'default_case':default,'cases':cases,'gaps':gaps,
          'source_delivery':original['delivery_id'],'source_revision':original['revision'],
          'source_result_sha256':sha(revision/'result.json'),
          'review_target':{'delivery_id':original['delivery_id'],'base_revision':original['revision'],
                           'source_manifest_sha256':original['source_manifest_sha256'],'submit_url':original['review']['submit_url']},
          'counts':{'covers':len(cases),'with_report':sum(c['report_available'] for c in cases),
                    'with_coach':sum(bool(c['copy']['coach']) for c in cases),'gaps':len(gaps)},'model_requests':0}
    save(out/'cases.json',data)
    save(out/'private-inputs.json',{'bindings':bindings,'source_delivery':str(delivery)})
    template=(Path(__file__).parent/'template.html').read_text()
    payload=json.dumps(data,ensure_ascii=False).replace('<','\\u003c').replace('\u2028','\\u2028').replace('\u2029','\\u2029')
    (out/'index.html').write_text(template.replace('<!--COVER_DATA-->',payload))
    for name in ('gallery.css','gallery.js'):shutil.copy2(Path(__file__).parent/name,out/name)
    return data

"""Consume verified training evidence; select, render and export a reviewable gallery."""
from collections import defaultdict
from pathlib import Path
import html
from PIL import Image,ImageOps
from scripts.body_scan_contracts.io import read,save,sha,bind
from scripts.body_scan_contracts.bundles import open_bundle,seal
from . import EVIDENCE_SCHEMA,VERSION
from .geometry import plan
from .render import settings,frame_for,render


def run(root,evidence,out,config=None):
    root=Path(root).resolve();evidence=Path(evidence).resolve();out=Path(out).resolve();bindings={}
    open_bundle(evidence,EVIDENCE_SCHEMA,('records.json','groups.json','sources.json'),bindings)
    cfg=settings(read(bind(config,bindings)) if config else {})
    if cfg.get('logo_path'):bind(cfg['logo_path'],bindings)
    records=read(evidence/'records.json');groups=read(evidence/'groups.json');bygroup=defaultdict(list);paths={}
    for record in records:
        aid=record['asset_id'];path=(root/record['source']).resolve()
        if aid in paths or not path.is_relative_to(root):raise ValueError('invalid_source_identity')
        paths[aid]=bind(path,bindings,record['source_sha256']);bygroup[record['directory']].append(record)
    out.mkdir(parents=True,exist_ok=False);results=[];review=[]
    for index,group in enumerate(groups,1):
        gid=f'd{index:03}';dest=out/gid;dest.mkdir();sources=bygroup[group['directory']]
        result=dict(group,case_id=gid,status='skipped',products=[],sources=[])
        eligible=[];seen=set()
        for r in sorted(sources,key=lambda x:(-x.get('score',0),x['asset_id'])):
            source={k:r[k] for k in ('asset_id','source_sha256','status','reason','score','action_name','source_cutoff_parts','issues') if k in r}
            aid=r['asset_id'];path=paths[aid]
            with Image.open(path) as raw:im=ImageOps.exif_transpose(raw).convert('RGB')
            original_size=im.size;im.thumbnail((720,960));im.save(dest/(aid+'-source.jpg'),quality=90)
            source['original']=gid+'/'+aid+'-source.jpg'
            if r['status']!='accepted':
                source['output_status']='needs_review' if r['status'] in ('needs_review','error') else 'rejected'
            else:
                if list(original_size)!=r['source_size']:raise ValueError('oriented_source_dimensions_changed')
                assessment=plan(r,original_size,frame_for(cfg),cfg)
                source['framing']=assessment
                if not assessment['passed']:source.update(output_status='rejected',reason=assessment['reason'])
                elif r['source_sha256'] in seen:source.update(output_status='duplicate',reason='相同图片只使用一次')
                elif len(eligible)>=cfg['max_per_member']:source.update(output_status='not_selected',reason='本组已选足清晰训练照片')
                else:
                    seen.add(r['source_sha256']);eligible.append(r);source['output_status']='selected'
            result['sources'].append(source)
        for r in eligible:
            aid=r['asset_id'];meta=render(paths[aid],r,dest/(aid+'.png'),cfg)
            if not meta['passed']:raise ValueError('render_plan_changed')
            result['products'].append(dict(meta,asset_id=aid,action_name=r['action_name'],score=r['score'],
                file=gid+'/'+aid+'.png',preview=gid+'/'+aid+'.jpg',before=gid+'/'+aid+'-before.jpg',
                original=gid+'/'+aid+'-source.jpg',sha256=sha(dest/(aid+'.png')),
                source_sha256=r['source_sha256'],review_flags=(['原图已有局部身体截断，保留现状'] if r.get('source_cutoff_parts') else [])+r.get('issues',[])))
        if result['products']:result['status']='generated'
        elif any(s['output_status']=='needs_review' for s in result['sources']):result['status']='needs_review'
        result['reason']='无日常训练图片候选；视频未抽帧' if not sources else '；'.join(s.get('reason','') for s in result['sources'] if s['output_status'] not in ('selected','duplicate'))
        result['requires_review']=result['status']!='generated' or any(s['output_status']=='needs_review' for s in result['sources']) or any(p['review_flags'] for p in result['products'])
        if result['requires_review']:
            review.append({k:result[k] for k in ('case_id','directory','status','reason','sources')})
        save(dest/'result.json',result);results.append(result)
    export_html(out,results,cfg)
    for name,value in [('results.json',results),('review.json',review),('sources.json',bindings),('presentation.json',cfg)]:save(out/name,value)
    if any(sha(path)!=digest for path,digest in bindings.items()):raise ValueError('source_changed_during_render')
    counts={'groups':len(results),'candidates':len(records),'generated_groups':sum(r['status']=='generated' for r in results),
            'products':sum(len(r['products']) for r in results),'review_groups':sum(r['status']=='needs_review' for r in results),
            'missing_groups':sum(not r['sources'] for r in results),
            'rejected_sources':sum(s['output_status']=='rejected' for r in results for s in r['sources']),
            'model_calls':0}
    save(out/'counts.json',counts);seal(out,VERSION,('results.json','index.html','review.json','presentation.json'));return counts


def export_html(out,results,cfg):
    esc=lambda value:html.escape(str(value));sections=[]
    for group in results:
        cards=[]
        for p in group['products']:
            x,y,w,h=p['crop'];labels='等比嵌入' if p['mode']=='inset' else '完整动作取景'
            flags='；'.join(p['review_flags'])
            cards.append(f'''<article><div class="photo"><img class="finished" src="{p['preview']}" loading="lazy"><img class="before" src="{p['before']}" loading="lazy" hidden><img class="original" src="{p['original']}" loading="lazy" hidden></div><div class="caption"><b>{esc(p['action_name'])}</b><span>{p['asset_id']} · {labels}</span></div><div class="tools"><button class="on" data-image="finished">处理后</button><button data-image="before">同取景 · 调色前</button><button data-image="original">原始照片</button><a href="{p['file']}" download>下载 PNG ↗</a></div><p class="note">{esc(flags)}</p><details><summary>取景与处理记录</summary><p>画布 {p['width']}×{p['height']}；保留完整可见动作区域；照片占框 {p['photo_area_ratio']:.0%}；统一缩放 {p['uniform_scale']:.2f} 倍。</p><p>曝光 {p['tone'].get('exposure_ev',0):+.2f} EV；背景轻度压暗降饱和；原图已有遮挡与截断保留。</p></details></article>''')
        for s in group['sources']:
            if s['output_status'] not in ('selected','duplicate'):
                cards.append(f'''<article class="rejected"><img class="thumb" loading="lazy" src="{s['original']}"><div><b>{esc(s['asset_id'])} · {'待确认' if s['output_status']=='needs_review' else '未生成'}</b><p>{esc(s.get('reason',''))}</p></div></article>''')
        sections.append(f'''<section id="{group['case_id']}" data-status="{group['status']}"><header><small>{esc(group['store'])}</small><h2>{esc(group['member'])}</h2></header>{''.join(cards) or '<p class="note">'+esc(group['reason'])+'</p>'}<a class="record" href="{group['case_id']}/result.json">查看本组记录</a></section>''')
    total=sum(len(g['products']) for g in results)
    page='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>训练日常 · 自然纪实版</title><style>
*{box-sizing:border-box}body{margin:0;background:#f4f1ec;color:#242522;font:15px/1.7 -apple-system,BlinkMacSystemFont,"PingFang SC",sans-serif}main{max-width:1120px;margin:auto;padding:52px 26px}.eyebrow{color:#b00016;font-size:12px;letter-spacing:.18em}h1{font-size:42px;line-height:1.25;margin:12px 0}h2{font-size:26px;margin:0}.intro{color:#68655f;max-width:800px}.filters{position:sticky;top:0;z-index:3;background:#f4f1ecf5;padding:14px 0;border-bottom:1px solid #dcd6ce}button{font:inherit;border:1px solid #d8d2c9;border-radius:24px;background:#fff;padding:7px 15px;cursor:pointer;margin:3px}.on{background:#bd0015;color:white;border-color:#bd0015}section{background:#fff;padding:26px;margin:28px 0;border-radius:15px;border:1px solid #e0dad2}header{margin-bottom:20px}small,.note{color:#84776b}article{margin:20px 0 32px}.photo{background:#e8e4de;aspect-ratio:3/4;overflow:hidden;border-radius:3px}.photo img{width:100%;height:100%;object-fit:contain;display:block}.caption{display:flex;justify-content:space-between;gap:15px;margin-top:14px}.caption span{color:#82776b;font-size:13px}.tools{display:flex;align-items:center;flex-wrap:wrap;gap:4px;margin-top:9px}a{color:#aa0016}.tools a{margin-left:auto}.note,details,.record{font-size:13px}.note:empty{display:none}.rejected{display:flex;gap:18px;padding:18px;background:#f6f3ef}.thumb{width:160px;max-height:230px;object-fit:contain}summary{cursor:pointer}details{color:#786e64;margin:14px 0}[hidden]{display:none!important}@media(max-width:650px){main{padding:24px 12px}section{padding:15px}h1{font-size:32px}.caption{display:block}.thumb{width:100px}}
</style><main><div class="eyebrow">UP · TRAINING JOURNAL</div><h1>每一次训练，都值得记录。</h1>'''
    page+=f'''<p class="intro">已生成 {total} 张 · 统一 {cfg['width']}×{cfg['height']}。完整动作取景、自然调色、轻度背景弱化，保留真实体形与器械关系。点击照片下方按钮，可比较同一取景下的调色前后，也可查看完整原图。</p><nav class="filters"><button class="on" data-filter="all">全部会员</button><button data-filter="generated">已有成品</button><button data-filter="needs_review">待确认</button><button data-filter="skipped">未生成</button></nav>'''+''.join(sections)
    page+='''</main><script>
document.querySelectorAll('[data-image]').forEach(b=>b.onclick=()=>{const card=b.closest('article');card.querySelectorAll('.photo img').forEach(im=>im.hidden=!im.classList.contains(b.dataset.image));card.querySelectorAll('[data-image]').forEach(x=>x.classList.toggle('on',x===b));});
document.querySelectorAll('[data-filter]').forEach(b=>b.onclick=()=>{document.querySelectorAll('section').forEach(s=>s.hidden=b.dataset.filter!=='all'&&s.dataset.status!==b.dataset.filter);document.querySelectorAll('[data-filter]').forEach(x=>x.classList.toggle('on',x===b));});
</script></html>'''
    (out/'index.html').write_text(page,encoding='utf-8')

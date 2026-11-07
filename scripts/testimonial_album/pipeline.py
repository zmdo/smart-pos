"""Compose scored testimonial evidence into downloadable album images and HTML."""
from collections import defaultdict
from pathlib import Path
import html
from scripts.body_scan_contracts.io import read,save,sha,bind
from scripts.body_scan_contracts.bundles import open_bundle,seal
from . import VERSION,EVIDENCE_SCHEMA
from .policy import rank_messages
from .render import render_page,assess_page

LABELS={'long_story':'长篇主图','focused_story':'重点感言','short_reply':'简短回复','wide_reply':'横屏感言'}

def run(root,evidence,out,font,config=None):
    root=Path(root).resolve();evidence=Path(evidence).resolve();out=Path(out).resolve();bindings={}
    open_bundle(evidence,EVIDENCE_SCHEMA,('records.json','groups.json','sources.json'),bindings)
    bind(font,bindings);settings=read(bind(config,bindings)) if config else {}
    if len(settings.get('title','会员感言'))>8 or len(settings.get('brand','UP 健身私教馆'))>40:raise ValueError('display_text_too_long')
    records=read(evidence/'records.json');groups=read(evidence/'groups.json');by_group=defaultdict(list);paths={}
    for r in records:
        p=(root/r['source']).resolve()
        if not p.is_relative_to(root):raise ValueError('source_outside_input')
        paths[r['asset_id']]=bind(p,bindings,r['source_sha256']);by_group[r['directory']].append(r)
    out.mkdir(parents=True,exist_ok=False);results=[];reviews=[]
    for index,group in enumerate(groups,1):
        gid=f't{index:03}';dest=out/gid;dest.mkdir();sources=by_group[group['directory']]
        result=dict(group,case_id=gid,status='skipped',pages=[],sources=sources,quality_rejections=[])
        options={**settings,**settings.get('members',{}).get(group['directory'],{})}
        # Per-member overrides must not create differently sized deliverables.
        options['width']=settings.get('width',1080);options['height']=settings.get('height',1440)
        eligible=[]
        for source in sources:
            if source['status']!='accepted':continue
            hero=rank_messages([source])[0]
            assessment=assess_page([source],paths,hero,options)
            source['presentation']=assessment
            if assessment['passed']:eligible.append(source)
            else:result['quality_rejections'].append(dict(assessment,asset_id=source['asset_id']))
        ranked=rank_messages(eligible)
        if not ranked:
            if result['quality_rejections']:
                result['skip_kind']='unsuitable_screenshot'
                result['reason']='截图不合格，未生成：'+'；'.join(r['asset_id']+' '+r['reason'] for r in result['quality_rejections'])
            else:
                result['skip_kind']='no_testimonial' if sources else 'missing_material'
                result['reason']='；'.join(r.get('reason','') for r in sources) or '门店目录中没有会员感言截图'
        else:
            chosen=options.get('hero_message_id')
            if chosen:
                selected=next((m for m in ranked if m['message_id']==chosen),None)
                if selected is None:raise ValueError('hero_message_not_in_member')
                ranked=[selected]+[m for m in ranked if m is not selected]
            ordered=[];seen_hashes=set()
            for message in ranked:
                record=next(r for r in eligible if r['asset_id']==message['asset_id'])
                if record['source_sha256'] in seen_hashes:continue
                seen_hashes.add(record['source_sha256']);ordered.append(record)
            for n in range(0,len(ordered),2):
                page_records=ordered[n:n+2];ids={r['asset_id'] for r in page_records}
                hero=next(m for m in ranked if m['asset_id'] in ids)
                # Both sources must qualify on their own. If a pair makes the
                # chat area too small, keep each valid source on a separate page.
                batches=[page_records] if assess_page(page_records,paths,hero,options)['passed'] else [[r] for r in page_records]
                for batch in batches:
                    batch_ids={r['asset_id'] for r in batch};batch_hero=next(m for m in ranked if m['asset_id'] in batch_ids)
                    name=f'page-{len(result["pages"])+1:02}'
                    layout=render_page(batch,paths,batch_hero,font,dest/(name+'.png'),options)
                    result['pages'].append(dict(layout,file=gid+'/'+name+'.png',preview=gid+'/'+name+'.jpg',sha256=sha(dest/(name+'.png'))))
            result.update(status='generated',ranking=ranked)
        issues=[r['asset_id']+': '+issue for r in sources for issue in r.get('issues',[])]
        issues.extend(r['asset_id']+': '+r.get('reason','') for r in sources if r['status']!='accepted')
        issues.extend(issue for p in result['pages'] for issue in p['issues'])
        issues.extend(r['asset_id']+': 截图不合格，未生成：'+r['reason'] for r in result['quality_rejections'])
        if any(m['requires_review'] for m in ranked):issues.append('部分会员回复需核对角色或气泡边界')
        result['issues']=list(dict.fromkeys(issues));result['requires_review']=bool(issues) or result['status']=='skipped'
        if result['requires_review']:reviews.append({k:result.get(k) for k in ('case_id','directory','status','issues','reason','skip_kind','quality_rejections')})
        for r in sources:
            # Export original screenshots separately for manual crop/role review.
            import shutil
            suffix=paths[r['asset_id']].suffix.lower();name=r['asset_id']+'-original'+suffix
            shutil.copy2(paths[r['asset_id']],dest/name);r['preview_original']=gid+'/'+name
        save(dest/'result.json',result);results.append(result)
    export_html(out,results)
    save(out/'results.json',results);save(out/'review.json',reviews);save(out/'sources.json',bindings)
    if any(sha(p)!=h for p,h in bindings.items()):raise ValueError('source_changed_during_render')
    counts={'groups':len(results),'generated_groups':sum(r['status']=='generated' for r in results),
            'pages':sum(len(r['pages']) for r in results),'skipped_groups':sum(r['status']=='skipped' for r in results),
            'rejected_sources':sum(r['status']=='rejected' for r in records),
            'layout_rejected_sources':sum(len(r['quality_rejections']) for r in results),
            'quality_skipped_groups':sum(r.get('skip_kind')=='unsuitable_screenshot' for r in results),'model_calls':0}
    save(out/'counts.json',counts);seal(out,VERSION,('results.json','review.json','index.html'));return counts

def export_html(out,results):
    esc=lambda v:html.escape(str(v));cards=[]
    for r in results:
        pages=''.join(f'<figure><a href="{p["file"]}" target="_blank"><img loading="lazy" src="{p["preview"]}"></a><figcaption>{LABELS[p["layout"]]} · {p["width"]}×{p["height"]} <a href="{p["file"]}" download>下载 PNG</a></figcaption></figure>' for p in r['pages'])
        analyses=[]
        for source in r['sources']:
            text=f'<h4>{esc(source["asset_id"])} · {esc(source["status"])} <a href="{esc(source["preview_original"])}" target="_blank">查看原图</a></h4><p>{esc(source["reason"])}</p>'
            if source.get('presentation') and not source['presentation']['passed']:
                text+='<p class="note">截图不合格，未生成：'+esc(source['presentation']['reason'])+'</p>'
            for m in source.get('messages',[]):
                parts=' / '.join(f'{k} {v:g}' for k,v in m['score_parts'].items())
                text+=f'<p><b>{m["score"]:g} 分</b> · {m["char_count"]} 字 · {esc(m["sentiment"])} · {esc(m["score_reason"])}</p><small>{esc(parts)}</small><blockquote>{esc(m["text"])}</blockquote>'
            analyses.append(text)
        cards.append(f'<section id="{r["case_id"]}" data-status="{r["status"]}" data-layout="{" ".join(p["layout"] for p in r["pages"])}"><header><span>{esc(r["store"])}</span><h2>{esc(r["member"])}</h2></header>{pages or "<p>"+esc(r.get("reason",""))+"</p>"}<p class="note">{esc("；".join(r["issues"]))}</p><details><summary>原图、评分与选图依据</summary>{"".join(analyses)}</details><a class="data" href="{r["case_id"]}/result.json">查看完整排版数据</a></section>')
    page='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>会员感言 · 相册预览</title><style>
*{box-sizing:border-box}body{margin:0;background:#f5f2ed;color:#252522;font:16px/1.7 -apple-system,BlinkMacSystemFont,"PingFang SC",sans-serif}main{max-width:1180px;margin:auto;padding:48px 28px}.kicker{color:#c40013;letter-spacing:.2em;font-size:12px}h1{font-size:42px;letter-spacing:-1px;margin:10px 0}h2{margin:0;font-size:25px}.intro{max-width:820px;color:#6c6862}nav{position:sticky;top:0;z-index:3;background:#f5f2edf5;padding:12px 0;border-bottom:1px solid #ded9d1}button{font:inherit;border:1px solid #d8d2ca;border-radius:28px;padding:8px 18px;background:white;margin:4px;cursor:pointer}button.active{background:#c90014;border-color:#c90014;color:white}section{background:#fff;padding:28px;border:1px solid #e6e0d8;border-radius:18px;margin:30px 0}header{margin-bottom:20px}header span{color:#8d8178;font-size:13px}figure{margin:0 0 22px}img{display:block;width:100%;height:auto}figcaption{color:#85796e;font-size:13px;margin-top:12px}a{color:#bb0012}figcaption a{float:right}details{margin:16px 0;color:#635d56}summary{cursor:pointer}blockquote{white-space:pre-wrap;background:#f7f5f1;border-left:3px solid #d8c3ae;margin:12px 0;padding:18px}.note{color:#927345;font-size:14px}.data{font-size:13px}[hidden]{display:none!important}@media(max-width:640px){main{padding:24px 12px}h1{font-size:32px}section{padding:14px}}
</style><main><div class="kicker">UP · MEMBER STORIES</div><h1>会员感言，相册里的真实反馈。</h1><p class="intro">主图根据会员回复的篇幅、具体内容、情感表达和清晰度选择。成品统一1080×1440，每张截图只使用一次；单张素材使用单图排版，多张素材按评分分配位置。截图等比缩放，保留相关对话，不改写聊天。图标和标题使用固定尺寸；聊天截图不足成品面积的一半，或标题区超过40%，则跳过生成并给出原因。评分只用于排版，详细依据可以展开查看。</p><nav><button class="active" data-filter="all">全部</button><button data-filter="long_story">长篇主图</button><button data-filter="focused_story">重点感言</button><button data-filter="short_reply">简短回复</button><button data-filter="wide_reply">横屏感言</button><button data-filter="skipped">未生成</button></nav>'''+''.join(cards)+'''</main><script>document.querySelectorAll('button').forEach(b=>b.onclick=()=>{document.querySelectorAll('button').forEach(x=>x.classList.toggle('active',x===b));document.querySelectorAll('section').forEach(s=>s.hidden=b.dataset.filter!=='all'&&(b.dataset.filter==='skipped'?s.dataset.status!=='skipped':!s.dataset.layout.split(' ').includes(b.dataset.filter)));});</script></html>'''
    first_page=next((p for r in results for p in r['pages']),None)
    if first_page:page=page.replace('统一1080×1440',f'统一{first_page["width"]}×{first_page["height"]}')
    (out/'index.html').write_text(page,encoding='utf-8')

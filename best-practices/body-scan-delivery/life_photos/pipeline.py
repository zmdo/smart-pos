"""Copy upstream life_photo selections, preserving every byte and source binding."""
from collections import defaultdict
from pathlib import Path
import html
import re
import shutil
from scripts.body_scan_contracts.io import read,save,bind,sha
from scripts.body_scan_contracts.bundles import seal
from . import VERSION

IMAGE_SUFFIXES={'.jpg','.jpeg','.png','.webp','.bmp','.tif','.tiff','.gif','.avif','.heic','.heif'}
WEB_SUFFIXES={'.jpg','.jpeg','.png','.webp','.gif','.avif','.bmp'}


def inventory(root,audit):
    root=Path(root).resolve();selected=[];groups={};seen=set()
    rows=read(audit)
    if not isinstance(rows,list):raise ValueError('invalid_classification_inventory')
    for row in rows:
        rel=Path(row['source'].split('/私教会员案例项目/',1)[-1])
        if row.get('reference_material') or len(rel.parts)<3 or not rel.parts[0].endswith('店'):
            continue
        if '..' in rel.parts or not (root/rel).resolve().is_relative_to(root) or rel.parts[0]!=row['store']:
            raise ValueError('invalid_store_source')
        directory=str(Path(*rel.parts[:2]))
        groups[directory]=dict(store=row['store'],member=row['member'],directory=directory)
        provider,label=next(((key,row[key]) for key in ('qwen','deepseek','old') if row.get(key)),('none',{}))
        if label.get('kind')!='life_photo':continue
        aid=row['asset_id']
        if not re.fullmatch(r'a\d+',aid) or aid in seen:raise ValueError('duplicate_or_invalid_asset_id')
        seen.add(aid)
        selected.append(dict(groups[directory],asset_id=aid,source=str(rel),source_sha256=row['source_sha256'],
            classification_provider=provider,classification_reason=str(label.get('reason','')),
            supported=rel.suffix.lower() in IMAGE_SUFFIXES))
    return selected,[groups[k] for k in sorted(groups)]


def run(root,audit,out):
    root=Path(root).resolve();out=Path(out).resolve();bindings={}
    if out.exists():raise FileExistsError(out)
    audit=bind(audit,bindings);records,groups=inventory(root,audit);bygroup=defaultdict(list);paths={}
    # Validate every selected image before creating output; never silently skip a missing/tampered source.
    for record in records:
        if record['supported']:
            paths[record['asset_id']]=bind(root/record['source'],bindings,record['source_sha256'])
        bygroup[record['directory']].append(record)
    out.mkdir(parents=True);results=[];review=[]
    for index,group in enumerate(groups,1):
        gid=f'l{index:03}';dest=out/gid;dest.mkdir()
        result=dict(group,case_id=gid,status='skipped',products=[],sources=[],reason='没有已筛选的生活照')
        for record in sorted(bygroup[group['directory']],key=lambda x:x['asset_id']):
            aid=record['asset_id'];source=dict(record)
            if not record['supported']:
                source.update(output_status='rejected',reason='分类为生活照，但文件不是支持的图片格式')
            else:
                path=paths[aid];target=dest/(aid+path.suffix)
                shutil.copy2(path,target)
                if sha(target)!=record['source_sha256']:raise ValueError('copied_photo_hash_mismatch')
                result['products'].append(dict(asset_id=aid,kind='life_photo',mode='original_passthrough',
                    file=str(target.relative_to(out)),preview=str(target.relative_to(out)) if path.suffix.lower() in WEB_SUFFIXES else None,
                    original_filename=path.name,source=record['source'],source_sha256=record['source_sha256'],
                    sha256=record['source_sha256'],classification_provider=record['classification_provider'],
                    classification_reason=record['classification_reason'],processing_applied=False))
                source.update(output_status='selected',reason='复用生活照分类，原文件直接输出')
            result['sources'].append(source)
        if result['products']:result.update(status='generated',reason='')
        elif result['sources']:result['reason']='；'.join(s['reason'] for s in result['sources'])
        if result['status']!='generated' or any(s['output_status']=='rejected' for s in result['sources']):
            review.append({k:result[k] for k in ('case_id','directory','status','reason','sources')})
        save(dest/'result.json',result);results.append(result)
    export_html(out,results)
    counts=dict(groups=len(groups),candidates=len(records),products=sum(len(g['products']) for g in results),
        generated_groups=sum(g['status']=='generated' for g in results),missing_groups=sum(not g['sources'] for g in results),
        rejected_sources=sum(s['output_status']=='rejected' for g in results for s in g['sources']),model_calls=0)
    for name,value in [('results.json',results),('review.json',review),('sources.json',bindings),('counts.json',counts)]:save(out/name,value)
    if any(sha(path)!=digest for path,digest in bindings.items()):raise ValueError('source_changed_during_export')
    seal(out,VERSION,('results.json','review.json','sources.json','counts.json','index.html'))
    return counts


def export_html(out,results):
    esc=lambda value:html.escape(str(value),quote=True);sections=[]
    for group in results:
        cards=[]
        for product in group['products']:
            photo=(f'<img loading="lazy" src="{esc(product["preview"])}" alt="会员生活照">' if product['preview'] else
                   '<p>浏览器无法直接预览此原始格式，请下载查看。</p>')
            cards.append(f'<article>{photo}<footer><span>{esc(product["asset_id"])} · 原图</span>'
                         f'<a href="{esc(product["file"])}" download="{esc(product["original_filename"])}">下载原文件 ↗</a></footer></article>')
        body=''.join(cards) or f'<p class="empty">{esc(group["reason"])}</p>'
        sections.append(f'<section id="{group["case_id"]}" data-status="{group["status"]}"><small>{esc(group["store"])}</small>'
                        f'<h2>{esc(group["member"])}</h2><div class="photos">{body}</div>'
                        f'<a class="record" href="{group["case_id"]}/result.json">查看素材记录</a></section>')
    total=sum(len(g['products']) for g in results)
    page='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>会员生活照 · 原图成品</title><style>
*{box-sizing:border-box}body{margin:0;background:#f4f1ec;color:#242522;font:15px/1.7 -apple-system,BlinkMacSystemFont,"PingFang SC",sans-serif}main{max-width:1120px;margin:auto;padding:48px 24px}h1{font-size:36px;margin:8px 0}h2{margin:0 0 20px}small,.intro,.empty{color:#786e64}.eyebrow{letter-spacing:.15em;color:#b00016}.filters{position:sticky;top:0;background:#f4f1ecf5;padding:12px 0;z-index:2}button{font:inherit;padding:7px 16px;border:1px solid #d8d2c9;border-radius:24px;background:white;cursor:pointer}.on{background:#b00016;color:white;border-color:#b00016}section{padding:26px;background:#fff;margin:24px 0}.photos{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:22px;align-items:start}article{min-width:0}article img{display:block;width:100%;height:auto}footer{display:flex;justify-content:space-between;gap:12px;margin-top:10px}a{color:#aa0016}.record{display:inline-block;font-size:13px;margin-top:24px}[hidden]{display:none!important}@media(max-width:650px){main{padding:24px 12px}.photos{grid-template-columns:1fr}section{padding:16px}h1{font-size:30px}}
</style><main><div class="eyebrow">UP · LIFE MOMENTS</div><h1>训练之外，也是生活。</h1>'''
    page+=f'<p class="intro">已筛选 {total} 张生活照。原文件直接交付，保留原始尺寸、格式与内容。</p>'
    page+='<nav class="filters"><button class="on" data-filter="all">全部会员</button> <button data-filter="generated">已有成品</button> <button data-filter="skipped">缺少素材</button></nav>'
    page+=''.join(sections)+'''</main><script>
document.querySelectorAll('[data-filter]').forEach(b=>b.onclick=()=>{document.querySelectorAll('section').forEach(s=>s.hidden=b.dataset.filter!=='all'&&s.dataset.status!==b.dataset.filter);document.querySelectorAll('[data-filter]').forEach(x=>x.classList.toggle('on',x===b));});
</script></html>'''
    (out/'index.html').write_text(page,encoding='utf-8')

"""Portable review UI: export corrections offline, submit online to the same API."""
import html
import json
from pathlib import Path

REASONS={
    'existing_analysis_assignment':'沿用已有的阶段分析结果。',
    'existing_tentative_inference':'采用已有的轻微变化推断，等待人工确认。',
    'reliable_session_propagation':'沿用同一可靠拍摄批次的阶段推断。',
    'highest_support_with_session_and_pair_constraints':'按支持分选择前后，并保持拍摄批次一致和不同原图配对。',
    'no_directional_evidence_deterministic_placeholder':'没有可用方向证据，当前为临时占位，请人工确认。',
    'explicit_user_review':'用户已审核并确认当前阶段。',
    'no_stable_comparable_region':'缺少稳定、可比较的局部差异。',
    'single_subtle_view':'只有单个朝向的轻微差异，尚不足以确认先后。',
    'session_assignment_conflict':'不同朝向或同批照片的前后判断存在冲突。',
    'consistent_visual_evidence':'存在方向一致的视觉变化证据，仍属于推断。',
}


def preview(result,dest):
    esc=lambda x:html.escape(str(x),quote=True)
    groups={}
    for row in result['items']:groups.setdefault((row['group_id'],row['store'],row['member']),[]).append(row)
    sections=[]
    for (gid,store,member),rows in groups.items():
        cards=[]
        for row in rows:
            options=''.join(f'<option value="{p}"'+(' selected' if row['phase']==p else '')+'>'+name+'</option>' for p,name in (('before','训练前'),('after','训练后')))
            score='人工已确认' if row['label_kind']=='human' else '位置或文字规则' if row['label_kind']=='rule' else '没有可用支持分' if row['confidence'] is None else f'模型支持分 {row["confidence"]:.2f}（非准确率）'
            cards.append(f'<article data-asset="{row["asset_id"]}" data-review="{str(row["requires_review"]).lower()}">'
                f'<img loading="lazy" src="{row["thumbnail"]}"><b>{row["asset_id"]} · {esc(row["view"])}</b>'
                f'<span class="badge {row["label_kind"]}">{esc(row["label"])}</span><small>{esc(score)}</small>'
                f'<select aria-label="{row["asset_id"]}阶段">{options}</select>'
                '<label><input type="checkbox">我已审核此图</label>'
                f'<details><summary>判断依据</summary><p>{esc(REASONS.get(row["analysis_reason"],row["analysis_reason"]))}</p>'
                f'<p>{esc(REASONS.get(row["assignment_reason"],row["assignment_reason"]))}</p></details></article>')
        products=''.join(f'<figure><a href="{esc(o["file"])}"><img loading="lazy" src="{esc(o["file"])}"></a>'
                         f'<figcaption>{esc(o["product_id"])} · '+('含待审核项' if o['requires_review'] else '已确认/规则标签')+'</figcaption></figure>'
                         for o in result['outputs'] if o['group_id']==gid and o['kind']!='single')
        sections.append(f'<section id="{gid}"><h2>{esc(store)} / {esc(member)}</h2><div class="photos">{"".join(cards)}</div>'
                        f'<details class="products"><summary>查看 VS 与三视图成品</summary><div class="gallery">{products or "尚缺配对素材，仅生成单图"}</div></details></section>')
    data=json.dumps({k:result[k] for k in ('delivery_id','revision','source_manifest_sha256')},ensure_ascii=False).replace('<','\\u003c')
    page='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>体测成品与阶段审核</title>
<style>body{font:15px/1.6 system-ui,sans-serif;background:#f5f4ee;color:#273c31;margin:0}main{max-width:1440px;margin:auto;padding:30px}h1{font-size:30px}a{color:#356b4b}button,.button{border:0;border-radius:7px;padding:12px 18px;background:#365e47;color:white;cursor:pointer;text-decoration:none}button:disabled{opacity:.5;cursor:wait}.bar{position:sticky;top:0;padding:15px;background:#f5f4eef5;z-index:2;display:flex;gap:12px;flex-wrap:wrap}section{padding:22px;background:white;border:1px solid #dde5d9;border-radius:14px;margin:25px 0}.photos{display:flex;gap:15px;overflow:auto}article{width:180px;flex-shrink:0;display:flex;flex-direction:column;gap:9px}article img{height:330px;width:180px;object-fit:contain;background:#eeece5}article small{font-size:12px;color:#6c796c}.badge{padding:3px 8px;border-radius:6px;background:#e7efe4}.inferred{background:#fff0c9}.pending{background:#fce0d4}select{padding:8px;border:1px solid #acbaaa;border-radius:6px}details p{font-size:12px;overflow-wrap:anywhere}.products{margin-top:22px}.gallery{display:flex;overflow:auto;gap:16px}figure{margin:15px 0;flex-shrink:0;width:280px}figure img{width:280px}figcaption{font-size:12px}#status{color:#89542f;white-space:pre-wrap}.note{padding:14px;background:#eaf0e5;border-left:4px solid #6c8764}input[type=file]{max-width:230px}@media(max-width:700px){main{padding:14px}section{padding:14px}.bar{position:static}}</style><main>'''
    page+=f'<h1>体测成品与阶段审核 · 第 {result["revision"]} 版</h1><p>{result["counts"]["images"]} 张图片 · {result["counts"]["products"]} 张成品 · {result["counts"]["requires_review"]} 张图片待审核</p>'
    page+='<p class="note">“（推断）”与“（待审）”均为未获人工确认的生成标签。选择正确阶段并勾选已审核，可导出修正文件或在线重新生成。只确认勾选的图片，其他标记继续保留。单图保留全部素材；VS 和三视图仅使用不同原图配对。</p>'
    page+='<div class="bar"><a class="button" href="products.zip" download>下载全部成品与审核清单</a><button id="export">导出审核结果</button><button id="submit">提交修正并重新生成</button><label>导入审核 JSON <input id="import" type="file" accept=".json,application/json"></label><a href="review.json">审核清单 JSON</a><a href="result.json">完整返回结果</a></div><p id="status"></p>'
    page+=''.join(sections)+f'<script type="application/json" id="metadata">{data}</script>'
    page+='''<script>
const meta=JSON.parse(document.getElementById('metadata').textContent),status=document.getElementById('status');
let imported=null;
const uuid=()=>globalThis.crypto?.randomUUID?.()||'review-'+Date.now()+'-'+Math.random().toString(36).slice(2);
document.querySelectorAll('article select').forEach(s=>s.addEventListener('change',()=>{s.closest('article').querySelector('input').checked=true;imported=null;}));
document.querySelectorAll('article input').forEach(s=>s.addEventListener('change',()=>imported=null));
function payload(){if(imported)return imported;const changes=[...document.querySelectorAll('article')].filter(a=>a.querySelector('input').checked).map(a=>({asset_id:a.dataset.asset,phase:a.querySelector('select').value,confirm:true}));if(!changes.length)throw Error('请先勾选已审核的图片。');return {delivery_id:meta.delivery_id,base_revision:meta.revision,source_manifest_sha256:meta.source_manifest_sha256,request_id:uuid(),changes};}
document.getElementById('export').onclick=()=>{try{const value=payload();imported=value;const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([JSON.stringify(value,null,2)],{type:'application/json'}));a.download='review-corrections.json';a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000);status.textContent='已导出修正文件。';}catch(e){status.textContent=e.message;}};
document.getElementById('import').onchange=async(e)=>{try{const value=JSON.parse(await e.target.files[0].text());if(value.delivery_id!==meta.delivery_id||value.base_revision!==meta.revision||value.source_manifest_sha256!==meta.source_manifest_sha256)throw Error('审核文件不属于当前版本，请打开对应版本再提交。');if(!Array.isArray(value.changes)||!value.changes.length)throw Error('没有可提交的修正。');for(const c of value.changes){const a=[...document.querySelectorAll('article')].find(a=>a.dataset.asset===c.asset_id);if(!a||!['before','after'].includes(c.phase)||c.confirm!==true)throw Error('审核文件包含无效图片或未确认项。');a.querySelector('select').value=c.phase;a.querySelector('input').checked=true;}imported=value;status.textContent='已载入 '+value.changes.length+' 项修正，点击提交重新生成。';}catch(e){status.textContent=e.message;imported=null;}};
document.getElementById('submit').onclick=async()=>{const b=document.getElementById('submit');try{if(!location.pathname.startsWith('/api/productions/'))throw Error('本地预览请先导出审核结果，再在在线生成服务导入提交。');const data=payload();imported=data;b.disabled=true;status.textContent='正在重新生成受影响的成品…';const response=await fetch('/api/productions/'+meta.delivery_id+'/review',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});const result=await response.json();if(!response.ok)throw Error(result.detail||'提交失败');location.href=result.preview_url;}catch(e){status.textContent=e.message;b.disabled=false;}};
</script></main></html>'''
    (Path(dest)/'index.html').write_text(page,encoding='utf-8')

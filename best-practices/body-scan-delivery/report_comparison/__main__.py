"""Render existing table data and crop frames; no models or upstream imports."""
import argparse
import html
import json
from pathlib import Path
from PIL import Image
from scripts.body_scan_contracts.io import read,save,sha,bind
from scripts.body_scan_contracts.bundles import open_bundle,seal
from .render import render
from . import VERSION

SCHEMA='body-report-five-column-v1'

def run(tables,crops,out,font,width=None):
    tables=Path(tables).resolve();crops=Path(crops).resolve();out=Path(out).resolve()
    bindings={};open_bundle(tables,SCHEMA,('records.json','tables.json','index.html'),bindings)
    records=read(tables/'records.json');cases=read(tables/'tables.json');byid={r['source_id']:r for r in records}
    cropdata=read(bind(crops/'manifest.json',bindings));byasset={r['asset_id']:r for r in cropdata['rows']}
    bind(font,bindings);out.mkdir(parents=True,exist_ok=False);results=[];cards=[];review=[]
    esc=lambda x:html.escape(str(x))
    for c in cases:
        dest=out/c['case_id'];dest.mkdir();warnings=list(c['warnings']);images={};reference=[]
        result={k:c[k] for k in ('case_id','store','member','display_member','display_store','table_origin','pair')}
        result.update(status='skipped',warnings=warnings,table_source_id=c['table_source_id'])
        if not c['rows']:
            result['reason']='没有可用表格或前后体测数据'
        else:
            try:
                if c['pair']:
                    for side in ('before','after'):
                        sid=c['pair'][side];record=byid[sid];crop=byasset.get(sid)
                        if not crop or crop['source_sha256']!=record['source_sha256']:
                            raise ValueError('report_crop_source_mismatch')
                        path=bind(crops/sid/'frame.png',bindings,crop['frame_sha256'])
                        images[side]=path;reference.append(record['source_size'][0])
                        if crop['status']!='cropped':warnings.append(side+' 报告裁剪仍待审核')
                if not reference:
                    # Table-only product uses its source image width, or document default.
                    source=byid.get(c['table_source_id'],{});reference=[source.get('source_size',[1080])[0]]
                w=width or 2*max(reference)
                layout=render(c,images,w,font,dest/'product.png')
                with Image.open(dest/'product.png') as im:
                    im.thumbnail((1200,1600));im.save(dest/'preview.jpg',quality=93)
                save(dest/'table.json',{'headers':c['headers'],'rows':c['rows'],'warnings':warnings,'source_ids':c['source_ids']})
                result.update(status='generated',layout=layout,product_sha256=sha(dest/'product.png'))
            except (ValueError,OSError,KeyError) as e:result.update(status='error',reason=str(e));warnings.append(str(e))
        result['requires_review']=bool(warnings);results.append(result);save(dest/'result.json',result)
        if warnings:review.append({'case_id':c['case_id'],'member':c['member'],'warnings':warnings,
            'row_issues':[{'type':r['type'],'issues':r['warnings']} for r in c['rows'] if r['warnings']]})
        title=esc(c['store']+' / '+c['member']);notes=esc('；'.join(warnings))
        mode='现成表格复刻' if c['table_origin']=='transcribed' else '体测数据计算' if c['table_origin']=='computed' else '无表格'
        detail='<details><summary>数据来源与逐行核验</summary><ul>'+''.join('<li>'+esc(r['type']+'：'+'；'.join(r['warnings']))+'</li>' for r in c['rows'] if r['warnings'])+'</ul><p>来源：'+esc(', '.join(c['source_ids']))+'</p></details>'
        media=(f'<a href="{c["case_id"]}/product.png" target="_blank"><img loading="lazy" src="{c["case_id"]}/preview.jpg"></a>'
               f'<p><a href="{c["case_id"]}/product.png" download>下载 PNG</a> · <a href="{c["case_id"]}/table.json">五列表格数据</a></p>') if result['status']=='generated' else '<p>'+esc(result.get('reason',''))+'</p>'
        cards.append(f'<section id="{c["case_id"]}" data-origin="{c["table_origin"]}" data-review="{str(bool(warnings)).lower()}"><h2>{title}</h2><p>{mode}</p>{media}<p class="warning">{notes}</p>{detail}</section>')
    page='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>报告对比成品</title><style>
body{margin:0;background:#f4f1ec;color:#27352c;font:16px/1.7 -apple-system,BlinkMacSystemFont,"PingFang SC",sans-serif}main{max-width:1080px;margin:auto;padding:36px 24px}h1{font-size:30px}h2{font-size:23px}section{background:white;border-radius:12px;padding:24px;margin:28px 0}img{display:block;width:100%;height:auto}a{color:#b80012}p{color:#647067}.warning{color:#93672a}nav{position:sticky;top:0;background:#f4f1ecf5;padding:12px 0}button{padding:9px 16px;border:1px solid #d3cec6;background:white;border-radius:20px;margin:3px;font:inherit;cursor:pointer}button.active{background:#cf0012;color:white;border-color:#cf0012}[hidden]{display:none!important}details{font-size:14px}section[data-review=true]{border:1px solid #e7cfaa}
</style><main><h1>体测报告 · 对比成品预览</h1><p>上方按测试日期或明确表格日期配对报告，下方复刻原表；没有现成表格时，由前后实测值计算。没有可用数据则不生成。原填变化量即使有误也保留，核验说明放在图片之外。识别结果尚未经人工逐项确认。</p>
<nav><button class="active" data-filter="all">全部</button><button data-filter="transcribed">原表复刻</button><button data-filter="computed">体测计算</button><button data-filter="review">待核对</button><button data-filter="none">未生成表格</button></nav>'''+''.join(cards)+'''</main><script>document.querySelectorAll('button').forEach(b=>b.onclick=()=>{document.querySelectorAll('button').forEach(x=>x.classList.toggle('active',x===b));document.querySelectorAll('section').forEach(s=>s.hidden=b.dataset.filter==='review'?s.dataset.review!=='true':b.dataset.filter!=='all'&&s.dataset.origin!==b.dataset.filter)});</script></html>'''
    (out/'index.html').write_text(page,encoding='utf-8');save(out/'results.json',results);save(out/'review.json',review);save(out/'sources.json',bindings)
    if any(sha(p)!=h for p,h in bindings.items()):raise ValueError('source_changed_during_render')
    seal(out,VERSION,('results.json','review.json','index.html'))
    counts={'cases':len(results),'generated':sum(r['status']=='generated' for r in results),
            'skipped':sum(r['status']=='skipped' for r in results),'errors':sum(r['status']=='error' for r in results),
            'review':len(review),'model_calls':0}
    save(out/'counts.json',counts);return counts

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for n in ('tables','crops','out','font'):p.add_argument('--'+n,type=Path,required=True)
    p.add_argument('--width',type=int,help='Explicit fixed export width; default twice original report width')
    a=p.parse_args();print(run(a.tables,a.crops,a.out,a.font,a.width))
if __name__=='__main__':main()

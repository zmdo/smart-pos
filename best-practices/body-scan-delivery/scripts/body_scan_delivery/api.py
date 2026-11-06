"""Mounted inside the existing authenticated Case Studio application."""
import os
import re
from pathlib import Path

from fastapi import APIRouter,HTTPException,Request
from fastapi.responses import FileResponse,HTMLResponse

from .pipeline import current,correct,ReviewConflict,read

router=APIRouter()


def base():return Path(os.environ.get('CASE_DELIVERIES','/root/autodl-fs/case-studio/productions')).resolve()


def delivery(identifier):
    if not re.fullmatch(r'[A-Za-z0-9_-]{8,80}',identifier):raise HTTPException(404,'不存在的生成任务')
    path=base()/identifier
    if not (path/'current.json').is_file():raise HTTPException(404,'不存在的生成任务')
    return path


def response(result):
    prefix=f'/api/productions/{result["delivery_id"]}/files/r{result["revision"]:04d}/'
    return {**result,'preview_url':prefix+'index.html','download_url':prefix+'products.zip',
            'review_url':prefix+'review.json','result_url':prefix+'result.json'}


@router.get('/api/productions')
def list_productions():
    results=[]
    for path in sorted(base().glob('*/current.json'),reverse=True):
        result,_=current(path.parent)
        public=response(result)
        results.append({k:public[k] for k in ('delivery_id','revision','counts','status','preview_url','download_url')})
    return results


@router.get('/api/productions/{identifier}')
def get_production(identifier:str):return response(current(delivery(identifier))[0])


@router.post('/api/productions/{identifier}/review')
async def submit_review(identifier:str,request:Request):
    # JSON content type + the host app's authenticated SameSite session prevent
    # cross-origin form submissions from becoming review actions.
    if request.headers.get('content-type','').split(';')[0].strip()!='application/json':raise HTTPException(415,'需要 JSON 审核结果')
    body=bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body)>256*1024:raise HTTPException(413,'审核结果过大')
    import json
    from starlette.concurrency import run_in_threadpool
    try:
        payload=json.loads(body)
        result=await run_in_threadpool(correct,delivery(identifier),payload)
        return response(result)
    except ReviewConflict as error:raise HTTPException(409,str(error))
    except (ValueError,TypeError) as error:raise HTTPException(422,str(error))


@router.get('/api/productions/{identifier}/files/{revision}/{filename:path}')
def files(identifier:str,revision:str,filename:str):
    root=delivery(identifier)
    if not re.fullmatch(r'r\d{4,}',revision):raise HTTPException(404)
    directory=root/'revisions'/revision
    if not (directory/'result.json').is_file():raise HTTPException(404)
    result=read(directory/'result.json')
    allowed={'index.html','result.json','review.json','review-template.json','products.zip'}
    allowed.update(p['file'] for p in result['outputs']);allowed.update(r['thumbnail'] for r in result['items'])
    if result.get('report_comparison'):
        allowed.update(('reports/index.html','reports/reports.json','reports/inventory.json'))
    if filename not in allowed:raise HTTPException(404)
    path=(directory/filename).resolve()
    if not path.is_relative_to(directory.resolve()) or not path.is_file():raise HTTPException(404)
    return FileResponse(path,filename='products.zip' if filename=='products.zip' else None)


@router.get('/review')
def review_home():
    return HTMLResponse('''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>体测成品审核</title><style>body{font:16px/1.7 system-ui;background:#f4f4ed;color:#304d3b;max-width:960px;margin:60px auto;padding:20px}input,button{font:inherit;padding:12px;border-radius:7px;border:1px solid #a6b59e}button{background:#365e47;color:white}article{padding:20px;background:white;margin:20px 0;border-radius:12px}a{color:#365e47}</style><h1>体测成品审核</h1><p>推断和待审标签先用于生成；审核修正后保存新版本。</p><form id="login" hidden><input id="token" type="password" placeholder="现有工作台访问码" autocomplete="current-password"><button>进入审核</button></form><p id="status"></p><main id="list"></main><script>
async function load(){const response=await fetch('/api/productions');if(response.status===401){document.getElementById('login').hidden=false;return;}if(!response.ok)throw Error('无法读取生成任务');const rows=await response.json();const host=document.getElementById('list');host.replaceChildren();for(const r of rows){const article=document.createElement('article'),a=document.createElement('a');a.href=r.preview_url;a.textContent=r.delivery_id+' · 第 '+r.revision+' 版';article.append(a);const p=document.createElement('p');p.textContent=r.counts.images+' 张图片 / '+r.counts.products+' 张成品 / '+r.counts.requires_review+' 张待审核';article.append(p);host.append(article);}if(!rows.length)host.textContent='暂无已生成的体测成品。';}
document.getElementById('login').onsubmit=async e=>{e.preventDefault();const r=await fetch('/api/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({token:document.getElementById('token').value})});if(r.ok){document.getElementById('token').value='';document.getElementById('login').hidden=true;document.getElementById('status').textContent='';await load();}else document.getElementById('status').textContent='访问码不正确或尝试过多';};load().catch(e=>document.getElementById('status').textContent=e.message);
</script></html>''')

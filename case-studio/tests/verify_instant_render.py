"""Integration check on an explicit isolated prepared job; no inference/model calls."""
import argparse, json, subprocess, time, copy
from pathlib import Path
import playwright
from fastapi.testclient import TestClient
from studio import store,review,presentation,config
from studio.render_materials import load
from studio.common import save,read,PYTHON,WEB_DATA
import app

parser=argparse.ArgumentParser();parser.add_argument('--job',required=True);parser.add_argument('--out',required=True);args=parser.parse_args()
assert WEB_DATA.name!='website','Use isolated QA storage'
root=Path(args.out);root.mkdir(parents=True,exist_ok=True)
m=copy.deepcopy(store.review(args.job,1)['members'][-1]);mid=m['id']
jid=store.create('即时遮罩保存验证',config.snapshot())['id'];store.save_review(jid,dict(members=[m]),0)
materials=load(jid,mid)
proc=subprocess.run([str(Path(playwright.__file__).parent/'driver/node'),'static/render/geometry.mjs'],input=json.dumps(dict(member=review.public(m),materials=materials,section='three_views')),text=True,capture_output=True,check=True)
manifest=json.loads(proc.stdout);edits=[];target=None
for g in manifest['groups']:
    for p in g['panels']:
        for f in p['faces']:
            edits.append(dict(scope=g['scope'],asset_id=p['asset_id'],face=f['source_face'],position=None,deleted=False))
            if target is None and not f['back_disabled']:target=len(edits)-1
assert target is not None
edits[target]['deleted']=True
client=TestClient(app.app,headers={'Origin':'http://testserver'})
client.post('/api/session',json={'code':config.load()['access_token']}).raise_for_status()
url=f'/api/jobs/{jid}/members/{mid}/mask-editor'
payload=dict(version=1,section='three_views',fingerprint='instant-v1',edits=edits)
bad=copy.deepcopy(payload);bad['edits'][target]['position']=[2,2]
assert client.patch(url,json=bad).status_code==400
start=time.monotonic();response=client.patch(url,json=payload);response.raise_for_status();elapsed=time.monotonic()-start
assert response.json()['version']==2
assert client.patch(url,json=payload).status_code==409
save(root/'review.json',presentation.freeze(store.review(jid)),True)
subprocess.run([PYTHON,'-m','studio.bridge','render',str(root/'review.json'),mid,str(root/'output'),'three_views'],check=True)
r=read(root/'output/result.json');p=next(p for p in r['products'] if p['kind']=='three_views')
panel=next(p for p in p['privacy_layout']['panels'] if p['asset_id']==edits[target]['asset_id']);face=next(f for f in panel['faces'] if f['source_face']==edits[target]['face'])
assert face['deleted']
assert all(f['back_disabled'] for panel in p['privacy_layout']['panels'] if panel['back'] for f in panel['faces'])
result=dict(job=jid,edit_count=len(edits),save_seconds=elapsed,invalid_position=400,version_conflict=409,export_matches_manual_delete=True,back_mask_off=True)
save(root/'validation.json',result,True);print(result)

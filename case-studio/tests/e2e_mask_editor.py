"""Run against a prepared review in an isolated STUDIO_WEB_DATA (no model calls)."""
import argparse, copy, shutil
from pathlib import Path
from fastapi.testclient import TestClient
from studio import config, store
from studio.common import WEB_DATA, read, save
import app

parser=argparse.ArgumentParser()
parser.add_argument('--review',required=True)
parser.add_argument('--source-web',required=True)
parser.add_argument('--member',default='m009')
args=parser.parse_args()
assert WEB_DATA.name!='website','Use isolated test storage'
store.initialize()
member=next(m for m in read(args.review)['members'] if m['id']==args.member)
sid=member['privacy']['sticker_id']
shutil.copytree(Path(args.source_web)/'stickers'/sid,WEB_DATA/'stickers'/sid,dirs_exist_ok=True)
job=store.create('mask-editor-qa',config.snapshot());jid=job['id'];mid=member['id']
store.save_review(jid,dict(members=[member]),0)
url=f'/api/jobs/{jid}/members/{mid}/mask-editor'
with TestClient(app.app,headers={'Origin':'http://testserver'}) as client:
    assert client.post(url,json={'version':1,'section':'three_views'}).status_code==401
    client.post('/api/session',json={'code':config.load()['access_token']}).raise_for_status()
    response=client.post(url,json={'version':1,'section':'three_views'});response.raise_for_status()
    manifest=response.json()
    assert len(manifest['groups'])==1 and len(manifest['groups'][0]['panels'])==6
    assert 'sticker_file' not in manifest
    for panel in manifest['groups'][0]['panels']:
        assert 'file' not in panel
        assert client.get(f'/api/jobs/{jid}/media/'+panel['media']).status_code==200
    edits=[]
    for group in manifest['groups']:
        for panel in group['panels']:
            for face in panel['faces']:
                edits.append(dict(scope=group['scope'],asset_id=panel['asset_id'],face=face['source_face'],position=face['manual_position'],deleted=face['deleted']))
    panel=manifest['groups'][0]['panels'][0];face=panel['faces'][0]
    edits[0]['position']=[face['default_rect'][0]/panel['size'][0]+.02,face['default_rect'][1]/panel['size'][1]+.01]
    edits[1]['deleted']=True
    payload=dict(version=1,section='three_views',fingerprint=manifest['fingerprint'],edits=edits)
    response=client.patch(url,json=payload);response.raise_for_status();assert response.json()['version']==2
    assert client.patch(url,json=payload).status_code==409
    changed=store.review(jid);save(WEB_DATA/'edited-review.json',changed,True)
    baseline=copy.deepcopy(member);updated=copy.deepcopy(changed['members'][0]);updated.pop('mask_edits')
    assert updated==baseline
    print('API editor load/save and revision conflict verified',flush=True)
    response=client.post(f'/api/jobs/{jid}/preview/{mid}',json={'version':2,'section':'three_views'});response.raise_for_status()
    product=response.json()['products'][0];layout=product['privacy_layout']
    assert layout['panels'][1]['faces'][0]['deleted']
    assert layout['panels'][0]['faces'][0]['manual_position']==edits[0]['position']
    save(WEB_DATA/'validation.json',{'job':jid,'member':mid,'version':2,'layout':layout,'review_unchanged_except_mask_edits':True},True)
    print('Final six-photo preview preserves independent move/delete',flush=True)

"""Benchmark a previous e2e_mask_editor run in isolated storage, never production."""
import json, time
from fastapi.testclient import TestClient
from studio import store, config, review
from studio.common import WEB_DATA, read, save
import app

assert WEB_DATA.name != 'website', 'Use isolated QA data'
validation=read(WEB_DATA/'validation.json');jid=validation['job'];mid=validation['member']
results={}
def measure(name, action):
    start=time.perf_counter();value=action();results[name]=round(time.perf_counter()-start,4);return value

with TestClient(app.app,headers={'Origin':'http://testserver'}) as client:
    client.post('/api/session',json={'code':config.load()['access_token']}).raise_for_status()
    version=store.review(jid)['version']
    def editor(section,tag):
        response=measure(tag,lambda:client.post(f'/api/jobs/{jid}/members/{mid}/mask-editor',json={'section':section,'version':version}))
        response.raise_for_status();body=response.json()
        ids=[body['sticker_media']]+[p['media'] for g in body['groups'] for p in g['panels']]
        results[tag+'_bytes']=sum(store.media_file(jid,i).stat().st_size for i in ids)
        return body
    editor('three_views','six_reopen')
    editor('vs','vs_first');editor('vs','vs_reopen')
    editor('cover','cover_first');editor('cover','cover_reopen')
    m=next(m for m in store.review(jid)['members'] if m['id']==mid)
    cover=dict(m['cover'],title='每一步都算数')
    response=measure('save_text',lambda:client.patch(f'/api/jobs/{jid}/members/{mid}?compact=true',json={'version':version,'member':{'cover':cover}}))
    response.raise_for_status();version=response.json()['version'];results['save_response_bytes']=len(response.content)
    editor('cover','cover_after_text_save')
    response=measure('cover_preview_after_edit',lambda:client.post(f'/api/jobs/{jid}/preview/{mid}',json={'version':version,'section':'cover'}))
    response.raise_for_status()
    for section in ('three_views','vs','cover'):
        response=measure(section+'_preview',lambda:client.post(f'/api/jobs/{jid}/preview/{mid}',json={'version':version,'section':section}))
        response.raise_for_status()
        results[section+'_preview_bytes']=sum(store.media_file(jid,p['media']).stat().st_size for p in response.json()['products'])
    measure('review_read',lambda:store.review(jid))
    measure('session_read',lambda:store.session_valid(client.cookies['studio_session']))
save(WEB_DATA/'performance.json',results,True)
print(json.dumps(results,ensure_ascii=False,indent=2))

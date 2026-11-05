"""Measured, provider-aware client; credentials never enter reports or caches."""
import base64
import hashlib
import json
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import cv2
import httpx

from scripts.body_scan_phase_sessions.client import ModelCallFailure


class MeasuredClient:
    def __init__(self, settings, cache, provider):
        self.settings = Path(settings)
        self.cfg = json.loads(self.settings.read_text(encoding='utf-8'))
        if not all(self.cfg.get(k) for k in ('base_url','model','api_key')):
            raise ValueError('missing_model_configuration')
        if provider not in ('qwen','deepseek'):
            raise ValueError('unsupported_provider')
        self.provider = provider; self.cache = Path(cache)
        self.cache.mkdir(parents=True, exist_ok=True)

    def ask(self, images, prompt, version):
        options = {'temperature':0, 'max_tokens':3500, 'response_format':{'type':'json_object'}}
        options.update({'enable_thinking':False} if self.provider=='qwen' else {'thinking':{'type':'disabled'}})
        identity = {'base_url':self.cfg['base_url'], 'model':self.cfg['model'], 'version':version, 'options':options}
        digest = hashlib.sha256(json.dumps(identity,sort_keys=True).encode()+prompt.encode())
        image_hashes=[]
        for im in images:
            h=hashlib.sha256(str(im.shape).encode()+im.tobytes()).hexdigest();image_hashes.append(h);digest.update(h.encode())
        key=digest.hexdigest();path=self.cache/(key+'.json');trace_path=self.cache/(key+'.trace.json')
        if path.exists() and trace_path.exists():
            return json.loads(path.read_text(encoding='utf-8')), {'cached':True,'request_count':0,'version':version,'key':key,'trace_path':str(trace_path)}
        content=[{'type':'text','text':'按上述规则检查图片，返回JSON。'}]
        for im in images:
            height,width=im.shape[:2];scale=min(1.,1280/max(height,width))
            resized=cv2.resize(im,(round(width*scale),round(height*scale)),interpolation=cv2.INTER_AREA)
            ok,data=cv2.imencode('.jpg',resized,[cv2.IMWRITE_JPEG_QUALITY,92])
            if not ok:raise ValueError('image_encoding_failed')
            content.append({'type':'image_url','image_url':{'url':'data:image/jpeg;base64,'+base64.b64encode(data).decode()}})
        payload={'model':self.cfg['model'],'messages':[{'role':'system','content':prompt},{'role':'user','content':content}],**options}
        trace={'cached':False,'request_count':0,'version':version,'key':key,'provider':self.provider,
               'requested_model':self.cfg['model'],'options':options,'image_count':len(images),'image_hashes':image_hashes,
               'prompt_sha256':hashlib.sha256(prompt.encode()).hexdigest(),'started_utc':datetime.now(timezone.utc).isoformat(),'attempts':[]}
        result=None;reason='request_failed'
        for attempt in range(2):
            if attempt:time.sleep(1)
            trace['request_count']+=1;t=time.monotonic();obs={};retry=True
            try:
                with httpx.Client(timeout=httpx.Timeout(120,connect=15),trust_env=False) as client:
                    response=client.post(self.cfg['base_url'].rstrip('/')+'/chat/completions',headers={'Authorization':'Bearer '+self.cfg['api_key']},json=payload)
                obs['http_status']=response.status_code
                if response.status_code!=200:
                    reason='http_'+str(response.status_code);retry=response.status_code in (408,429) or response.status_code>=500
                else:
                    body=response.json();choice=body['choices'][0]
                    obs.update(returned_model=body.get('model'),usage=body.get('usage',{}),finish_reason=choice.get('finish_reason'))
                    text=choice['message']['content'].strip()
                    if choice.get('finish_reason')=='length':reason='response_truncated'
                    else:
                        if text.startswith('```'):text=text.split('\n',1)[1].rsplit('```',1)[0]
                        decoded=json.loads(text)
                        if isinstance(decoded,dict):result=decoded
                        else:reason='response_not_object'
            except httpx.TimeoutException:reason='request_timeout'
            except httpx.RequestError:reason='transport_error'
            except (ValueError,KeyError,IndexError,TypeError,AttributeError):reason='invalid_json_or_response_structure'
            obs['elapsed_seconds']=round(time.monotonic()-t,4)
            if result is None:obs['error']=reason
            trace['attempts'].append(obs)
            if result is not None or not retry:break
        trace['elapsed_seconds']=round(sum(a['elapsed_seconds'] for a in trace['attempts']),4)
        trace['success']=result is not None
        # Keep failed run attempts when a later resumable sweep succeeds.
        history=self.cache/'history';history.mkdir(exist_ok=True)
        (history/(key+'.'+uuid.uuid4().hex+'.json')).write_text(
            json.dumps(trace,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        if result is not None:
            temporary=path.with_suffix('.'+uuid.uuid4().hex+'.tmp');temporary.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');temporary.replace(path)
        trace_path.write_text(json.dumps(trace,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        if result is None:raise ModelCallFailure(reason,trace)
        return result,trace

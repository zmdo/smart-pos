"""Compatible VLM cache with bounded transport recovery and sanitized diagnostics."""
import base64
import hashlib
import json
import time
import uuid

import cv2
import httpx

from scripts.body_scan.reference import VisualEvidence


class ModelCallFailure(ValueError):
    def __init__(self, reason, trace):
        super().__init__(reason)
        self.trace = trace


class EvidenceClient(VisualEvidence):
    def ask(self, images, prompt, version):
        cfg = self.config_loader()
        if not all(cfg.get(k) for k in ('base_url', 'model', 'api_key')):
            raise ModelCallFailure('model_not_configured', {'request_count': 0, 'version': version})
        digest = hashlib.sha256(version.encode()+prompt.encode())
        digest.update((cfg['base_url']+'\0'+cfg['model']).encode())
        for im in images:
            digest.update(str(im.shape).encode()+im.tobytes())
        path = self.cache/(digest.hexdigest()+'.json')
        if path.exists():
            return json.loads(path.read_text(encoding='utf-8')), {'cached': True, 'request_count': 0, 'version': version}
        content = [{'type': 'text', 'text': '按上述规则检查图片，返回JSON。'}]
        for im in images:
            h, w = im.shape[:2]; scale = min(1., 1280/max(h, w))
            im = cv2.resize(im, (round(w*scale), round(h*scale)), interpolation=cv2.INTER_AREA)
            ok, data = cv2.imencode('.jpg', im, [cv2.IMWRITE_JPEG_QUALITY, 92])
            if not ok:
                raise ModelCallFailure('image_encoding_failed', {'request_count': 0, 'version': version})
            content.append({'type': 'image_url', 'image_url': {'url': 'data:image/jpeg;base64,'+base64.b64encode(data).decode()}})
        payload = {'model': cfg['model'], 'messages': [{'role': 'system', 'content': prompt}, {'role': 'user', 'content': content}],
                   'temperature': 0, 'max_tokens': 3500, 'response_format': {'type': 'json_object'}, 'thinking': {'type': 'disabled'}}
        trace = {'cached': False, 'request_count': 0, 'version': version, 'attempts': []}
        for attempt in range(2):
            if attempt:
                time.sleep(1)
            trace['request_count'] += 1; observation = {}; started = time.monotonic(); retry = True
            result = None; error = None
            try:
                with httpx.Client(timeout=httpx.Timeout(100, connect=15), trust_env=False) as client:
                    response = client.post(cfg['base_url'].rstrip('/')+'/chat/completions',
                                           headers={'Authorization': 'Bearer '+cfg['api_key']}, json=payload)
                observation['http_status'] = response.status_code
                if response.status_code != 200:
                    error = 'model_http_'+str(response.status_code)
                    retry = response.status_code in (408, 429) or response.status_code >= 500
                else:
                    choice = response.json()['choices'][0]
                    finish = choice.get('finish_reason'); observation['finish_reason'] = finish
                    raw = choice['message']['content'].strip()
                    if finish == 'length':
                        error = 'model_response_truncated'
                    else:
                        if raw.startswith('```'):
                            raw = raw.split('\n', 1)[1].rsplit('```', 1)[0]
                        result = json.loads(raw)
                        if not isinstance(result, dict):
                            error = 'model_response_not_object'; result = None
            except httpx.TimeoutException:
                error = 'model_timeout'
            except httpx.RequestError:
                error = 'model_transport_error'
            except (ValueError, KeyError, IndexError, TypeError, AttributeError):
                error = 'model_response_invalid_json'
            observation['elapsed_seconds'] = round(time.monotonic()-started, 3)
            if error:
                observation['error'] = error
            trace['attempts'].append(observation)
            if result is not None and error is None:
                self.cache.mkdir(parents=True, exist_ok=True)
                temporary = path.with_suffix('.'+uuid.uuid4().hex+'.tmp')
                temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
                temporary.replace(path)
                return result, trace
            if not retry:
                break
        raise ModelCallFailure(error or 'model_request_failed', trace)

"""Same prompts and image pixels for full-dataset classification/background checks."""
import argparse
import importlib.util
import json
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import cv2

from scripts.body_scan.pipeline import save_json
from scripts.body_scan_phase.inputs import digest
from scripts.body_scan.background_screening import PROMPT as BACKGROUND_PROMPT, VERSION as BACKGROUND_VERSION
from .client import MeasuredClient


def is_reference(asset):
    # Only genuine store intake folders are in scope, including when a reference
    # package happens to contain a member's original photographs.
    parts=Path(asset.get('path') or asset.get('source') or '').parts
    if any(p in ('参考模板','参考模版','会员案例素材生产标准（说明文件）') for p in parts):
        return True
    if '私教会员案例项目' in parts:
        index=parts.index('私教会员案例项目')+1
        if index>=len(parts) or not parts[index].endswith('店'):
            return True
    return not (asset.get('store') or '').endswith('店')


def classifier_module(path):
    sys.path.insert(0,str(path.parent))
    spec=importlib.util.spec_from_file_location('full_eval_classifier',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def run(job_path, out, settings, provider, mode='classification', candidate_ids=None, workers=3, case_code=Path('/root/apps/case-studio')):
    job_path=Path(job_path).resolve();out=Path(out).resolve();out.mkdir(parents=True,exist_ok=True)
    module=classifier_module(case_code/'classify.py')
    assets=[a for a in json.loads(job_path.read_text(encoding='utf-8'))['assets']
            if not is_reference(a) and Path(a['path']).suffix.lower() in ('.jpg','.jpeg','.png','.webp')]
    if candidate_ids is not None:assets=[a for a in assets if a['id'] in candidate_ids]
    config={'job':str(job_path),'job_sha256':digest(job_path),'provider':provider,'mode':mode,
            'asset_ids':[a['id'] for a in assets],'workers':workers,'max_image_side':1280,'jpeg_quality':92}
    cp=out/'config.json'
    if cp.exists() and json.loads(cp.read_text())!=config:raise ValueError('sweep_resume_configuration_changed')
    save_json(cp,config);(out/'items').mkdir(exist_ok=True)
    client=MeasuredClient(settings,out/'calls',provider)
    prompt=module.SYSTEM if mode=='classification' else BACKGROUND_PROMPT
    version=module.PROMPT_VERSION+'-full-eval' if mode=='classification' else BACKGROUND_VERSION
    def work(asset):
        path=(job_path.parent/'input'/asset['path']).resolve()
        if not path.is_relative_to((job_path.parent/'input').resolve()):raise ValueError('input_path_escape')
        record={'asset_id':asset['id'],'store':asset.get('store'),'member':asset.get('member'),'source':str(path),
                'source_sha256':digest(path),'reference_material':is_reference(asset),
                'prompt_version':module.PROMPT_VERSION if mode=='classification' else BACKGROUND_VERSION}
        try:
            image=cv2.imread(str(path))
            if image is None:raise ValueError('unreadable_image')
            raw,trace=client.ask([image],prompt,version);record.update(raw=raw,trace=trace)
            if mode=='classification':
                value=module.normalize(raw);record.update(classification=value,status='classified')
            else:record.update(background=raw,status='inspected')
        except (ValueError,OSError,TypeError) as error:
            record.update(status='needs_review',reason=str(error))
            if hasattr(error,'trace'):record['trace']=error.trace
        save_json(out/'items'/(asset['id']+'.json'),record)
        return record
    rows=[]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures=[pool.submit(work,a) for a in assets]
        for future in as_completed(futures):
            row=future.result();rows.append(row)
            if len(rows)%20==0 or len(rows)==len(assets):print(provider,mode,len(rows),'/',len(assets),flush=True)
    rows.sort(key=lambda r:r['asset_id']);save_json(out/'summary.json',rows)
    save_json(out/'counts.json',{'total':len(rows),'statuses':dict(Counter(r['status'] for r in rows)),
              'kinds':dict(Counter(r.get('classification',{}).get('kind') for r in rows))})
    return rows


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--job',type=Path,required=True);parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--settings',type=Path,required=True);parser.add_argument('--provider',choices=['deepseek','qwen'],required=True)
    parser.add_argument('--mode',choices=['classification','background'],default='classification')
    parser.add_argument('--ids',type=Path);parser.add_argument('--workers',type=int,default=3)
    args=parser.parse_args();ids=set(json.loads(args.ids.read_text())) if args.ids else None
    run(args.job,args.out,args.settings,args.provider,args.mode,ids,args.workers)

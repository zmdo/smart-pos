"""Fixed pair benchmark independent of each provider's capture-session grouping."""
import argparse
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from itertools import combinations
from pathlib import Path

from scripts.body_scan.pipeline import save_json
from scripts.body_scan_phase.inputs import load
from scripts.body_scan_phase_sessions.pipeline import image_for
from scripts.body_scan_phase_sessions.evidence import (SessionEvidence, family, OBSERVE_PROMPT,
    OBSERVE_VERSION, validate_observations, direction)
from .client import MeasuredClient


def evaluate(directory, out, settings, provider, cache, workers=3):
    items, _, bindings = load(directory)
    out=Path(out); out.mkdir(exist_ok=False)
    client=MeasuredClient(settings, cache, provider);evidence=SessionEvidence(cache);evidence.ask=client.ask
    grouped=defaultdict(list)
    for item in items:grouped[(item['store'],item['member'])].append(item)
    tasks=[];controls=[]
    for key, group in sorted(grouped.items()):
        ordered=sorted(group,key=lambda r:(r['source_sha256'],r['asset_id']))
        for a,b in combinations(ordered,2):
            if family(a['view'])==family(b['view']) and a['source_sha256']!=b['source_sha256']:
                tasks.append((a,b,'same_view_candidate'))
        if len(controls)<6:
            controls.append((ordered[0],ordered[0],'identical_photo_control'))
    tasks.extend(controls)
    save_json(out/'config.json',{'input':str(Path(directory).resolve()),'provider':provider,'pairs':len(tasks),
        'forced_two_orders':True,'workers':workers,'prompt_version':OBSERVE_VERSION,'controls':len(controls)})
    save_json(out/'sources.json',bindings);(out/'items').mkdir()
    def work(index, task):
        a,b,kind=task
        images=[image_for(r,key) for r in (a,b) for key in ('source','uniform')]
        primary,first=evidence.attempt(images,OBSERVE_PROMPT,OBSERVE_VERSION,validate_observations)
        swapped,second=evidence.attempt(images[2:]+images[:2],OBSERVE_PROMPT,OBSERVE_VERSION,validate_observations)
        if primary is not None and swapped is not None:
            decision,_=evidence.compare(images)
        else:
            decision={'after':None,'strength':'none','markers':{},'reason':'model_response_unavailable'}
        row={'id':f'p{index:03d}','asset_ids':[a['asset_id'],b['asset_id']],'store':a['store'],'member':a['member'],
             'kind':kind,'view_family':family(a['view']),'primary':first,'swapped':second,'decision':decision,
             'primary_direction':direction(primary) if primary else None,
             'swapped_direction':direction(swapped) if swapped else None,
             'source_phases':[a['phase'],b['phase']],'source_phase_origins':[a['phase_source'],b['phase_source']]}
        save_json(out/'items'/(row['id']+'.json'),row);return row
    rows=[]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures=[pool.submit(work,i,task) for i,task in enumerate(tasks,1)]
        for future in as_completed(futures):
            rows.append(future.result())
            if len(rows)%10==0 or len(rows)==len(tasks):print(provider,'fixed_observations',len(rows),'/',len(tasks),flush=True)
    rows.sort(key=lambda r:r['id']);save_json(out/'summary.json',rows)
    from scripts.body_scan_phase.inputs import digest
    if any(digest(path)!=expected for path,expected in bindings.items()):raise ValueError('observation_inputs_changed')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for flag in ('input','out','settings','cache'):parser.add_argument('--'+flag,type=Path,required=True)
    parser.add_argument('--provider',choices=['deepseek','qwen'],required=True);parser.add_argument('--workers',type=int,default=3)
    a=parser.parse_args();evaluate(a.input,a.out,a.settings,a.provider,a.cache,a.workers)

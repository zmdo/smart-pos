"""Carry already measured calls into a new, strictly store-only experiment."""
import argparse
import shutil
from pathlib import Path

from scripts.body_scan.pipeline import save_json
from .metrics import read
from .sweep import is_reference


def narrow(source, target):
    source=Path(source);target=Path(target);target.mkdir(exist_ok=False)
    for name in ('local-inventory.json','remote-inventory.json'):
        shutil.copy2(source/name,target/name)
    for provider in ('deepseek','qwen'):
        for stage in ('classification','background'):
            name=stage+'-'+provider;old=source/name;new=target/name
            (new/'items').mkdir(parents=True);(new/'calls/history').mkdir(parents=True)
            rows=[r for r in read(old/'summary.json') if not is_reference(r)]
            keys=set()
            for r in rows:
                r['reference_material']=False
                if 'trace' in r:
                    key=r['trace']['key'];keys.add(key)
                    if 'trace_path' in r['trace']:r['trace']['trace_path']=str(new/'calls'/(key+'.trace.json'))
                save_json(new/'items'/(r['asset_id']+'.json'),r)
            for key in keys:
                for ending in ('.json','.trace.json'):
                    path=old/'calls'/(key+ending)
                    if path.exists():shutil.copy2(path,new/'calls'/path.name)
                for path in (old/'calls/history').glob(key+'.*.json'):
                    shutil.copy2(path,new/'calls/history'/path.name)
            config=read(old/'config.json');config['asset_ids']=[r['asset_id'] for r in rows]
            save_json(new/'config.json',config);save_json(new/'summary.json',rows)
    included={r['asset_id'] for r in read(target/'classification-deepseek/summary.json')}
    audit=read(source/'intake-audit.json');audit['items']=[r for r in audit['items'] if r['asset_id'] in included]
    audit['scope']='All store-folder still images reviewed; reference/template and instructions folders excluded in their entirety.'
    save_json(target/'intake-audit.json',audit)
    save_json(target/'scope.json',{'policy':'Only xxx店 intake folders. Exclude reference templates including original examples, and instructions.',
        'measurement_origin':str(source),'reused_only_matching_store_image_calls':True,'reference_assets_in_model_statistics':0})


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--source',type=Path,required=True);p.add_argument('--target',type=Path,required=True)
    a=p.parse_args();narrow(a.source,a.target)

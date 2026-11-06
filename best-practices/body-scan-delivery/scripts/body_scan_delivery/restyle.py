"""Render a new immutable delivery from existing labels and approved images only."""
import argparse
import copy
import re
from pathlib import Path

from .presentation import load_presentation
from .pipeline import current,read,save,bind,publish


def restyle(delivery,out,presentation=None):
    delivery=Path(delivery).resolve();out=Path(out).resolve()
    if not re.fullmatch(r'[A-Za-z0-9_-]{8,80}',out.name):raise ValueError('invalid_delivery_id')
    result,previous=current(delivery)
    source=read(delivery/'private-inputs.json')
    bind(previous/'result.json',source['bindings'])
    source['restyle_of']={'delivery_id':result['delivery_id'],'revision':result['revision']}
    source.pop('review_request_sha256',None)
    if presentation:source['presentation']=load_presentation(presentation,source['bindings'])
    out.mkdir(parents=True,exist_ok=False);(out/'revisions').mkdir()
    save(out/'private-inputs.json',source)
    return publish(out,copy.deepcopy(result['items']),source,1,previous=previous)


if __name__=='__main__':
    p=argparse.ArgumentParser(description='仅重绘成品：复用既有标签和素材，不调用任何上游节点或模型')
    p.add_argument('--delivery',type=Path,required=True)
    p.add_argument('--out',type=Path,required=True)
    p.add_argument('--presentation',type=Path)
    a=p.parse_args()
    print(restyle(a.delivery,a.out,a.presentation)['counts'])

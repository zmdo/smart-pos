"""Body-photo deliverables; fit approved frames without recropping or reshaping."""
import hashlib
import json
import re
import shutil
from collections import defaultdict
from pathlib import Path

from PIL import Image

from scripts.body_scan_contracts.labels import family
from .presentation import resolve, public_presentation
from view_comparison.render import draw_vs, VERSION as VS_RENDERER
from three_views.render import seamless_grid, VERSION as GRID_RENDERER
from single_view.render import draw_single, text, place, VERSION as SINGLE_RENDERER

RED='#E70012';BG='#F3F0EA';INK='#25382F'
VIEWS={'front':'正视','side':'侧视','back':'后视'}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def priority(row):
    return ({'human':3,'rule':2,'inferred':1,'pending':0}[row['label_kind']],row['confidence'] or 0,row['asset_id'])


def product_file(product,rows):
    clean=lambda s:re.sub(r'[\x00-\x1f/\\:"<>|?*]','_',s)[:80].strip(' .') or '未命名'
    prefix=Path('outputs')/clean(product['store'])/(clean(product['member'])+'_'+product['group_id'])
    if product['kind']=='single':
        filename=rows[0]['asset_id']+'-体测'+VIEWS[product['view']]+'图-'+rows[0]['label']+'.jpg'
    elif product['kind']=='vs':filename='会员体测'+VIEWS[product['view']]+'图（训练前VS训练后）.jpg'
    else:filename='会员体测三视图对比拼图.png'
    return str(prefix/filename)


def plan(rows):
    """All photos get singles; choose distinct-source pairs, never duplicate one."""
    grouped=defaultdict(list)
    for row in rows:grouped[(row['group_id'],row['store'],row['member'])].append(row)
    plans=[];gaps=[];selections=[]
    for (gid,store,member),members in sorted(grouped.items()):
        slots={};pairs={}
        for row in members:
            plans.append({'product_id':'single-'+row['asset_id'],'group_id':gid,'store':store,'member':member,
                          'kind':'single','view':family(row['view']),'asset_ids':[row['asset_id']]})
        for view in VIEWS:
            choices={phase:sorted((r for r in members if family(r['view'])==view and r['phase']==phase),key=priority,reverse=True)
                     for phase in ('before','after')}
            available=[(a,b) for a in choices['before'] for b in choices['after'] if a['source_sha256']!=b['source_sha256']]
            if available:
                a,b=max(available,key=lambda pair:(priority(pair[0]),priority(pair[1])))
                slots[(view,'before')]=a;slots[(view,'after')]=b;pairs[view]=[a['asset_id'],b['asset_id']]
                plans.append({'product_id':gid+'-vs-'+view,'group_id':gid,'store':store,'member':member,
                              'kind':'vs','view':view,'asset_ids':pairs[view]})
            else:
                gaps.append({'group_id':gid,'store':store,'member':member,'product':'vs-'+view,
                             'reason':'缺少不同原图构成的训练前后配对','available':{k:[r['asset_id'] for r in v] for k,v in choices.items()}})
            selections.append({'group_id':gid,'view':view,'selected':pairs.get(view,[]),
                               'all_candidates':{k:[r['asset_id'] for r in v] for k,v in choices.items()}})
        if len(pairs)==3:
            plans.append({'product_id':gid+'-three-views','group_id':gid,'store':store,'member':member,
                          'kind':'three_views','view':'all',
                          'asset_ids':[slots[(v,p)]['asset_id'] for p in ('before','after') for v in ('front','side','back')]})
        else:
            gaps.append({'group_id':gid,'store':store,'member':member,'product':'three_views','reason':'六个朝向/阶段槽位未齐',
                         'missing_views':[v for v in VIEWS if v not in pairs]})
    return plans,gaps,selections


def draw_product(product,rows,photos,font,context=None):
    if product['kind']=='three_views':return seamless_grid(rows,photos)
    if product['kind']=='vs':return draw_vs(rows,photos,font,context or resolve(product),product['view'])
    if product['kind']=='single':return draw_single(rows,photos,font,context)
    raise ValueError('unsupported_product_kind')


def render(plans,rows,photos,dest,font,previous=None,presentation=None,reports=None):
    dest=Path(dest);(dest/'outputs').mkdir(parents=True,exist_ok=True)
    lookup={r['asset_id']:r for r in rows};outputs=[];old={}
    if previous:
        old={p['product_id']:p for p in json.loads((Path(previous)/'result.json').read_text())['outputs']}
    for product in plans:
        selected=[lookup[k] for k in product['asset_ids']]
        context=resolve(product,presentation,reports) if product['kind']=='vs' else None
        flags=[]
        if product['kind']=='vs' and product['view']=='side' and len({r['view'] for r in selected})>1:
            flags.append('side_direction_labels_differ_verify_view')
        dependencies=[{k:r.get(k) for k in ('asset_id','phase','label_kind','label','review_flags')} for r in selected]
        photo_hashes=[sha(photos[r['asset_id']]) for r in selected]
        if product['kind']=='three_views':
            # Labels remain in metadata, but no longer affect image pixels.
            identity={'renderer':GRID_RENDERER,'product':product,'photo_hashes':photo_hashes}
        else:
            identity={'renderer':SINGLE_RENDERER if product['kind']=='single' else 'body-delivery-v1','product':product,'labels':dependencies,
                      'photo_hashes':photo_hashes,'font_sha256':sha(font)}
        if context:
            identity.update(renderer=VS_RENDERER,presentation=public_presentation(context))
        signature=hashlib.sha256(json.dumps(identity,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        relative=product_file(product,selected);path=dest/relative;path.parent.mkdir(parents=True,exist_ok=True)
        reused=False
        if product['product_id'] in old and old[product['product_id']]['dependency_sha256']==signature:
            source=Path(previous)/old[product['product_id']]['file']
            if sha(source)!=old[product['product_id']]['sha256']:raise ValueError('previous_product_changed')
            shutil.copy2(source,path);reused=True
        else:
            image=draw_product(product,selected,photos,font,context)
            if product['kind']=='three_views':image.save(path,format='PNG')
            else:image.save(path,quality=92,subsampling=0)
        with Image.open(path) as image:width,height=image.size
        layout=({'renderer_version':GRID_RENDERER,'layout':'seamless-3x2','image_annotations':False}
                if product['kind']=='three_views' else {})
        if product['kind']=='single':
            layout.update(renderer_version=SINGLE_RENDERER,layout='photo-only',image_annotations=False)
        if context:
            layout.update(renderer_version=VS_RENDERER,layout='reference-vs',stage_annotations=False,
                          presentation=public_presentation(context))
        outputs.append({**product,**layout,'file':relative,'width':width,'height':height,'sha256':sha(path),
            'dependency_sha256':signature,'reused':reused,'labels':[{k:r[k] for k in ('asset_id','phase','label','requires_review')} for r in selected],
            'requires_review':any(r['requires_review'] for r in selected),
            'review_asset_ids':[r['asset_id'] for r in selected if r['requires_review']], 'warnings':flags})
    return outputs

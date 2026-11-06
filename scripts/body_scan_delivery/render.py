"""Body-photo deliverables; fit approved frames without recropping or reshaping."""
import hashlib
import json
import re
import shutil
from collections import defaultdict
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

from scripts.body_scan_contracts.labels import family

RED='#E70012';BG='#F3F0EA';INK='#25382F'
VIEWS={'front':'正视','side':'侧视','back':'后视'}
GRID_RENDERER='body-three-views-seamless-v2'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def text(draw,xy,value,font,size=34,fill=INK,anchor='mm'):
    draw.text(xy,value,font=ImageFont.truetype(str(font),size),fill=fill,anchor=anchor)


def place(canvas,path,box):
    with Image.open(path) as source:
        image=ImageOps.contain(source.convert('RGB'),(box[2]-box[0],box[3]-box[1]),Image.Resampling.LANCZOS)
    canvas.paste(image,(box[0]+(box[2]-box[0]-image.width)//2,box[1]+(box[3]-box[1]-image.height)//2))


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


def seamless_grid(rows,photos):
    """Join the six approved frames at native size; add no pixels between them."""
    if len(rows)!=6:raise ValueError('three_views_requires_six_frames')
    images=[]
    for row in rows:
        with Image.open(photos[row['asset_id']]) as source:
            images.append(source.convert('RGB'))
    if len({image.size for image in images})!=1:
        raise ValueError('three_views_requires_equal_frame_sizes')
    width,height=images[0].size
    canvas=Image.new('RGB',(width*3,height*2))
    for index,image in enumerate(images):
        canvas.paste(image,((index%3)*width,(index//3)*height))
    return canvas


def draw_product(product,rows,photos,font):
    if product['kind']=='three_views':
        return seamless_grid(rows,photos)
    canvas=Image.new('RGB',(1080,1440),BG);draw=ImageDraw.Draw(canvas)
    if product['kind']=='single':
        row=rows[0];place(canvas,photos[row['asset_id']],(0,0,1080,1320))
        draw.rectangle((0,1320,1080,1440),fill='white')
        text(draw,(540,1370),VIEWS[family(row['view'])]+' · '+row['label'],font,40)
    elif product['kind']=='vs':
        draw.rectangle((0,0,1080,184),fill=RED)
        text(draw,(540,65),'UP健身私教馆',font,58,'white')
        text(draw,(540,140),'体测'+VIEWS[product['view']]+'图',font,40,'white')
        for index,row in enumerate(rows):
            place(canvas,photos[row['asset_id']],(index*540+8,192,index*540+532,1220))
        draw.rectangle((0,1220,1080,1440),fill=RED)
        for index,row in enumerate(rows):
            text(draw,(270+index*540,1273),row['label'],font,39,'white')
        member=product['member'];masked=member[:1]+'**'
        text(draw,(540,1380),product['store']+'  ·  '+masked,font,32,'white')
        draw.ellipse((489,658,591,760),fill=RED,outline='white',width=5)
        text(draw,(540,709),'VS',font,42,'white')
    else:raise ValueError('unsupported_product_kind')
    return canvas


def render(plans,rows,photos,dest,font,previous=None):
    dest=Path(dest);(dest/'outputs').mkdir(parents=True,exist_ok=True)
    lookup={r['asset_id']:r for r in rows};outputs=[];old={}
    if previous:
        old={p['product_id']:p for p in json.loads((Path(previous)/'result.json').read_text())['outputs']}
    for product in plans:
        selected=[lookup[k] for k in product['asset_ids']]
        flags=[]
        if product['kind']=='vs' and product['view']=='side' and len({r['view'] for r in selected})>1:
            flags.append('side_direction_labels_differ_verify_view')
        dependencies=[{k:r.get(k) for k in ('asset_id','phase','label_kind','label','review_flags')} for r in selected]
        photo_hashes=[sha(photos[r['asset_id']]) for r in selected]
        if product['kind']=='three_views':
            # Labels remain in metadata, but no longer affect image pixels.
            identity={'renderer':GRID_RENDERER,'product':product,'photo_hashes':photo_hashes}
        else:
            identity={'renderer':'body-delivery-v1','product':product,'labels':dependencies,
                      'photo_hashes':photo_hashes,'font_sha256':sha(font)}
        signature=hashlib.sha256(json.dumps(identity,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        relative=product_file(product,selected);path=dest/relative;path.parent.mkdir(parents=True,exist_ok=True)
        reused=False
        if product['product_id'] in old and old[product['product_id']]['dependency_sha256']==signature:
            source=Path(previous)/old[product['product_id']]['file']
            if sha(source)!=old[product['product_id']]['sha256']:raise ValueError('previous_product_changed')
            shutil.copy2(source,path);reused=True
        else:
            image=draw_product(product,selected,photos,font)
            if product['kind']=='three_views':image.save(path,format='PNG')
            else:image.save(path,quality=92,subsampling=0)
        with Image.open(path) as image:width,height=image.size
        layout=({'renderer_version':GRID_RENDERER,'layout':'seamless-3x2','image_annotations':False}
                if product['kind']=='three_views' else {})
        outputs.append({**product,**layout,'file':relative,'width':width,'height':height,'sha256':sha(path),
            'dependency_sha256':signature,'reused':reused,'labels':[{k:r[k] for k in ('asset_id','phase','label','requires_review')} for r in selected],
            'requires_review':any(r['requires_review'] for r in selected),
            'review_asset_ids':[r['asset_id'] for r in selected if r['requires_review']], 'warnings':flags})
    return outputs

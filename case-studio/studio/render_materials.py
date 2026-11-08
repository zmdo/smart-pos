"""Prepare immutable, path-free inputs for the shared browser/worker renderer."""
import copy, itertools
from pathlib import Path
from PIL import Image, ImageOps
from .common import save, read, signature, cache_dir, PYTHON, sha
from . import store, fonts, presentation, privacy, stickers
from .work_cache import lock_for, EDITOR_SLOTS

VERSION = 'instant-materials-v1'
IDENTITY = [[1,0,0],[0,1,0],[0,0,1]]


def build(member, folder):
    # Imports stay inside the isolated bridge, outside GPU/model module namespaces.
    from .rendering import panel_head_points, crop_from_plan, plan_pair, project
    from scripts.body_scan_delivery.logo import load_logo
    from .privacy_panels import project_faces
    eng = member['_engine']
    folder.mkdir(parents=True, exist_ok=True)
    files = {}
    def asset(path):
        path = str(Path(path).resolve())
        key = signature(path)[:24]
        files[key] = path
        return key
    def source(aid, path, transform=IDENTITY, size=None):
        with Image.open(path) as im:
            native = ImageOps.exif_transpose(im).size
        evidence = eng.get('privacy', {}).get('sources', {}).get(str(path))
        valid = bool(evidence and eng.get('privacy', {}).get('version') == privacy.VERSION
                     and sha(path) == evidence.get('source_sha256'))
        result = dict(size=list(size or native), source_hash=sha(path),
                      head_points=panel_head_points(member,aid,path,transform),
                      faces=project_faces(evidence,native,transform,size or native) if valid else [],
                      checked=valid, evidence_faces=evidence['faces'] if valid else [])
        return result
    photos = {}
    for aid, path in eng['photos'].items():
        photos[aid] = dict(source(aid,path), image=asset(path))
        ed = eng.get('editors', {}).get(aid)
        if ed:
            l,t,r,b = ed['bounds']
            polygon = project([[l,t],[r,t],[r,b],[l,b]],ed['H']).tolist()
            photos[aid]['cover'] = dict(source(aid,ed['source'],ed['H'],ed['size']),
                image=asset(ed['path']), default_crop=ed['default_crop'], polygon=polygon,
                source_transform=ed['H'])
    pairs = {}
    for a,b in itertools.combinations(eng.get('editors',{}),2):
        try:
            frames = plan_pair([eng['metadata'][a],eng['metadata'][b]])
            crops = {aid:crop_from_plan(frame,eng['editors'][aid]['H'],eng['editors'][aid]['size'])
                     for aid,frame in zip((a,b),frames)}
            pairs['|'.join(sorted((a,b)))] = dict(crops=crops)
        except ValueError as exc:
            pairs['|'.join(sorted((a,b)))] = dict(error=str(exc))
    logo = None
    if eng.get('logo'):
        path = folder/'logo.png'
        load_logo(eng['logo'],(1000,240)).save(path)
        logo = asset(path)
    sticker = None
    sid = member.get('privacy',{}).get('sticker_id')
    if sid:
        with Image.open(stickers.get(sid)['path']) as im:
            im = im.convert('RGBA'); im = im.crop(im.getchannel('A').getbbox())
            native_size=list(im.size)
            path=folder/'avatar.png'; im.save(path)
            sticker=dict(image=asset(path),size=native_size)
    result=dict(renderer=VERSION, photos=photos, pairs=pairs, logo=logo, sticker=sticker,
                sticker_scale=privacy.STICKER_SCALE,
                reports={k:dict(image=asset(p),size=list(Image.open(p).size)) for k,p in eng.get('report_images',{}).items()},
                dates=(eng.get('table') or {}).get('pair') or {}, files=files)
    result['legacy_masks'] = legacy_masks(member, result)
    save(folder/'materials.json',result,True)
    return result


def legacy_masks(member, materials):
    """Keep existing manual edits only if their original geometry still matches."""
    edits=member.get('mask_edits',{})
    if not edits:return []
    from .rendering import plan, manual_plan, plan_pair
    from view_comparison.render import geometry
    eng=member['_engine'];rows=[];public={p['asset_id']:p for p in member['photos']}
    for original in eng['rows']:
        p=public[original['asset_id']];r=dict(original,phase=p['phase'],view=p['view'])
        if p.get('preferred') or p['confirmed']:r.update(label_kind='human',confidence=1.0 if p.get('preferred') else .99)
        rows.append(r)
    products=plan(rows)[0]
    front=next((p for p in products if p['kind']=='vs' and p['view']=='front'),None)
    if front:products.append(dict(front,kind='cover'))
    result=[];prefs=member.get('_render_settings') or presentation.settings();width=prefs['output_width']
    for p in products:
        scope=p['kind']+':'+p['view']
        if scope not in edits:continue
        ids=p['asset_ids'];sizes=[materials['photos'][a]['size'] for a in ids]
        boxes=geometry(sizes,width,len(member['vs']['metrics']),width*4//3)['photo_boxes'] if p['kind']=='vs' else None
        logical=geometry(sizes,1080,len(member['vs']['metrics']),1440)['photo_boxes'] if boxes else None
        try:
            defaults=plan_pair([eng['metadata'][a] for a in ids]) if p['kind']=='cover' else None
            for i,aid in enumerate(ids):
                if aid not in edits[scope]:continue
                crop=None;back=public[aid]['view']=='back'
                if defaults:
                    ed=eng['editors'][aid];crop=member['cover']['crops'].get(aid) or materials['pairs']['|'.join(sorted(ids))]['crops'][aid]
                    frame=manual_plan(ed,crop) if aid in member['cover']['crops'] else defaults[i]
                    transform=frame['H_source_to_cover'];size=logical_size=[500,478];source=eng['metadata'][aid]['source'];back=False
                else:
                    source=eng['photos'][aid];w,h=sizes[i]
                    size=[boxes[i][2]-boxes[i][0],boxes[i][3]-boxes[i][1]] if boxes else [w,h]
                    logical_size=[logical[i][2]-logical[i][0],logical[i][3]-logical[i][1]] if logical else size
                    transform=[[size[0]/w,0,0],[0,size[1]/h,0],[0,0,1]]
                evidence=privacy.checked_evidence(member,source)
                sig=signature(dict(source=evidence['source_sha256'],faces=evidence['faces'],transform=transform,size=size,back=back))
                if sig==edits[scope][aid]['signature']:
                    result.append(dict(scope=scope,asset_id=aid,signature=sig,size=logical_size,crop=crop,back=back))
        except (ValueError,KeyError):
            continue
    return result


def key(member):
    e=member['_engine']
    legacy={s:{a:v for a,v in ps.items() if not v.get('signature','').startswith('canvas-v1:')} for s,ps in member.get('mask_edits',{}).items()}
    return signature(dict(version=VERSION,engine={k:e.get(k) for k in ('photos','editors','metadata','privacy','report_images','table','logo')},legacy={k:v for k,v in legacy.items() if v},
                          sticker=member.get('privacy',{}).get('sticker_id')))


def load(jid, mid):
    from .workflow import command
    data=store.review(jid)
    member=next(m for m in data['members'] if m['id']==mid)
    fingerprint=key(member)
    base=cache_dir(jid)/'instant-materials'/mid/fingerprint
    with lock_for(str(base)):
        if not (base/'output/materials.json').exists():
            save(base/'review.json', data, True)
            with EDITOR_SLOTS:
                command(jid,[PYTHON,'-m','studio.bridge','materials',base/'review.json',mid,base/'output'],base/'prepare.log')
        result=read(base/'output/materials.json')
    result['assets']={k:f'/api/jobs/{jid}/media/{store.media(jid,p)}' for k,p in result.pop('files').items()}
    result['fingerprint']=fingerprint
    return result

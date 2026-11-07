"""Deterministic privacy masking and safe rectangular framing of original pixels."""
import math
from PIL import Image

def pixels(bounds,size,padding=0):
    w,h=size;l,t,r,b=bounds
    return [max(0,math.floor(l*w/1000-padding)),max(0,math.floor(t*h/1000-padding)),
            min(w,math.ceil(r*w/1000+padding)),min(h,math.ceil(b*h/1000+padding))]

def subtract(rect,protected):
    l,t,r,b=rect;pl,pt,pr,pb=protected
    il,it,ir,ib=max(l,pl),max(t,pt),min(r,pr),min(b,pb)
    if il>=ir or it>=ib:return [rect]
    return [x for x in ([l,t,r,it],[l,ib,r,b],[l,it,il,ib],[ir,it,r,ib]) if x[0]<x[2] and x[1]<x[3]]

def mask_regions(evidence,size):
    result=[];protected=[pixels(b,size,2) for b in (evidence['protected_regions']+evidence.get('text_regions',[])+evidence.get('coach_avatar_regions',[]))]
    for region in evidence['privacy_regions']:
        padding=max(4,round(min(size)*.006));rect=pixels(region['bbox'],size,padding);pieces=[rect]
        if region['kind'] not in ('member_avatar','person_photo'):raise ValueError('unsupported_privacy_scope')
        # A photo used as a right-side avatar remains an avatar. Discard its
        # whole duplicate mask rather than mosaicking a thin detection rim.
        l,t,r,b=pixels(region['bbox'],size)
        if any(max(0,min(r,cr)-max(l,cl))*max(0,min(b,cb)-max(t,ct)) >= (r-l)*(b-t)*.5
               for cl,ct,cr,cb in (pixels(box,size,2) for box in evidence.get('coach_avatar_regions',[]))):
            continue
        for keep in protected:pieces=[p for piece in pieces for p in subtract(piece,keep)]
        for piece in pieces:result.append({'kind':region['kind'],'box':piece})
    return result

def mosaic(im,regions):
    result=im.copy()
    for region in regions:
        l,t,r,b=region['box']
        if l>=r or t>=b:continue
        if region['kind'] not in ('member_avatar','person_photo'):raise ValueError('unsupported_privacy_scope')
        cells=4
        patch=result.crop((l,t,r,b))
        low=patch.resize((min(cells,r-l),min(cells,b-t)),Image.Resampling.BOX)
        result.paste(low.resize(patch.size,Image.Resampling.NEAREST),(l,t))
    return result

def crop_for_frame(evidence,size,aspect):
    w,h=size
    required=pixels(evidence['main_bbox'],size,max(3,round(min(size)*.006)))
    for box in evidence['protected_regions']:
        p=pixels(box,size,2);required=[min(required[0],p[0]),min(required[1],p[1]),max(required[2],p[2]),max(required[3],p[3])]
    allowed=pixels(evidence['usable_bbox'],size)
    allowed=[min(allowed[0],required[0]),min(allowed[1],required[1]),max(allowed[2],required[2]),max(allowed[3],required[3])]
    rw,rh=required[2]-required[0],required[3]-required[1];aw,ah=allowed[2]-allowed[0],allowed[3]-allowed[1]
    cw=max(rw,math.ceil(rh*aspect));ch=math.ceil(cw/aspect);mode='cover_protected'
    if cw>aw or ch>ah:
        mode='contain_protected'
        if cw>aw:cw=aw;ch=max(rh,min(ah,math.ceil(cw/aspect)))
        if ch>ah:ch=ah;cw=max(rw,min(aw,math.ceil(ch*aspect)))
    left=round((required[0]+required[2]-cw)/2);top=round((required[1]+required[3]-ch)/2)
    left=max(allowed[0],required[2]-cw,min(left,required[0],allowed[2]-cw))
    top=max(allowed[1],required[3]-ch,min(top,required[1],allowed[3]-ch))
    crop=[left,top,left+cw,top+ch]
    assert 0<=left<left+cw<=w and 0<=top<top+ch<=h
    assert left<=required[0] and top<=required[1] and left+cw>=required[2] and top+ch>=required[3]
    return crop,{'mode':mode,'protected_bounds':required,'main_content_fraction':round(rw*rh/(cw*ch),6)}

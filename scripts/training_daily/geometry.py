"""Rectangular action-preserving crops; never stretch or warp people."""
import math


def pixels(box,size):
    w,h=size;l,t,r,b=box
    return [max(0,math.floor(l*w/1000)),max(0,math.floor(t*h/1000)),
            min(w,math.ceil(r*w/1000)),min(h,math.ceil(b*h/1000))]


def plan(record,size,frame,settings):
    if record['status']!='accepted':
        return {'passed':False,'reason':record.get('reason','素材未通过复核'),'code':'evidence_not_accepted'}
    usable=pixels(record['usable_bbox'],size)
    boxes=[pixels(record['action_bbox'],size),pixels(record['subject_bbox'],size)]
    boxes.extend(pixels(x['bbox'],size) for x in record['protected_boxes'])
    required=[min(b[0] for b in boxes),min(b[1] for b in boxes),max(b[2] for b in boxes),max(b[3] for b in boxes)]
    if not (usable[0]<=required[0]<required[2]<=usable[2] and usable[1]<=required[1]<required[3]<=usable[3]):
        return {'passed':False,'reason':'动作保护范围超出有效照片区域','code':'invalid_geometry'}
    aw,ah=usable[2]-usable[0],usable[3]-usable[1]
    margin=round(min(aw,ah)*settings['action_margin'])
    required=[max(usable[0],required[0]-margin),max(usable[1],required[1]-margin),
              min(usable[2],required[2]+margin),min(usable[3],required[3]+margin)]
    rw,rh=required[2]-required[0],required[3]-required[1]
    aspect=frame[2]/frame[3];cw=max(rw,math.ceil(rh*aspect));ch=math.ceil(cw/aspect);mode='fill'
    if cw>aw or ch>ah:
        mode='inset'
        if cw>aw:cw=aw;ch=max(rh,min(ah,math.ceil(cw/aspect)))
        if ch>ah:ch=ah;cw=max(rw,min(aw,math.ceil(ch*aspect)))
    subject=pixels(record['subject_bbox'],size)
    x=round((subject[0]+subject[2]-cw)/2);y=round((required[1]+required[3]-ch)/2)
    x=max(usable[0],required[2]-cw,min(x,required[0],usable[2]-cw))
    y=max(usable[1],required[3]-ch,min(y,required[1],usable[3]-ch))
    scale=min(frame[2]/cw,frame[3]/ch);pw,ph=round(cw*scale),round(ch*scale)
    px=frame[0]+(frame[2]-pw)//2;py=frame[1]+(frame[3]-ph)//2
    area_ratio=pw*ph/(frame[2]*frame[3]);short_side=min(cw,ch)
    issues=[]
    if short_side<settings['min_crop_short_side']:issues.append('有效照片像素不足，放大后难以看清动作')
    if scale>settings['max_upscale']:issues.append('所需放大超过清晰度上限')
    if area_ratio<settings['min_photo_area']:issues.append('有效动作画面过窄，无法成为成品主体')
    return {'passed':not issues,'reason':'；'.join(issues),'code':'insufficient_picture' if issues else '',
            'crop':[x,y,x+cw,y+ch],'usable':usable,'required':required,'mode':mode,
            'frame':frame,'placement':[px,py,pw,ph],'uniform_scale':scale,
            'photo_area_ratio':round(area_ratio,6),'source_short_side':short_side,
            'action_preserved':True,'source_cutoff_parts':record.get('source_cutoff_parts',[])}

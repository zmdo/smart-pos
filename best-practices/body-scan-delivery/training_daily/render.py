"""Frameless training photos, with native-pixel and original-file fallbacks."""
from pathlib import Path
import shutil
import numpy as np
from PIL import Image,ImageFilter,ImageOps
from .geometry import pixels
from .routing import choose_plan

DEFAULTS={'width':1080,'height':1440,'border':0,'accent':'#e60012',
          'action_margin':.025,'min_crop_short_side':380,'max_upscale':1.8,'min_photo_area':.45,
          'max_per_member':3,'enhance':True,'background_strength':.06,
          'shadow_lift':.06,'highlight_compression':.08,'sharpen_percent':28,
          'inset_background':'soft','logo_path':None}


def settings(config):
    result={**DEFAULTS,**config}
    # Borderless is a product rule, including when replaying an older config.
    result['border']=0
    bounds={'width':(720,2400),'height':(960,3200),'border':(0,24),'action_margin':(0,.08),
            'min_crop_short_side':(100,1200),'max_upscale':(1,2.5),'min_photo_area':(.35,.9),
            'max_per_member':(1,6),'background_strength':(0,.12),'shadow_lift':(0,.12),
            'highlight_compression':(0,.15),'sharpen_percent':(0,50)}
    for key,(low,high) in bounds.items():
        value=result[key]
        if isinstance(value,bool) or not isinstance(value,(int,float)) or not np.isfinite(value) or not low<=value<=high:
            raise ValueError('invalid_setting:'+key)
    for key in ('width','height','border','max_per_member','sharpen_percent'):
        if result[key]!=int(result[key]):raise ValueError('setting_must_be_integer:'+key)
        result[key]=int(result[key])
    if result['height']<result['width'] or result['inset_background'] not in ('soft','solid') or not isinstance(result['enhance'],bool):
        raise ValueError('invalid_canvas_or_style')
    return result


def frame_for(config):
    w,h,b=config['width'],config['height'],0
    # Optional logo occupies its own footer, never overlays an action or a foot.
    footer=round(w*.09) if config.get('logo_path') else 0
    return [b,b,w-2*b,h-2*b-footer]


def protection(size,bounds,feather):
    """Protect the entire action rectangle; effects only fade in outside it."""
    w,h=size;l,t,r,b=bounds
    xs=np.arange(w,dtype=np.float32);ys=np.arange(h,dtype=np.float32)
    dx=np.maximum(np.maximum(l-xs,xs-(r-1)),0)
    dy=np.maximum(np.maximum(t-ys,ys-(b-1)),0)
    distance=np.hypot(dy[:,None],dx[None,:])
    return 1-np.clip(distance/max(1,feather),0,1)


def enhance(im,record,crop,config):
    if not config['enhance']:
        return im.copy(),{'enabled':False,'geometry_warp':False}
    arr=np.asarray(im,dtype=np.float32)/255
    original_y=arr@np.array([.2126,.7152,.0722],dtype=np.float32)
    wb=np.ones(3,dtype=np.float32)
    if record.get('cast_confidence',0)>=.85:
        wb=np.array({'neutral':[1,1,1],'yellow':[.99,1,1.025],'green':[1.015,.985,1.015],
                     'blue':[1.02,1,.985],'magenta':[.99,1.015,.99]}[record['color_cast']],dtype=np.float32)
    arr=np.clip(arr*wb,0,1)
    ev={'balanced':.04,'dark':.20,'backlit':.16,'bright':-.04}[record['lighting']]
    arr=np.clip(arr*(2**ev),0,1)
    y=arr@np.array([.2126,.7152,.0722],dtype=np.float32)
    lift=config['shadow_lift']*(1-y)**2*y/(y+.12)
    compress=config['highlight_compression']*np.clip((y-.70)/.30,0,1)**2
    arr=np.clip(arr+(lift-compress)[...,None],0,1)
    # Mild denoising only for visibly noisy dark regions; blend, never synthesize detail.
    if record.get('noise')=='high':
        smooth=np.asarray(Image.fromarray(np.uint8(arr*255)).filter(ImageFilter.GaussianBlur(.55)),dtype=np.float32)/255
        amount=.18*np.clip((.35-original_y)/.35,0,1)
        arr=arr*(1-amount[...,None])+smooth*amount[...,None]
    action=pixels(record['action_bbox'],record['source_size'])
    local=[action[0]-crop[0],action[1]-crop[1],action[2]-crop[0],action[3]-crop[1]]
    protected=protection(im.size,local,min(im.size)*.08)
    bg=(1-protected)*config['background_strength']
    gray=arr@np.array([.2126,.7152,.0722],dtype=np.float32)
    arr=(arr*(1-bg[...,None])+gray[...,None]*bg[...,None])*(1-bg[...,None]*.7)
    result=Image.fromarray(np.uint8(np.clip(arr*255,0,255)))
    if config['sharpen_percent']:
        result=result.filter(ImageFilter.UnsharpMask(radius=.75,percent=config['sharpen_percent'],threshold=4))
    return result,{'enabled':True,'exposure_ev':ev,'white_balance_gains':[round(float(x),4) for x in wb],
                   'shadow_lift':config['shadow_lift'],'highlight_compression':config['highlight_compression'],
                   'background_strength':config['background_strength'],'background_method':'feathered_action_rectangle',
                   'sharpen_percent':config['sharpen_percent'],'denoise':record.get('noise')=='high',
                   'geometry_warp':False,'skin_reshape':False}


def render(path,record,out,config):
    with Image.open(path) as raw:original=ImageOps.exif_transpose(raw).convert('RGB')
    geometry=choose_plan(record,original,frame_for(config),config)
    if not geometry['passed']:return geometry
    out=Path(out);out.parent.mkdir(parents=True,exist_ok=True)
    if geometry['mode'] in ('native_crop','original_passthrough'):
        if geometry['mode']=='original_passthrough':
            output=out.with_suffix(Path(path).suffix.lower());shutil.copy2(path,output)
            w,h=original.size
        else:
            output=out.with_suffix('.png');photo=original.crop(geometry['crop']);photo.save(output)
            w,h=photo.size
        return dict(geometry,tone={'enabled':False,'geometry_warp':False,'skin_reshape':False},width=w,height=h,
                    files={'file':output.name,'preview':output.name,'before':None})
    crop=original.crop(geometry['crop']);treated,tone=enhance(crop,record,geometry['crop'],config)
    canvas=Image.new('RGB',(config['width'],config['height']),'#ebe8e3')
    x,y,w,h=geometry['frame'];px,py,pw,ph=geometry['placement']
    if geometry['mode']=='inset' and config['inset_background']=='soft':
        # Very blurred, low-contrast background is decoration only; the sharp action stays whole.
        back=ImageOps.fit(treated,(w,h)).filter(ImageFilter.GaussianBlur(max(w,h)*.06))
        back=Image.blend(back,Image.new('RGB',back.size,'#ebe8e3'),.70)
        canvas.paste(back,(x,y))
    else:canvas.paste('#ebe8e3',(x,y,x+w,y+h))
    canvas.paste(treated.resize((pw,ph),Image.Resampling.LANCZOS),(px,py))
    if config.get('logo_path'):
        top=y+h;canvas.paste('#f9f7f4',(x,top,x+w,config['height']-config['border']))
        with Image.open(config['logo_path']) as raw:logo=raw.convert('RGBA')
        logo.thumbnail((round(w*.30),round((config['height']-config['border']-top)*.65)))
        canvas.paste(logo,(x+(w-logo.width)//2,top+(config['height']-config['border']-top-logo.height)//2),logo)
    canvas.save(out);canvas.save(out.with_suffix('.jpg'),quality=94,subsampling=0)
    # QA pair uses the same crop/scale so lighting changes can be assessed fairly.
    before=Image.new('RGB',canvas.size,'#ebe8e3')
    before.paste(crop.resize((pw,ph),Image.Resampling.LANCZOS),(px,py))
    before.save(out.with_name(out.stem+'-before.jpg'),quality=92)
    thumb=original.copy();thumb.thumbnail((720,960));thumb.save(out.with_name(out.stem+'-source.jpg'),quality=90)
    return dict(geometry,tone=tone,width=canvas.width,height=canvas.height,
                files={'file':out.name,'preview':out.with_suffix('.jpg').name,'before':out.stem+'-before.jpg'})

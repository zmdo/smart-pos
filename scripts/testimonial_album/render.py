"""Render original screenshot pixels into a scored album; no model calls."""
import math
from pathlib import Path
from PIL import Image,ImageDraw,ImageFont,ImageOps
from .policy import choose_layout
from . import PRIVACY_POLICY
from .privacy import crop_for_frame,mask_regions,mosaic

def load_font(path,size,weight=700):
    font=ImageFont.truetype(str(path),max(8,round(size)))
    try:
        axes=font.get_variation_axes()
        font.set_variation_by_axes([max(a['minimum'],min(a['maximum'],weight)) if a['name']==b'Weight' else a['default'] for a in axes])
    except (OSError,AttributeError):pass
    return font

def pixel_box(bounds,size):
    w,h=size;x1,y1,x2,y2=bounds
    # Add a safety rim so imprecise model boxes do not hug the glyphs.
    return [max(0,math.floor(x1*w/1000-w*.008)),max(0,math.floor(y1*h/1000-h*.006)),
            min(w,math.ceil(x2*w/1000+w*.008)),min(h,math.ceil(y2*h/1000+h*.006))]

def open_crop(path,bounds):
    with Image.open(path) as raw:im=ImageOps.exif_transpose(raw).convert('RGB')
    crop=pixel_box(bounds,im.size)
    return im.crop(tuple(crop)),crop,im.size

# Match the red-border v1 title sizes. Only the global canvas width scales them.
BRAND_PRESETS={
    'horizontal':{'icon_width':193.6,'title_font_px':97,'brand_font_px':29},
    'vertical':{'icon_width':145.6,'title_font_px':69,'brand_font_px':13},
}

class UnsuitableScreenshot(ValueError):
    def __init__(self,assessment):
        super().__init__(assessment['reason']);self.assessment=assessment

def brand_metrics(canvas_width,orientation):
    unit=canvas_width/1080
    return dict(orientation=orientation,icon_width=BRAND_PRESETS[orientation]['icon_width']*unit,
                title_font_px=round(BRAND_PRESETS[orientation]['title_font_px']*unit),
                brand_font_px=round(BRAND_PRESETS[orientation]['brand_font_px']*unit))

def draw_brand(canvas,rect,font_path,config,orientation=None):
    x,y,w,h=rect;draw=ImageDraw.Draw(canvas);red=config.get('accent','#e60012')
    draw.rounded_rectangle((x,y,x+w,y+h),radius=12,fill='#fffdf9')
    title=config.get('title','会员感言');brand=config.get('brand','UP 健身私教馆');elements=[]
    orientation=orientation or ('horizontal' if w>=h*1.6 else 'vertical')
    metrics=brand_metrics(canvas.width,orientation);unit=canvas.width/1080
    title_font=load_font(font_path,metrics['title_font_px'])
    brand_font=load_font(font_path,metrics['brand_font_px'],450)
    if draw.textlength(brand,font=brand_font)>w-24*unit:raise ValueError('brand_text_too_long_for_canvas')
    draw.line((x+w*.18,y+16*unit,x+w*.82,y+16*unit),fill=red,width=max(2,round(2*unit)))

    def text_center(text,font,cx,top,role):
        b=draw.textbbox((0,0),text,font=font);tw,th=b[2]-b[0],b[3]-b[1]
        left=cx-tw/2;draw.text((left-b[0],top-b[1]),text,font=font,fill=red if role=='title' else '#8a7770')
        elements.append({'role':role,'bounds':[left,top,left+tw,top+th],'font_px':font.size})
    def envelope(left,top,ew):
        eh=ew*.64
        draw.rounded_rectangle((left,top,left+ew,top+eh),radius=ew*.055,fill='#dce5eb')
        draw.polygon([(left,top),(left+ew/2,top+eh*.66),(left+ew,top)],fill='#edf2f5')
        draw.polygon([(left,top+eh),(left+ew/2,top+eh*.42),(left+ew,top+eh)],fill='#c6d4de')
        cx=left+ew/2;cy=top+eh*.52;r=ew*.115
        draw.ellipse((cx-2*r,cy-r,cx,cy+r),fill=red);draw.ellipse((cx,cy-r,cx+2*r,cy+r),fill=red)
        draw.polygon([(cx-2*r,cy),(cx+2*r,cy),(cx,cy+2.6*r)],fill=red)
        elements.append({'role':'icon','bounds':[left,top,left+ew,top+eh]})
    ew=metrics['icon_width']
    if orientation=='horizontal':
        gap=42*unit
        tb=draw.textbbox((0,0),title,font=title_font);bb=draw.textbbox((0,0),brand,font=brand_font)
        th=tb[3]-tb[1];bh=bb[3]-bb[1];textw=max(tb[2]-tb[0],bb[2]-bb[0])
        totalw=ew+gap+textw;totalh=max(ew*.64,th+bh+18*unit)
        if totalw>w-24*unit or totalh>h-24*unit:raise ValueError('fixed_brand_does_not_fit_panel')
        left=x+(w-totalw)/2;ty=y+(h-th-bh-18*unit)/2
        envelope(left,y+(h-ew*.64)/2,ew)
        text_center(title,title_font,left+ew+gap+textw/2,ty,'title')
        text_center(brand,brand_font,left+ew+gap+textw/2,ty+th+18*unit,'brand')
    else:
        lines=[title[:2],title[2:]] if len(title)==4 else [title]
        bounds=[draw.textbbox((0,0),line,font=title_font) for line in lines]
        heights=[b[3]-b[1] for b in bounds]
        bb=draw.textbbox((0,0),brand,font=brand_font);bh=bb[3]-bb[1];gap=18*unit
        total=ew*.64+sum(heights)+bh+gap*(len(lines)+1)
        if max(ew,max(b[2]-b[0] for b in bounds))>w-24*unit or total>h-24*unit:
            raise ValueError('fixed_brand_does_not_fit_panel')
        top=y+(h-total)/2
        envelope(x+(w-ew)/2,top,ew);top+=ew*.64+gap
        for line,th in zip(lines,heights):text_center(line,title_font,x+w/2,top,'title');top+=th+gap
        text_center(brand,brand_font,x+w/2,top,'brand')
    return elements

def card_geometry(im,rect,width):
    x,y,w,h=map(round,rect);pad=max(3,round(width*.003))
    scale=min((w-2*pad)/im.width,(h-2*pad)/im.height)
    size=(max(1,round(im.width*scale)),max(1,round(im.height*scale)))
    px=x+(w-size[0])//2;py=y+(h-size[1])//2
    return {'placement':[px,py,*size],'frame':[x,y,w,h],
            'frame_fill':round(size[0]*size[1]/((w-2*pad)*(h-2*pad)),4),'scale':scale}

def paste_card(canvas,im,rect,asset_id,role,crop,original_size,details=None):
    geometry=card_geometry(im,rect,canvas.width);x,y,w,h=geometry['frame']
    ImageDraw.Draw(canvas).rounded_rectangle((x,y,x+w,y+h),radius=12,fill='#f7f5f1')
    px,py,pw,ph=geometry['placement'];canvas.paste(im.resize((pw,ph),Image.Resampling.LANCZOS),(px,py))
    return dict(geometry,asset_id=asset_id,role=role,original_size=list(original_size),crop=crop,
                uniform_scale=True,content_clipped=False,content_crop=details)

def prepare_page(records,paths,hero,config):
    width=int(config.get('width',1080))
    height=int(config.get('height',1440))
    if not 720<=width<=2400 or not width<=height<=width*2:raise ValueError('canvas_size_out_of_range')
    if not 1<=len(records)<=2:raise ValueError('one_or_two_sources_per_page')
    if len({r['asset_id'] for r in records})!=len(records):raise ValueError('duplicate_source_on_page')
    byid={r['asset_id']:r for r in records};primary=byid[hero['asset_id']]
    ordered=[primary]+[r for r in records if r is not primary]
    layout=config.get('layout','auto')
    if layout=='auto':layout=choose_layout(hero)
    if layout not in ('long_story','focused_story','short_reply','wide_reply'):raise ValueError('unknown_layout')
    # One template for every member: identical photo region and bottom title panel.
    unit=width/1080;margin=round(15*unit);gap=round(11*unit);inner=width-2*margin
    brand_h=round(240*unit);photo_h=height-2*margin-gap-brand_h
    photo_frame=[margin,margin,inner,photo_h];brand_rect=[margin,height-margin-brand_h,inner,brand_h]
    if len(records)==1:frames=[photo_frame]
    else:
        primary_w=round((inner-gap)*.60)
        frames=[[margin,margin,primary_w,photo_h],[margin+primary_w+gap,margin,inner-gap-primary_w,photo_h]]
    prepared=[]
    for record,rect in zip(ordered,frames):
        annotation=record.get('layout_evidence',{})
        if annotation.get('status')!='verified' or annotation.get('privacy_audit_passed') is not True or annotation.get('privacy_policy')!=PRIVACY_POLICY:
            raise UnsuitableScreenshot({'passed':False,'reason':'AI 主要内容或隐私遮盖复核未通过，待人工审核后生成',
                'codes':['privacy_or_content_unverified'],'chat_area_ratio':None,'brand_area_ratio':None})
        with Image.open(paths[record['asset_id']]) as raw:im=ImageOps.exif_transpose(raw).convert('RGB')
        pad=max(3,round(width*.003));aspect=(rect[2]-2*pad)/(rect[3]-2*pad)
        crop,details=crop_for_frame(annotation,im.size,aspect)
        masks=mask_regions(annotation,im.size);masked=mosaic(im,masks)
        details.update(privacy_masks=masks,privacy_audit_passed=True,protected_regions=annotation['protected_regions'])
        prepared.append((masked.crop(tuple(crop)),rect,record['asset_id'],'main_content',crop,list(im.size),details))
    plan={'layout':layout,'composition':'fixed_single' if len(records)==1 else 'fixed_pair',
          'width':width,'height':height,'photo_frame':photo_frame,'brand_frame':brand_rect,'brand_orientation':'horizontal'}
    return plan,prepared

def assess_plan(plan,prepared):
    area=plan['width']*plan['height']
    placements=[card_geometry(im,rect,plan['width'])['placement'] for im,rect,*_ in prepared]
    chat_ratio=sum(w*h for _,_,w,h in placements)/area
    brand_ratio=plan['brand_frame'][2]*plan['brand_frame'][3]/area
    codes=[];reasons=[]
    if any(p[-1]['main_content_fraction']<.40 for p in prepared):
        codes.append('main_content_too_sparse');reasons.append('主要聊天内容不足取景区域的 40%，扩展背景无法形成合格成品')
    if chat_ratio<.50:
        codes.append('chat_area_too_small');reasons.append(f'聊天截图仅占成品面积的 {chat_ratio:.1%}，低于 50%，无法成为画面主体')
    if brand_ratio>.40:
        codes.append('brand_area_too_large');reasons.append(f'标题区占成品面积的 {brand_ratio:.1%}，超过 40% 上限')
    return {'passed':not codes,'reason':'；'.join(reasons),'codes':codes,
            'chat_area_ratio':round(chat_ratio,6),'brand_area_ratio':round(brand_ratio,6),
            'min_chat_area_ratio':.50,'max_brand_area_ratio':.40}

def assess_page(records,paths,hero,config):
    try:return assess_plan(*prepare_page(records,paths,hero,config))
    except UnsuitableScreenshot as e:return e.assessment

def render_page(records,paths,hero,font_path,out,config):
    plan,prepared=prepare_page(records,paths,hero,config);quality=assess_plan(plan,prepared)
    # Rejected layouts never create a PNG/JPG, even when invoked outside pipeline.
    if not quality['passed']:raise UnsuitableScreenshot(quality)
    width,height=plan['width'],plan['height'];brand_rect=plan['brand_frame']
    canvas=Image.new('RGB',(width,height),config.get('accent','#e60012'))
    layers=[paste_card(canvas,*args) for args in prepared]
    brand_elements=draw_brand(canvas,brand_rect,font_path,config,plan['brand_orientation'])
    main_size=prepared[0][-2]
    estimate=hero['text_line_height']/1000*main_size[1]*layers[0]['scale']
    issues=[]
    if hero['requires_review']:issues.append('主要回复角色、边界或原图完整性待核对，主图区已使用完整上下文')
    if estimate and estimate<16:issues.append('主图文字预计偏小，请放大原图核对')
    out=Path(out);canvas.save(out,format='PNG');canvas.save(out.with_suffix('.jpg'),quality=94,subsampling=0)
    return dict(plan,hero_message_id=hero['message_id'],hero_score=hero['score'],hero_char_count=hero['char_count'],
                estimated_main_text_px=round(estimate,2),layers=layers,brand_elements=brand_elements,
                brand_style=brand_metrics(width,plan['brand_orientation']),quality=quality,issues=issues)

"""Render original screenshot pixels into a scored album; no model calls."""
import math
from pathlib import Path
from PIL import Image,ImageDraw,ImageFont,ImageOps
from .policy import choose_layout

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

def draw_brand(canvas,rect,font_path,config):
    x,y,w,h=rect;draw=ImageDraw.Draw(canvas);red=config.get('accent','#e60012')
    draw.rounded_rectangle((x,y,x+w,y+h),radius=12,fill='#fffdf9')
    # Keep the title/icon together even when this is a tall side panel.
    content_h=min(h,w*1.55)
    if h>content_h:y+=(h-content_h)/2;h=content_h
    draw.line((x+w*.18,y+h*.08,x+w*.82,y+h*.08),fill=red,width=max(2,round(w*.008)))
    wide=w>h*2
    # Small vector envelope/heart, independent of font emoji coverage.
    ew=min(w*.52,h*.44) if not wide else h*.8
    eh=ew*.64;ex=x+(w-ew)/2 if not wide else x+w*.055;ey=y+h*.18
    draw.rounded_rectangle((ex,ey,ex+ew,ey+eh),radius=ew*.055,fill='#dce5eb')
    draw.polygon([(ex,ey),(ex+ew/2,ey+eh*.66),(ex+ew,ey)],fill='#edf2f5')
    draw.polygon([(ex,ey+eh),(ex+ew/2,ey+eh*.42),(ex+ew,ey+eh)],fill='#c6d4de')
    cx=ex+ew/2;cy=ey+eh*.52;r=ew*.115
    draw.ellipse((cx-2*r,cy-r,cx,cy+r),fill=red);draw.ellipse((cx,cy-r,cx+2*r,cy+r),fill=red)
    draw.polygon([(cx-2*r,cy),(cx+2*r,cy),(cx,cy+2.6*r)],fill=red)
    title=config.get('title','会员感言');lines=[title[:2],title[2:]] if len(title)==4 and not wide else [title]
    size=round(min(w*.28,h*.16)) if not wide else round(h*.4);font=load_font(font_path,size)
    for i,line in enumerate(lines):
        while draw.textlength(line,font=font)>w*.86:
            size-=1;font=load_font(font_path,size)
        box=draw.textbbox((0,0),line,font=font);yy=y+h*.47+i*h*.21 if not wide else y+h*.22
        draw.text((x+(w-(box[2]-box[0]))/2-box[0],yy-box[1]),line,font=font,fill=red)
    brand=config.get('brand','UP 健身私教馆');font=load_font(font_path,max(10,round(w*.045 if not wide else h*.12)),450)
    while draw.textlength(brand,font=font)>w*.85:
        if font.size<=8:raise ValueError('brand_text_too_long_for_canvas')
        font=load_font(font_path,font.size-1,450)
    draw.text((x+(w-draw.textlength(brand,font=font))/2,y+h*(.92 if not wide else .76)),brand,font=font,fill='#8a7770')

def paste_card(canvas,im,rect,asset_id,role,crop,original_size):
    x,y,w,h=map(round,rect);pad=max(6,round(canvas.width*.007))
    ImageDraw.Draw(canvas).rounded_rectangle((x,y,x+w,y+h),radius=12,fill='#f7f5f1')
    scale=min((w-2*pad)/im.width,(h-2*pad)/im.height)
    size=(max(1,round(im.width*scale)),max(1,round(im.height*scale)))
    placed=im.resize(size,Image.Resampling.LANCZOS)
    px=x+(w-size[0])//2;py=y+(h-size[1])//2;canvas.paste(placed,(px,py))
    return {'asset_id':asset_id,'role':role,'original_size':list(original_size),'crop':crop,
            'placement':[px,py,*size],'scale':scale,'uniform_scale':True,'content_clipped':False}

def render_page(records,paths,hero,font_path,out,config):
    width=int(config.get('width',1080))
    height=int(config.get('height',1440))
    if not 720<=width<=2400 or not width<=height<=width*2:raise ValueError('canvas_size_out_of_range')
    if not 1<=len(records)<=2:raise ValueError('one_or_two_sources_per_page')
    if len({r['asset_id'] for r in records})!=len(records):raise ValueError('duplicate_source_on_page')
    byid={r['asset_id']:r for r in records};primary=byid[hero['asset_id']]
    secondary=next((r for r in records if r['asset_id']!=primary['asset_id']),None)
    layout=config.get('layout','auto')
    if layout=='auto':layout=choose_layout(hero)
    if layout not in ('long_story','focused_story','short_reply','wide_reply'):raise ValueError('unknown_layout')
    # Each original is placed exactly once, always retaining all relevant replies.
    main,main_crop,main_size=open_crop(paths[primary['asset_id']],primary['context_bbox'])
    margin=round(width*.022);gap=round(width*.014);inner=width-2*margin;pad=round(width*.014)
    content_h=height-2*margin
    if config.get('layout','auto')=='auto' and main.width/main.height>2.7:layout='wide_reply'
    if secondary is None:
        # Compare two fixed-canvas arrangements; give richer feedback more room,
        # then choose the one that keeps screenshot text largest without stretching.
        richness=min(1,hero['score']/100)
        band_h=round(width*(.31-.11*richness));side=round(width*(.31-.06*richness))
        bottom_main=[margin,margin,inner,content_h-band_h-gap]
        bottom_brand=[margin,height-margin-band_h,inner,band_h]
        side_main=[margin,margin,inner-side-gap,content_h]
        side_brand=[width-margin-side,margin,side,content_h]
        fit=lambda rect:min((rect[2]-pad)/main.width,(rect[3]-pad)/main.height)
        if fit(side_main)>fit(bottom_main)*1.02:
            main_rect,brand_rect=side_main,side_brand;composition='single_side_band'
        else:
            main_rect,brand_rect=bottom_main,bottom_brand;composition='single_bottom_band'
    else:
        context,context_crop,context_size=open_crop(paths[secondary['asset_id']],secondary['context_bbox'])
        secondary_score=max(m['score'] for m in secondary['messages'])
        ratio=max(.52,min(.70,.58+(hero['score']-secondary_score)*.002))
        col=round((inner-gap)*ratio);side=inner-gap-col;brand_h=min(round(side*1.28),round(content_h*.40))
        main_rect=[margin,margin,col,content_h]
        context_rect=[margin+col+gap,margin,side,content_h-brand_h-gap]
        brand_rect=[margin+col+gap,margin+content_h-brand_h,side,brand_h]
        composition='pair_feature'
    canvas=Image.new('RGB',(width,height),config.get('accent','#e60012'))
    layers=[paste_card(canvas,main,main_rect,primary['asset_id'],'context',main_crop,main_size)]
    if secondary is not None:
        layers.append(paste_card(canvas,context,context_rect,secondary['asset_id'],'context',context_crop,context_size))
    draw_brand(canvas,brand_rect,font_path,config)
    estimate=hero['text_line_height']/1000*main_size[1]*layers[0]['scale']
    issues=[]
    if hero['requires_review']:issues.append('主要回复角色、边界或原图完整性待核对，主图区已使用完整上下文')
    if estimate and estimate<16:issues.append('主图文字预计偏小，请放大原图核对')
    out=Path(out);canvas.save(out,format='PNG');canvas.save(out.with_suffix('.jpg'),quality=94,subsampling=0)
    return {'layout':layout,'composition':composition,'width':width,'height':height,'hero_message_id':hero['message_id'],
            'hero_score':hero['score'],'hero_char_count':hero['char_count'],'estimated_main_text_px':round(estimate,2),
            'layers':layers,'brand_frame':brand_rect,'issues':issues}

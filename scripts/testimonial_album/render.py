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

def fit_font(draw,text,path,size,width,weight=700,error='display_text_too_long_for_canvas'):
    font=load_font(path,size,weight)
    while draw.textlength(text,font=font)>width:
        if font.size<=8:raise ValueError(error)
        font=load_font(path,font.size-1,weight)
    return font

def draw_brand(canvas,rect,font_path,config):
    x,y,w,h=rect;draw=ImageDraw.Draw(canvas);red=config.get('accent','#e60012')
    draw.rounded_rectangle((x,y,x+w,y+h),radius=12,fill='#fffdf9')
    title=config.get('title','会员感言');brand=config.get('brand','UP 健身私教馆');elements=[]
    def text_center(text,font,cx,top,role):
        b=draw.textbbox((0,0),text,font=font);tw,th=b[2]-b[0],b[3]-b[1]
        left=cx-tw/2;draw.text((left-b[0],top-b[1]),text,font=font,fill=red if role=='title' else '#8a7770')
        elements.append({'role':role,'bounds':[left,top,left+tw,top+th]})
    def envelope(left,top,ew):
        eh=ew*.64
        draw.rounded_rectangle((left,top,left+ew,top+eh),radius=ew*.055,fill='#dce5eb')
        draw.polygon([(left,top),(left+ew/2,top+eh*.66),(left+ew,top)],fill='#edf2f5')
        draw.polygon([(left,top+eh),(left+ew/2,top+eh*.42),(left+ew,top+eh)],fill='#c6d4de')
        cx=left+ew/2;cy=top+eh*.45;r=ew*.105
        draw.ellipse((cx-2*r,cy-r,cx,cy+r),fill=red);draw.ellipse((cx,cy-r,cx+2*r,cy+r),fill=red)
        draw.polygon([(cx-2*r,cy),(cx+2*r,cy),(cx,cy+2.6*r)],fill=red)
        elements.append({'role':'icon','bounds':[left,top,left+ew,top+eh]})
    if w>=h*1.6:
        # Separate icon and text columns even for a large bottom title panel.
        inset=min(w,h)*.10;ew=min(h*.68,w*.22);gap=w*.04
        available=w-2*inset-ew-gap
        title_font=fit_font(draw,title,font_path,min(h*.43,w*.12),available)
        brand_font=fit_font(draw,brand,font_path,min(h*.13,w*.035),available,450,'brand_text_too_long_for_canvas')
        tb=draw.textbbox((0,0),title,font=title_font);bb=draw.textbbox((0,0),brand,font=brand_font)
        th=tb[3]-tb[1];bh=bb[3]-bb[1];textw=max(tb[2]-tb[0],bb[2]-bb[0])
        totalw=ew+gap+textw;left=x+(w-totalw)/2;ty=y+(h-th-bh-h*.08)/2
        envelope(left,y+(h-ew*.64)/2,ew)
        text_center(title,title_font,left+ew+gap+textw/2,ty,'title')
        text_center(brand,brand_font,left+ew+gap+textw/2,ty+th+h*.08,'brand')
    else:
        lines=[title[:2],title[2:]] if len(title)==4 else [title]
        title_font=fit_font(draw,max(lines,key=len),font_path,min(w*.32,h*.17),w*.84)
        brand_font=fit_font(draw,brand,font_path,min(w*.045,h*.06),w*.84,450,'brand_text_too_long_for_canvas')
        heights=[draw.textbbox((0,0),line,font=title_font)[3]-draw.textbbox((0,0),line,font=title_font)[1] for line in lines]
        bb=draw.textbbox((0,0),brand,font=brand_font);bh=bb[3]-bb[1]
        ew=min(w*.60,h*.29);gap=min(w*.08,h*.045)
        total=ew*.64+sum(heights)+bh+gap*(len(lines)+1)
        top=y+(h-total)/2
        envelope(x+(w-ew)/2,top,ew);top+=ew*.64+gap
        for line,th in zip(lines,heights):text_center(line,title_font,x+w/2,top,'title');top+=th+gap
        text_center(brand,brand_font,x+w/2,top,'brand')
    return elements

def paste_card(canvas,im,rect,asset_id,role,crop,original_size):
    x,y,w,h=map(round,rect);pad=max(3,round(canvas.width*.003))
    ImageDraw.Draw(canvas).rounded_rectangle((x,y,x+w,y+h),radius=12,fill='#f7f5f1')
    scale=min((w-2*pad)/im.width,(h-2*pad)/im.height)
    size=(max(1,round(im.width*scale)),max(1,round(im.height*scale)))
    placed=im.resize(size,Image.Resampling.LANCZOS)
    px=x+(w-size[0])//2;py=y+(h-size[1])//2;canvas.paste(placed,(px,py))
    return {'asset_id':asset_id,'role':role,'original_size':list(original_size),'crop':crop,
            'placement':[px,py,*size],'frame':[x,y,w,h],
            'frame_fill':round(size[0]*size[1]/((w-2*pad)*(h-2*pad)),4),
            'scale':scale,'uniform_scale':True,'content_clipped':False}

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
    margin=round(width*.014);gap=round(width*.010);inner=width-2*margin;pad=2*max(3,round(width*.003))
    content_h=height-2*margin
    if config.get('layout','auto')=='auto' and main.width/main.height>2.7:layout='wide_reply'
    if secondary is None:
        # Give screenshot pixels priority over a large title panel. Compare two
        # compact title positions, then fit the photo frame to its actual extent.
        # Wide screenshots must remain readable, rather than being cover-cropped.
        richness=min(1,hero['score']/100)
        band_h=round(width*(.16-.04*richness));side=round(width*(.18-.035*richness))
        bottom_main=[margin,margin,inner,content_h-band_h-gap]
        side_main=[margin,margin,inner-side-gap,content_h]
        fit=lambda rect:min((rect[2]-pad)/main.width,(rect[3]-pad)/main.height)
        if fit(side_main)>fit(bottom_main)*1.02:
            main_w=min(side_main[2],math.ceil(main.width*fit(side_main))+pad)
            main_rect=[margin,margin,main_w,content_h]
            brand_rect=[margin+main_w+gap,margin,inner-main_w-gap,content_h]
            composition='single_side_band'
        else:
            main_h=min(bottom_main[3],math.ceil(main.height*fit(bottom_main))+pad)
            main_rect=[margin,margin,inner,main_h]
            brand_rect=[margin,margin+main_h+gap,inner,content_h-main_h-gap]
            composition='single_bottom_band'
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
    brand_elements=draw_brand(canvas,brand_rect,font_path,config)
    estimate=hero['text_line_height']/1000*main_size[1]*layers[0]['scale']
    issues=[]
    if hero['requires_review']:issues.append('主要回复角色、边界或原图完整性待核对，主图区已使用完整上下文')
    if estimate and estimate<16:issues.append('主图文字预计偏小，请放大原图核对')
    out=Path(out);canvas.save(out,format='PNG');canvas.save(out.with_suffix('.jpg'),quality=94,subsampling=0)
    return {'layout':layout,'composition':composition,'width':width,'height':height,'hero_message_id':hero['message_id'],
            'hero_score':hero['score'],'hero_char_count':hero['char_count'],'estimated_main_text_px':round(estimate,2),
            'layers':layers,'brand_frame':brand_rect,'brand_elements':brand_elements,'issues':issues}

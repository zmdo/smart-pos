"""Fixed layout; uniform image scale; every source table row remains visible."""
from functools import lru_cache
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
from . import VERSION

RED='#e60012';INK='#242821';MUTED='#70736d';PAPER='#f5f2ed';LINE='#e4e0d9'
HEADERS=['类型','初始数据（训练前）','阶段数据（训练后）','变化量（+/-）','单位']

def render(case,images,width,font_path,out):
    if not case['rows']:raise ValueError('no_table_no_product')
    if width<400:raise ValueError('reference_width_too_small')
    height=round(width*1.25);canvas=Image.new('RGB',(width,height),PAPER);draw=ImageDraw.Draw(canvas)
    @lru_cache(maxsize=256)
    def load_font(size):
        f=ImageFont.truetype(str(font_path),size)
        try:
            axes=f.get_variation_axes()
            f.set_variation_by_axes([max(a['minimum'],min(a['maximum'],500)) if a['name']==b'Weight' else a['default'] for a in axes])
        except (OSError,AttributeError):pass
        return f
    def font(size):return load_font(max(10,round(size*width)))
    def label(text,box,size=.018,fill=INK,bold=False):
        x,y,w,h=box;f=font(size)
        # Long bilateral values get multiple lines, preserving every character.
        if draw.textbbox((0,0),text,font=f)[2]>w*.94 and h>f.size*1.8:
            lines=[];line=''
            for char in text:
                if char=='\n' or draw.textlength(line+char,font=f)>w*.92:
                    lines.append(line);line='' if char=='\n' else char
                else:line+=char
            if line:lines.append(line)
            text='\n'.join(lines)
        while (draw.textbbox((0,0),text,font=f)[2]>w*.94 or draw.textbbox((0,0),text,font=f)[3]>h*.85) and f.size>width*.008:
            f=load_font(f.size-1)
        bounds=draw.textbbox((0,0),text,font=f)
        if bounds[2]>w*.96 or bounds[3]-bounds[1]>h*.96:raise ValueError('text_exceeds_fixed_frame')
        draw.text((x+(w-bounds[2])/2,y+(h-(bounds[3]-bounds[1]))/2-bounds[1]),text,font=f,fill=fill)
    margin=round(width*.025);inner=width-2*margin
    draw.rectangle((0,0,width,round(width*.009)),fill=RED)
    draw.text((margin,width*.025),'体测数据 · 前后对比',font=font(.029),fill=INK)
    geometry=[]
    if images:
        half=inner//2; y=round(width*.111); ih=round(half*4/3)
        for i,side in enumerate(('before','after')):
            x=margin+i*half
            label(('训练前' if i==0 else '训练后')+'  '+case['pair'][side+'_date'],(x,width*.074,half,width*.028),size=.017,fill=RED if i else INK)
            with Image.open(images[side]) as raw: im=raw.convert('RGB')
            scale=min(half/im.width,ih/im.height);sz=(round(im.width*scale),round(im.height*scale))
            scaled=im.resize(sz,Image.Resampling.LANCZOS)
            px=x+(half-sz[0])//2;py=y+(ih-sz[1])//2;canvas.paste(scaled,(px,py))
            geometry.append({'side':side,'source_size':list(im.size),'placement':[px,py,*sz],
                             'scale':scale,'uniform_scale':True,'content_clipped':False})
        table_y=round(width*.807);table_bottom=round(width*1.205)
        label('阶段性训练成果',(margin,width*.761,inner,width*.039),size=.025,fill=RED)
    else:
        # Missing pair does not justify duplicating a report or guessing order.
        table_y=round(width*.145);table_bottom=round(width*1.15)
        label('阶段性训练成果',(margin,width*.088,inner,width*.045),size=.026,fill=RED)
    cols=[.17,.24,.24,.22,.13]; xs=[margin]
    for fraction in cols:xs.append(xs[-1]+round(inner*fraction))
    xs[-1]=width-margin
    header_h=round(width*.043); row_h=(table_bottom-table_y-header_h)/len(case['rows'])
    draw.rounded_rectangle((margin,table_y,width-margin,table_bottom),radius=round(width*.008),fill='white')
    draw.rectangle((margin,table_y,width-margin,table_y+header_h),fill=RED)
    for i,title in enumerate(HEADERS):label(title,(xs[i],table_y,xs[i+1]-xs[i],header_h),size=.017,fill='white')
    for index,row in enumerate(case['rows']):
        y=table_y+header_h+index*row_h
        if index%2==1:draw.rectangle((margin,round(y),width-margin,round(y+row_h)),fill='#faf8f5')
        for col,key in enumerate(('type','before','after','delta','unit')):
            label(str(row.get(key) or '—'),(xs[col],y,xs[col+1]-xs[col],row_h),size=min(.019,row_h/width*.52),
                  fill=RED if key=='delta' else INK)
        draw.line((margin,round(y+row_h),width-margin,round(y+row_h)),fill=LINE,width=max(1,round(width*.0006)))
    canvas.save(out)
    return {'version':VERSION,'width':width,'height':height,'row_count':len(case['rows']),
            'images':geometry,'width_rule':'2 * max(original before width, original after width)',
            'height_rule':'round(width * 1.25)','table_only':not bool(images)}

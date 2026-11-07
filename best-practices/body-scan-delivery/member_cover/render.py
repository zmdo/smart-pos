"""1080x1440 reference cover; bounded typography and a fixed photo window."""
from functools import lru_cache
import re
from PIL import Image, ImageDraw, ImageOps
from scripts.body_scan_delivery.logo import load_logo
from scripts.body_scan_delivery.vs_layout import typeface

BG='#F3F0EA'; RED='#E70012'; INK='#11140C'; BROWN='#805225'; BODY='#595052'
SIZE=(1080,1440)


@lru_cache(maxsize=96)
def font(path, size, weight=700):
    return typeface(path,size,weight)


def line(draw, text, box, path, size, fill, weight=800, minimum=24, center=False):
    x1,y1,x2,y2=box
    for fs in range(size,minimum-1,-1):
        f=font(path,fs,weight);b=draw.textbbox((0,0),text,font=f)
        if b[2]-b[0]<=x2-x1 and b[3]-b[1]<=y2-y1:
            xy=((x1+x2)/2,(y1+y2)/2) if center else (x1,(y1+y2)/2)
            draw.text(xy,text,font=f,fill=fill,anchor='mm' if center else 'lm')
            return {'font_size':fs,'width':draw.textlength(text,font=f)}
    raise ValueError('cover_heading_too_long')


def story_lines(segments, path, size, width):
    f=font(path,size,400);lines=[];row=[];x=0.
    for segment in segments:
        for ch in re.findall(r'[A-Za-z0-9]+(?:\.[A-Za-z0-9]+)*(?:%)?|[^\n]|\n',segment['text']):
            cw=f.getlength(ch)
            if ch=='\n' or x+cw>width:
                if ch in '，。；！？、）”' and row:
                    previous=row.pop();lines.append(row);row=[previous];x=previous[2]
                else:
                    lines.append(row);row=[];x=0.
            if ch!='\n':
                row.append((ch,segment['emphasis'],cw));x+=cw
    if row:lines.append(row)
    return lines


def draw_cover(images, copy, presentation, path, store):
    canvas=Image.new('RGB',SIZE,BG);draw=ImageDraw.Draw(canvas)
    draw.rounded_rectangle((692,26,1050,130),radius=54,outline=RED,width=8)
    line(draw,copy.get('badge','会员案例'),(716,35,1028,119),path,63,RED,900,center=True)
    heading=line(draw,copy['title'],(30,81,664,211),path,119,RED,900,minimum=60)
    draw.rectangle((30,214,min(664,30+heading['width']),220),fill=RED)
    line(draw,copy['subtitle'],(32,244,1048,318),path,67,BROWN,800)
    line(draw,copy['headline'],(32,339,1048,414),path,71,INK,900)
    card=Image.new('RGB',(1016,622),RED)
    card.paste(images[0],(8,8));card.paste(images[1],(508,8))
    # Top corners are rounded with the red frame; the bottom is the brand bar.
    photo_mask=Image.new('L',(1000,478),255);md=ImageDraw.Draw(photo_mask)
    md.rectangle((0,0,1000,478),fill=0)
    md.rounded_rectangle((0,0,1000,530),radius=44,fill=255)
    pair=Image.new('RGB',(1000,478));pair.paste(images[0],(0,0));pair.paste(images[1],(500,0))
    card.paste(RED,(8,8,1008,486));card.paste(pair,(8,8),photo_mask)
    cd=ImageDraw.Draw(card)
    if presentation.get('logo_path'):
        logo=load_logo(presentation['logo_path'],(325,86),presentation.get('logo_sha256'))
        card.paste(logo,(38,516+(86-logo.height)//2),logo)
    else:
        line(cd,presentation.get('brand_name','UP 健身私教馆'),(36,514,470,597),path,40,'white')
    # Small location pin drawn as geometry, no external icon asset.
    cd.ellipse((536,521,592,577),fill='white');cd.polygon([(538,555),(564,592),(590,555)],fill='white')
    cd.ellipse((555,540,573,558),fill=RED)
    address=copy.get('address') or presentation.get('address') or 'UP 健身私教馆'
    if address=='UP 健身私教馆':
        address_lines=[address,copy.get('store_text',store)]
    else:
        address_lines=[address[:15],address[15:]] if len(address)>15 else [address,copy.get('store_text',store)]
    line(cd,address_lines[0],(614,514,982,554),path,32,'white',700)
    line(cd,address_lines[1],(614,557,982,599),path,32,'white',700)
    mask=Image.new('L',card.size);ImageDraw.Draw(mask).rounded_rectangle((0,0,1015,621),radius=54,fill=255)
    canvas.paste(card,(32,452),mask)
    draw=ImageDraw.Draw(canvas)
    def quote(char, xy):
        mark=Image.new('RGBA',(160,160));md=ImageDraw.Draw(mark)
        md.text((0,0),char,font=font(path,90,900),fill=BODY)
        mark=ImageOps.contain(mark.crop(mark.getbbox()),(37,32),Image.Resampling.LANCZOS)
        canvas.paste(mark,xy,mark)
    quote('“',(32,1105))
    for fs in range(28,21,-1):
        lines=story_lines(copy['segments'],path,fs,944)
        step=round(fs*1.68)
        if len(lines)*step<=285:break
    else:raise ValueError('cover_story_too_long')
    f=font(path,fs,400)
    for i,row in enumerate(lines):
        x=87.;y=1102+i*step+fs
        for ch,emphasis,cw in row:
            draw.text((x,y),ch,font=f,fill=RED if emphasis else BODY,anchor='ls');x+=cw
    quote('”',(1006,1377))
    return canvas,{'canvas':list(SIZE),'photo_window':[40,460,1040,938],
                   'photo_panel_size':[500,478],'story_font_size':fs,'story_lines':len(lines),
                   'headings_fit':True,'story_fits':True}

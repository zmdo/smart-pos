"""Reference-style VS card: full photos, fixed width, content-driven height."""
import math
from PIL import Image, ImageDraw, ImageFont
from .logo import load_logo

VERSION = 'body-same-view-reference-v5'
RED = '#E70012'
TITLES = {'front':'体测正视图','side':'体测侧视图','back':'体测后视图'}


def typeface(path, size, weight):
    font=ImageFont.truetype(str(path),size)
    try:
        axes=font.get_variation_axes()
        font.set_variation_by_axes([min(a['maximum'],max(a['minimum'],weight))
                                   if a['name']==b'Weight' else a['default'] for a in axes])
    except (OSError,AttributeError):
        pass  # Static fonts use their supplied weight.
    return font


def geometry(sizes, width, metric_count=3):
    if len(sizes)!=2 or any(w<=0 or h<=0 for w,h in sizes):raise ValueError('vs_requires_two_valid_photos')
    ratio = sum(w/h for w,h in sizes)
    height = round(width/ratio)
    left = round(height*sizes[0][0]/sizes[0][1])
    if height<1 or not 0<left<width:raise ValueError('unsupported_vs_photo_aspect_ratio')
    header = round(width*219/1080)
    footer = round(width*(338+90*(math.ceil(metric_count/3)-1))/1080)
    return {'width':width,'height':header+height+footer,'header':header,'photo_height':height,
            'footer':footer,'photo_boxes':[[0,header,left,header+height],[left,header,width,header+height]]}


def draw_vs(rows, photos, font, context, view):
    sources=[]
    for row in rows:
        with Image.open(photos[row['asset_id']]) as source:sources.append(source.convert('RGB'))
    layout=geometry([im.size for im in sources],context['width'],len(context['metrics']))
    width=layout['width'];scale=width/1080
    px=lambda n:max(1,round(n*scale))
    canvas=Image.new('RGB',(width,layout['height']),RED);draw=ImageDraw.Draw(canvas)
    for source,box in zip(sources,layout['photo_boxes']):
        # The only aspect error is integer-pixel rounding (at most one pixel).
        canvas.paste(source.resize((box[2]-box[0],box[3]-box[1]),Image.Resampling.LANCZOS),box[:2])

    def label(value,box,size=40,color=RED,bold=True,align='center'):
        x1,y1,x2,y2=box;stroke=0
        for fs in range(px(size),0,-1):
            f=typeface(font,fs,700 if bold else 400)
            bounds=draw.textbbox((0,0),value,font=f,stroke_width=stroke)
            if bounds[2]-bounds[0]<=x2-x1 and bounds[3]-bounds[1]<=y2-y1:break
        x=x2 if align=='right' else (x1+x2)/2
        draw.text((x,(y1+y2)/2),value,font=f,anchor='rm' if align=='right' else 'mm',fill=color,
                  stroke_width=stroke,stroke_fill=color)

    def capsule(box,fill='white',outline=RED,stroke=6):
        draw.rounded_rectangle(box,radius=(box[3]-box[1])/2,fill=fill,outline=outline,width=px(stroke))

    if context.get('logo_path'):
        logo=load_logo(context['logo_path'],(px(660),px(130)),context.get('logo_sha256'))
        canvas.paste(logo,((width-logo.width)//2,px(35)+(px(130)-logo.height)//2),logo)
    else:
        label(context['brand_name'],(px(200),px(45),width-px(200),px(150)),60,'white')
    if context.get('consent_text'):
        label(context['consent_text'],(px(690),px(186),width-px(16),px(212)),18,'white',False,align='right')

    # The title overlaps only the top edge of the photo, as in the supplied reference.
    box=(width//2-px(135),px(173),width//2+px(135),px(270))
    draw.rounded_rectangle(box,radius=px(25),fill='white',outline=RED,width=px(6))
    label(TITLES[view],(box[0]+px(18),box[1]+px(15),box[2]-px(18),box[3]-px(14)),42)

    # Italic, outlined lettering drawn at the native output resolution.
    mark=Image.new('RGBA',(px(240),px(140)));md=ImageDraw.Draw(mark)
    f=typeface(font,px(96),900)
    md.text((px(119),px(66)),'VS',font=f,anchor='mm',fill=RED,stroke_width=px(10),stroke_fill='white')
    md.text((px(119),px(66)),'VS',font=f,anchor='mm',fill=RED,stroke_width=px(2),stroke_fill=RED)
    mark=mark.transform(mark.size,Image.Transform.AFFINE,(1,.23,-px(18),0,1,0),Image.Resampling.BICUBIC)
    center_y=layout['header']+round(layout['photo_height']*.40)
    canvas.paste(mark,(width//2-mark.width//2,center_y-mark.height//2),mark)

    bottom=layout['header']+layout['photo_height'];y1=bottom-px(125);y2=bottom-px(25)
    for index,photo_box in enumerate(layout['photo_boxes']):
        center=(photo_box[0]+photo_box[2])//2
        half=min(px(120),(photo_box[2]-photo_box[0])*.38)
        b=(round(center-half),y1,round(center+half),y2)
        capsule(b)
        label(('Before','After')[index],(b[0]+px(18),y1+px(6),b[2]-px(18),y2-px(6)),43)
    cx=width//2;cy=(y1+y2)//2
    points=[(cx-px(56),cy-px(27)),(cx+px(16),cy-px(27)),(cx+px(16),cy-px(54)),
            (cx+px(77),cy),(cx+px(16),cy+px(54)),(cx+px(16),cy+px(27)),(cx-px(56),cy+px(27))]
    draw.polygon(points,fill=RED)
    draw.line(points+[points[0]],fill='white',width=px(6),joint='curve')

    y=bottom+px(36);box=(px(62),y,width-px(56),y+px(100))
    capsule(box,fill=RED,outline='white',stroke=4)
    namebox=(box[0],box[1],px(300),box[3]);capsule(namebox,outline='white',stroke=1)
    label(context['nickname'],(namebox[0]+px(20),y+px(15),namebox[2]-px(20),y+px(84)),43)
    label(context['address'],(px(326),y+px(18),box[2]-px(24),y+px(82)),31,'white')
    for index,metric in enumerate(context['metrics']):
        line,col=divmod(index,3)
        count=min(3,len(context['metrics'])-line*3)
        gap=px(6);margin=px(14);cell=(width-2*margin-gap*(count-1))/count
        x=round(margin+col*(cell+gap));y=bottom+px(171+90*line)
        box=(x,y,round(x+cell),y+px(72));capsule(box,outline='white',stroke=1)
        label(metric['text'],(box[0]+px(20),y+px(8),box[2]-px(20),y+px(64)),41)
    return canvas

"""Single-view photo on a plain canvas, without image annotations."""
from PIL import Image, ImageFont, ImageOps

VERSION="body-single-photo-v2"
BG="#F3F0EA";INK="#25382F"


def text(draw,xy,value,font,size=34,fill=INK,anchor='mm'):
    draw.text(xy,value,font=ImageFont.truetype(str(font),size),fill=fill,anchor=anchor)


def place(canvas,path,box):
    with Image.open(path) as source:
        image=ImageOps.contain(source.convert('RGB'),(box[2]-box[0],box[3]-box[1]),Image.Resampling.LANCZOS)
    canvas.paste(image,(box[0]+(box[2]-box[0]-image.width)//2,box[1]+(box[3]-box[1]-image.height)//2))


def draw_single(rows,photos,font,context=None):
    context=context or {}
    canvas=Image.new("RGB",(1080,1440),context.get('background',BG))
    row=rows[0];place(canvas,photos[row["asset_id"]],(0,0,1080,1440))
    return canvas

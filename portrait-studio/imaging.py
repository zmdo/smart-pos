import math
from PIL import Image, ImageOps, ImageDraw
Image.MAX_IMAGE_PIXELS = 30_000_000
DIRECTIONS = ["front", "back", "left", "right"]
def open_image(path):
    with Image.open(path) as im:
        if im.width * im.height > Image.MAX_IMAGE_PIXELS:
            raise ValueError("图片像素超过 3000 万")
        return ImageOps.exif_transpose(im).convert("RGB")
def validate_box(value, width, height, normalized=False):
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        raise ValueError("模型没有返回有效坐标")
    vals = [float(v) for v in value]
    if not all(math.isfinite(v) for v in vals):
        raise ValueError("模型坐标不是有效数字")
    if normalized:
        vals = [vals[0]*width/1000, vals[1]*height/1000, vals[2]*width/1000, vals[3]*height/1000]
    x1, y1, x2, y2 = vals
    x1, y1, x2, y2 = max(0,x1), max(0,y1), min(width,x2), min(height,y2)
    if x2-x1 < 2 or y2-y1 < 2:
        raise ValueError("模型返回的人物或面部框无效")
    return [round(x1,2), round(y1,2), round(x2,2), round(y2,2)]
DEFAULT_STICKER_SIZE = 192
DEFAULT_STICKER_FILL = "#ddd8cf"
DEFAULT_STICKER_INK = "#4c5449"
def draw_default_sticker(size):
    art = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(art)
    radius = max(2, min(size)//8)
    draw.rounded_rectangle((0, 0, size[0]-1, size[1]-1), radius=radius, fill=DEFAULT_STICKER_FILL)
    line = max(1, min(size)//45)
    draw.ellipse((size[0]*.22,size[1]*.3,size[0]*.32,size[1]*.4), fill=DEFAULT_STICKER_INK)
    draw.ellipse((size[0]*.68,size[1]*.3,size[0]*.78,size[1]*.4), fill=DEFAULT_STICKER_INK)
    draw.arc((size[0]*.27,size[1]*.37,size[0]*.73,size[1]*.72),0,180,fill=DEFAULT_STICKER_INK,width=line)
    return art
def sticker_art(sticker, size):
    """Uploaded art is fitted into `size`; the built-in face is drawn at that size."""
    if sticker:
        return ImageOps.fit(sticker.convert("RGBA"), size, method=Image.Resampling.LANCZOS)
    return draw_default_sticker(size)
def render_person(image, bbox, face, options, sticker=None):
    w, h = options["width"], options["height"]
    x1,y1,x2,y2 = bbox
    pad = options["padding"] / 100
    scale = min(w*(1-2*pad)/(x2-x1), h*(1-2*pad)/(y2-y1))
    cx,cy = (x1+x2)/2, (y1+y2)/2
    # Inverse affine mapping preserves the image background and centers the subject.
    left,top = cx-w/(2*scale), cy-h/(2*scale)
    result = image.transform((w,h), Image.Transform.AFFINE, (1/scale,0,left,0,1/scale,top),
        resample=Image.Resampling.BICUBIC, fillcolor=options["background"])
    face_out = None
    mask_mode = None
    if face and options["mask_enabled"]:
        fx1,fy1,fx2,fy2 = face
        mx,my = ((fx1+fx2)/2-left)*scale, ((fy1+fy2)/2-top)*scale
        if options.get("mask_scaled", False):
            # Sticker follows the face box size (multiplied by the cover ratio).
            mask_mode = "scaled"
            fw,fh = (fx2-fx1)*scale*options["mask_scale"], (fy2-fy1)*scale*options["mask_scale"]
            box = [max(0,int(mx-fw/2)),max(0,int(my-fh/2)),min(w,math.ceil(mx+fw/2)),min(h,math.ceil(my+fh/2))]
            a,b,c,d = box
            if c>a and d>b:
                # Opaque base avoids accidentally exposing the face under transparent stickers.
                cover = Image.new("RGBA", (c-a,d-b), DEFAULT_STICKER_FILL)
                cover.alpha_composite(sticker_art(sticker, cover.size))
                result.paste(cover.convert("RGB"), (a,b))
                face_out = box
        else:
            # Default: paste the sticker at its own pixel size, centred on the face box.
            mask_mode = "native"
            art = sticker_art(sticker, sticker.size if sticker else (DEFAULT_STICKER_SIZE,)*2)
            base = Image.new("RGBA", art.size, DEFAULT_STICKER_FILL)
            base.alpha_composite(art)
            a = int(round(mx - art.width/2))
            b = int(round(my - art.height/2))
            cover = base.convert("RGB")
            # PIL crops whatever falls outside the canvas, so the centre stays on the face.
            result.paste(cover, (a, b))
            face_out = [a, b, a+art.width, b+art.height]
    return result, {"scale":scale,"source_origin":[left,top],"face_bbox_output":face_out,
        "mask_mode":mask_mode}
def make_sheets(records, out_dir, options):
    groups = {}
    for row in records:
        if row.get("status") == "done":
            groups.setdefault(row["directory"], {d:[] for d in DIRECTIONS})[row["orientation"]].append(row)
    sheets = []
    w,h,gap = options["width"],options["height"],options["gap"]
    rows_per_page = max(1, min(8, 40_000_000//((w+gap)*4*(h+gap))))
    for group_index,(directory,buckets) in enumerate(sorted(groups.items())):
        count = max(map(len,buckets.values()))
        for offset in range(0,count,rows_per_page):
            rows = min(rows_per_page,count-offset)
            canvas = Image.new("RGB",(w*4+gap*3,h*rows+gap*(rows-1)),options["background"])
            missing=[]
            for col,direction in enumerate(DIRECTIONS):
                for r in range(rows):
                    index=offset+r
                    if index<len(buckets[direction]):
                        with Image.open(out_dir/buckets[direction][index]["output"]) as im:
                            canvas.paste(im,(col*(w+gap),r*(h+gap)))
                    else:
                        missing.append({"row":r,"direction":direction})
            name=f"sheet-{group_index+1:03d}-{offset//rows_per_page+1:02d}.png"
            canvas.save(out_dir/name)
            preview=canvas.copy()
            preview.thumbnail((1600,1800))
            preview.save(out_dir/("preview-"+name), optimize=True)
            sheets.append({"directory":directory,"file":name,"preview":"preview-"+name,
                "width":canvas.width,"height":canvas.height,"rows":rows,"missing":missing,
                "counts":{d:len(buckets[d]) for d in DIRECTIONS}})
    return sheets


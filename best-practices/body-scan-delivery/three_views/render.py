"""Native-size, annotation-free front/side/back grid."""
from PIL import Image

VERSION = "body-three-views-seamless-v2"


def seamless_grid(rows,photos):
    """Join the six approved frames at native size; add no pixels between them."""
    if len(rows)!=6:raise ValueError('three_views_requires_six_frames')
    images=[]
    for row in rows:
        with Image.open(photos[row['asset_id']]) as source:
            images.append(source.convert('RGB'))
    if len({image.size for image in images})!=1:
        raise ValueError('three_views_requires_equal_frame_sizes')
    width,height=images[0].size
    canvas=Image.new('RGB',(width*3,height*2))
    for index,image in enumerate(images):
        canvas.paste(image,((index%3)*width,(index//3)*height))
    return canvas

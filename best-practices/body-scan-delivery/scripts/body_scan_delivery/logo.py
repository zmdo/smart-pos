"""Load local vector/raster branding; retain artwork and trim empty SVG artboards."""
import hashlib
import io
import re
import xml.etree.ElementTree as ET
from functools import lru_cache
from pathlib import Path

VERSION = 'svg-alpha-trim-v1'
FORMATS = {'.png','.jpg','.jpeg','.webp','.svg'}
SVG_NS = 'http://www.w3.org/2000/svg'


def normalized_svg(data):
    """Drop Illustrator's private editing payload without enabling unsafe XML."""
    if len(data)>2_000_000:raise ValueError('logo_svg_too_large')
    text=data.decode('utf-8-sig')
    # Illustrator uses literal namespace entities. Allow only these simple URI
    # declarations, never external entities, nested expansion or parameter entities.
    for declaration in re.findall(r'<!ENTITY\b[^>]*>',text,re.I):
        if not re.fullmatch(r'<!ENTITY\s+ns_[\w.-]+\s+([\"\'])https?://[\w.:/#-]+\1\s*>',declaration):
            raise ValueError('unsupported_svg_entity')
    root=ET.fromstring(text)
    if root.tag not in ('svg','{'+SVG_NS+'}svg'):raise ValueError('invalid_svg_root')
    for parent in list(root.iter()):
        for child in list(parent):
            local=child.tag.split('}')[-1]
            if (child.tag.startswith('{') and not child.tag.startswith('{'+SVG_NS+'}')) or local in ('foreignObject','metadata','script'):
                parent.remove(child)
    return ET.tostring(root,encoding='utf-8')


def deny_resource(url,resource_type):
    raise ValueError('logo_external_resource_not_allowed')


@lru_cache(maxsize=8)
def _load(data,extension,box):
    from PIL import Image,ImageOps
    if extension=='.svg':
        try:
            from cairosvg.surface import PNGSurface
        except ImportError as exc:
            raise RuntimeError('SVG logo requires requirements-logo.txt on rendering server') from exc
        vector=normalized_svg(data)
        # Render a square artboard at sufficient resolution, then use its visible
        # alpha bounds. PNGSurface passes our fetcher to every nested SVG/CSS fetch.
        root=ET.fromstring(vector)
        viewbox=root.get('viewBox','').replace(',',' ').split()
        if len(viewbox)==4:
            w,h=map(float,viewbox[2:])
        else:
            parse=lambda v:float(v.removesuffix('px'))
            w,h=parse(root.get('width','0')),parse(root.get('height','0'))
        if not 0<w<100000 or not 0<h<100000:raise ValueError('invalid_logo_svg_dimensions')
        size=min(4096,max(box)*3)
        scale=size/max(w,h)
        raster=PNGSurface.convert(bytestring=vector,unsafe=False,
            output_width=max(1,round(w*scale)),output_height=max(1,round(h*scale)),url_fetcher=deny_resource)
        with Image.open(io.BytesIO(raster)) as source:image=source.convert('RGBA')
        bbox=image.getchannel('A').getbbox()
        if not bbox:raise ValueError('empty_svg_logo')
        image=image.crop(bbox)
    else:
        with Image.open(io.BytesIO(data)) as source:image=ImageOps.exif_transpose(source).convert('RGBA')
    return ImageOps.contain(image,box,Image.Resampling.LANCZOS)


def load_logo(path,box,expected_sha256=None):
    path=Path(path);data=path.read_bytes()
    if expected_sha256 and hashlib.sha256(data).hexdigest()!=expected_sha256:
        raise ValueError('logo_changed_after_binding')
    if path.suffix.lower() not in FORMATS:raise ValueError('unsupported_logo_format')
    return _load(data,path.suffix.lower(),tuple(box)).copy()

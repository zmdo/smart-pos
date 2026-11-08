"""Freeze output preferences once per render; never rewrite a saved product."""
import copy
from PIL import Image, ImageOps
from . import config, fonts

VERSION = 'studio-typography-canvas-v1'
KEYS = ('default_font', 'font_overrides', 'output_width', 'output_background', 'mask_lifestyle')


def settings():
    cfg = config.load()
    return {k:copy.deepcopy(cfg[k]) for k in KEYS}


def freeze(data):
    result = copy.deepcopy(data)
    result['_render_settings'] = settings()
    return result


def font_context(member, preferences, section):
    available = {f['id']:f['path'] for f in fonts.catalog()}
    default = available[preferences['default_font']]
    overrides = dict(preferences.get('font_overrides', {}), **member.get('fonts', {}))
    selected = {k[len(section)+1:]: available[v] for k,v in overrides.items() if k.startswith(section+'.')}
    return default, selected


def fit(image, preferences):
    width = preferences['output_width']
    size = (width, width*4//3)
    if image.size == size:
        return image.convert('RGB')
    scaled = ImageOps.contain(image.convert('RGB'), size, Image.Resampling.LANCZOS)
    canvas = Image.new('RGB', size, preferences['output_background'])
    canvas.paste(scaled, ((width-scaled.width)//2, (size[1]-scaled.height)//2))
    return canvas

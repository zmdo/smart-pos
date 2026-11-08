"""Immutable font files and an authenticated catalog for output typography."""
import hashlib, io, re, threading
from functools import lru_cache
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
from fontTools.ttLib import TTFont
from .common import DATA, WEB_DATA, FONT, read, save, sha

LOCK = threading.RLock()
ROOT = WEB_DATA / 'fonts'
DEFAULT = 'noto-sans-sc'
MAX_BYTES = 32 * 1024 * 1024
BUILTINS = {
    DEFAULT: ('思源黑体', FONT),
    'noto-serif-sc': ('思源宋体', DATA / 'fonts/NotoSerifSC.ttf'),
    'zcool-kuaile': ('站酷快乐体', DATA / 'fonts/ZCOOLKuaiLe-Regular.ttf'),
    'ma-shan-zheng': ('马善政毛笔体', DATA / 'fonts/MaShanZheng-Regular.ttf'),
}


@lru_cache(maxsize=32)
def digest(path, modified, size):
    return sha(path)


def catalog():
    rows = [dict(id=k, name=name, path=str(path), active=True, builtin=True,
                 license='SIL Open Font License 1.1', sha256=digest(str(path), path.stat().st_mtime_ns, path.stat().st_size) if path.exists() else 'missing')
            for k, (name, path) in BUILTINS.items() if k == DEFAULT or path.exists()]
    return rows + read(ROOT / 'catalog.json', [])


def get(fid, active=False):
    row = next((r for r in catalog() if r['id'] == fid), None)
    if row is None or (active and not row['active']):
        raise ValueError('字体不存在或已停用，请重新选择')
    return row


def public(row):
    return {k:v for k,v in row.items() if k != 'path'}


def upload(data, filename, name=''):
    if not data or len(data) > MAX_BYTES or Path(filename or '').suffix.lower() not in ('.ttf', '.otf'):
        raise ValueError('请上传不超过 32 MB 的 TTF 或 OTF 字体')
    if data[:4] not in (b'\x00\x01\x00\x00', b'OTTO'):
        raise ValueError('不支持该字体格式，请使用 TTF 或 OTF')
    try:
        with TTFont(io.BytesIO(data), lazy=False) as face:
            cmap = face.getBestCmap() or {}
            if not cmap or len(cmap) > 200000:
                raise ValueError('empty font')
            family = face['name'].getDebugName(1) or Path(filename).stem
        ImageFont.truetype(io.BytesIO(data), 32).getmask('会员 Before 123')
    except Exception as exc:
        raise ValueError('字体文件无法读取，请更换完整的 TTF/OTF 文件') from exc
    name = (name.strip() or family)[:80]
    if any(ord(c) < 32 for c in name):
        raise ValueError('字体名称无效')
    digest = hashlib.sha256(data).hexdigest()
    fid = 'font-' + digest[:24]
    with LOCK:
        rows = read(ROOT / 'catalog.json', [])
        existing = next((r for r in rows if r['id'] == fid), None)
        if existing:
            existing.update(active=True, name=name)
            save(ROOT / 'catalog.json', rows)
            return public(existing)
        if len(rows) >= 200:
            raise ValueError('字体库已达到 200 个字体上限')
        ROOT.mkdir(parents=True, exist_ok=True)
        file = ROOT / (fid + ('.otf' if data[:4] == b'OTTO' else '.ttf'))
        file.write_bytes(data)
        row = dict(id=fid, name=name, path=str(file), active=True, builtin=False,
                   sha256=digest, license='用户上传', chinese=ord('会') in cmap)
        rows.append(row)
        save(ROOT / 'catalog.json', rows)
        return public(row)


def deactivate(fid):
    from . import config
    with LOCK:
        if fid in BUILTINS:
            raise ValueError('预置字体不能停用')
        cfg = config.load()
        if fid == cfg['default_font'] or fid in cfg.get('font_overrides', {}).values():
            raise ValueError('请先更换设置页中引用该字体的默认项')
        rows = read(ROOT / 'catalog.json', [])
        row = next((r for r in rows if r['id'] == fid), None)
        if row is None:
            raise ValueError('字体不存在')
        row['active'] = False
        save(ROOT / 'catalog.json', rows)
        return public(row)


def preview(fid):
    row = get(fid)
    target = ROOT / 'previews' / (fid + '.png')
    if not target.exists():
        canvas = Image.new('RGB', (720, 190), '#f5f2ed')
        draw = ImageDraw.Draw(canvas)
        for y, value, size in ((26, '把每一份改变，留在镜头里', 40), (106, 'Before → After  0123456789', 32)):
            face = ImageFont.truetype(row['path'],size)
            try:
                face.set_variation_by_axes([min(a['maximum'],max(a['minimum'],400)) if a['name']==b'Weight' else a['default'] for a in face.get_variation_axes()])
            except (OSError, AttributeError):
                pass
            draw.text((24,y), value, font=face, fill='#25382f')
        target.parent.mkdir(parents=True, exist_ok=True)
        canvas.save(target)
    return target


def valid_key(key):
    return isinstance(key, str) and bool(re.fullmatch(
        r'(vs\.(brand_name|address|nickname|consent_text|before_text|after_text|vs_text|titles\.(front|side|back)|metrics\.[0-5])'
        r'|cover\.(title|subtitle|headline|story|badge|store_text|address|brand_name)'
        r'|table\.(table_title|report_title|before_label|after_label|headers\.[0-4]|rows\.([0-9]|1[0-9])\.(type|before|after|delta|unit))'
        r'|single\.caption|testimonial\.(title|brand))', key))


def validate_map(value, previous=None):
    if not isinstance(value, dict) or len(value) > 160:
        raise ValueError('字体配置格式无效')
    result = {}
    available = {r['id']:r for r in catalog()}
    for key, fid in value.items():
        if not valid_key(key) or not isinstance(fid, str):
            raise ValueError('字体字段无效')
        if fid:
            # Existing historical references survive catalog deactivation.
            row = available.get(fid)
            if row is None or (not row['active'] and (previous or {}).get(key) != fid):
                raise ValueError('字体不存在或已停用，请重新选择')
            result[key] = fid
    return result

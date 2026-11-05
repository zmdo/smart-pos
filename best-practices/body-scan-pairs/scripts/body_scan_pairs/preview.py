"""Review artifact: detected boundary, native crops and separately aligned outputs."""
import html
import json
import zipfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps


def make_previews(out):
    out = Path(out)
    rows = json.loads((out/'summary.json').read_text(encoding='utf-8'))
    font_path = Path('/root/autodl-fs/case-studio/fonts/NotoSansSC.ttf')
    font = ImageFont.truetype(str(font_path), 23) if font_path.exists() else ImageFont.load_default()
    small = ImageFont.truetype(str(font_path), 17) if font_path.exists() else font
    results = {}
    if (out/'aligned/summary.json').exists():
        results = {r['asset_id']: r for r in json.loads((out/'aligned/summary.json').read_text(encoding='utf-8'))}
    sections = []
    for row in rows:
        aid = row['asset_id']
        sheet = Image.new('RGB', (1200, 1340), '#eeeae3')
        draw = ImageDraw.Draw(sheet)
        title = f"{row.get('store') or ''} / {row.get('member') or ''} / {aid}"
        draw.text((20, 15), title, font=font, fill='#26352c')
        description = row.get('reason_zh', row.get('reason', '硬拼接拆分；时间顺序未推测'))
        draw.text((20, 50), description, font=small, fill='#774532')

        def paste(path, rect):
            if not path.exists():
                return
            x, y, w, h = rect
            with Image.open(path) as image:
                thumb = ImageOps.contain(ImageOps.exif_transpose(image).convert('RGB'), (w, h), Image.Resampling.LANCZOS)
                sheet.paste(thumb, (x+(w-thumb.width)//2, y+(h-thumb.height)//2))

        draw.text((20, 92), '原拼图 / 绿色为保留边界', font=small, fill='#26352c')
        boundary = out/'splits'/aid/'boundaries.jpg'
        paste(boundary if boundary.exists() else Path(row.get('source', '/nonexistent')), (20, 130, 430, 1100))
        for i, child in enumerate(row['children']):
            x = 475+i*355
            phase = {'before': '训练前', 'after': '训练后', 'unknown': '时间未知'}[child['phase']]
            draw.text((x, 92), f"子图 {i+1} · {phase} · 原尺寸裁切", font=small, fill='#26352c')
            paste(Path(child['source']), (x, 125, 335, 470))
            result = results.get(child['asset_id'], {})
            label = '校正 + 比例统一 + 矩形取景' if result.get('status') == 'rectangular' else '尚无通过校正的成品'
            draw.text((x, 625), label, font=small, fill='#26352c')
            if result.get('status') == 'rectangular':
                paste(out/'aligned'/child['asset_id']/'aligned.png', (x, 665, 335, 625))
            else:
                reason = result.get('reason', child.get('reason', '仅拆分 / 未运行校正'))
                draw.text((x, 690), str(reason)[:34], font=small, fill='#774532')
        if not row['children']:
            draw.text((480, 160), '未生成子图', font=font, fill='#774532')
            reason = row.get('layout', {}).get('seam', {}).get('reason', '')
            for n, start in enumerate(range(0, len(reason), 28)):
                draw.text((480, 220+30*n), reason[start:start+28], font=small, fill='#26352c')
        name = aid+'-review.jpg'
        sheet.save(out/name, quality=92)
        sections.append('<section><h2>'+html.escape(title)+'</h2><p>'+html.escape(row['status']+': '+description)
                        +'</p><img src="'+name+'" loading="lazy"></section>')
    (out/'index.html').write_text('<!doctype html><html lang="zh-CN"><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1"><title>硬拼接体测图拆分</title>'
        '<style>body{background:#eeeae3;color:#26352c;font:16px sans-serif;margin:28px}img{max-width:100%;height:auto}'
        'section{margin:32px 0}a{color:#405f43}</style><h1>硬拼接拆分验证</h1>'
        '<p>仅接受两张照片直接硬拼接。渐变拼接淘汰；边界不确定待复核。原始照片不改写。</p>'
        '<p><a href="body-scan-pairs-results.zip">下载图片和验证记录</a></p>'+''.join(sections)+'</html>', encoding='utf-8')
    with zipfile.ZipFile(out/'body-scan-pairs-results.zip', 'w', zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(out.rglob('*')):
            rel = path.relative_to(out)
            if (path.is_file() and path.suffix not in ('.zip', '.log') and 'aligned-pinhole' not in rel.parts
                    and not path.name.startswith('candidate-') and not path.name.endswith('-candidate.png')):
                archive.write(path, rel)

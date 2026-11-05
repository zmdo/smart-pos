"""Review sheets and downloadable aligned images, grouped by store/member."""
import html
import json
import zipfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps


def make_previews(out, records, groups, font_path, previous=None):
    out = Path(out)
    font = ImageFont.truetype(str(font_path), 22) if Path(font_path).exists() else ImageFont.load_default()
    small = ImageFont.truetype(str(font_path), 17) if Path(font_path).exists() else ImageFont.load_default()
    lookup = {r['asset_id']: r for r in records}
    prior_rows = {}
    if previous is not None:
        previous = Path(previous)
        prior_rows = {r['asset_id']: r for r in json.loads((previous/'summary.json').read_text(encoding='utf-8'))}
    labels = {'front': '前', 'back': '后', 'side_left': '左', 'side_right': '右', 'side': '侧'}
    links = []
    for group in groups:
        ids = group['asset_ids']
        if not ids:
            continue
        original_thumbs = {}
        for aid in ids:
            with Image.open(out / aid / 'original.png') as original:
                original_thumbs[aid] = ImageOps.contain(original.convert('RGB'), (230, 537), Image.Resampling.LANCZOS)
        output_y = 115 + max(im.height for im in original_thumbs.values()) + 65
        sheet_height = output_y + 595
        sheet = Image.new('RGB', (max(660, 250 * len(ids) + 20), sheet_height), '#eeeae3')
        draw = ImageDraw.Draw(sheet)
        title = group['store'] + ' / ' + group['member']
        draw.text((15, 10), title, font=font, fill='#26352c')
        draw.text((15, 48), '上：原图   下：统一比例、肩部对齐、最大矩形取景', font=small, fill='#26352c')
        for index, aid in enumerate(ids):
            row = lookup[aid]
            x = 15 + index * 250
            label = labels.get(row['classification'].get('view'), '?')
            label += ' / ' + aid
            draw.text((x, 83), label, font=small, fill='#26352c')
            thumb = original_thumbs[aid]
            sheet.paste(thumb, (x + (230-thumb.width)//2, 115))
            with Image.open(out / aid / 'aligned.png') as aligned:
                thumb = ImageOps.contain(aligned.convert('RGB'), (230, 537), Image.Resampling.LANCZOS)
                sheet.paste(thumb, (x + (230-thumb.width)//2, output_y))
            action = '网格校正' if row['route'] == 'grid' else ('非网格：相机校正' if row['geometry']['action'] == 'camera_pinhole' else '非网格：几何不变')
            draw.text((x, output_y - 40), action, font=small, fill='#26352c')
        if group['excluded_asset_ids']:
            draw.text((15, sheet_height - 35), '待复核：' + ', '.join(group['excluded_asset_ids']), font=small, fill='#9d513d')
        name = group['group_id'] + '-comparison.jpg'
        sheet.save(out / name, quality=92)
        links.append('<h2>' + html.escape(title) + '</h2><img src="' + name + '" loading="lazy">')
        # Full-resolution stitched output in front/back/left/right order.
        with Image.open(out / ids[0] / 'aligned.png') as first:
            dimensions = first.size
        strip = Image.new('RGB', (dimensions[0]*len(ids), dimensions[1]), '#eeeae3')
        for i, aid in enumerate(ids):
            with Image.open(out / aid / 'aligned.png') as image:
                strip.paste(image, (i*dimensions[0], 0))
        strip.save(out / (group['group_id'] + '-aligned.jpg'), quality=95)
        if previous is not None:
            upgrade = Image.new('RGB', (max(660, 250*len(ids)+20), 1250), '#eeeae3')
            ud = ImageDraw.Draw(upgrade)
            ud.text((15, 10), title, font=font, fill='#26352c')
            ud.text((15, 48), '上：上一版成品    下：接入相机校正后的成品', font=small, fill='#26352c')
            for index, aid in enumerate(ids):
                x = 15+index*250
                ud.text((x, 80), labels.get(lookup[aid]['classification'].get('view'), '?')+' / '+aid, font=small, fill='#26352c')
                old = prior_rows.get(aid, {})
                old_path = previous/aid/'aligned.png'
                matched = old.get('source_sha256') == lookup[aid].get('source_sha256') and old_path.exists()
                for path, y in ((old_path if matched else None, 112), (out/aid/'aligned.png', 680)):
                    if path is None:
                        ud.text((x, y+20), '暂无对应旧成品', font=small, fill='#9d513d')
                    else:
                        with Image.open(path) as image:
                            thumb = ImageOps.contain(image.convert('RGB'), (230, 537), Image.Resampling.LANCZOS)
                            upgrade.paste(thumb, (x+(230-thumb.width)//2, y))
            upgrade_name = group['group_id']+'-upgrade.jpg'
            upgrade.save(out/upgrade_name, quality=92)
            links.append('<h3>接入前后</h3><img src="'+upgrade_name+'" loading="lazy">')
    pending = [r for r in records if r['status'] == 'needs_review']
    links.append('<h2>待复核</h2><ul>' + ''.join('<li>' + html.escape(r['asset_id'] + ': ' + r['reason']) + '</li>' for r in pending) + '</ul>')
    mode_title = '非网格相机校正' if any(r.get('geometry', {}).get('action') == 'camera_pinhole' for r in records) else '非网格几何保持原样'
    (out / 'index.html').write_text('<!doctype html><meta charset="utf-8"><title>体测图取景预览</title>'
                                  '<style>body{background:#eeeae3;color:#26352c;font:16px sans-serif;margin:32px}img{max-width:100%}</style>'
                                  '<h1>体测图统一取景 · '+mode_title+'</h1>' + ''.join(links), encoding='utf-8')
    with zipfile.ZipFile(out / 'body-scan-results.zip', 'w', zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(out.rglob('*')):
            if path.is_file() and path.suffix != '.zip':
                archive.write(path, path.relative_to(out))

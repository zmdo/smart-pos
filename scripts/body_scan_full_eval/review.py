"""Source-bound contact sheets and all-image classifier comparison, on the server."""
import argparse
import html
import json
from collections import Counter
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

from scripts.body_scan.pipeline import save_json
from scripts.body_scan_phase.inputs import digest
from .sweep import is_reference


def build(root):
    root = Path(root)
    config = json.loads((root/'classification-deepseek/config.json').read_text())
    job_path = Path(config['job'])
    job = json.loads(job_path.read_text())
    providers = {p: {r['asset_id']: r for r in json.loads((root/('classification-'+p)/'summary.json').read_text())}
                 for p in ('deepseek', 'qwen')}
    rows = []
    for asset in job['assets']:
        aid = asset['id']
        if aid not in providers['deepseek']:
            continue
        source = (job_path.parent/'input'/asset['path']).resolve()
        record = {'asset_id': aid, 'store': asset.get('store'), 'member': asset.get('member'),
                  'source': str(source), 'source_sha256': digest(source), 'reference_material': is_reference(asset),
                  'old': asset.get('class') or {}}
        for p in providers:
            row = providers[p][aid]
            if row['source_sha256'] != record['source_sha256']:
                raise ValueError('source_changed')
            record[p] = row.get('classification', {})
        record['kind_agreement'] = record['deepseek'].get('kind') == record['qwen'].get('kind')
        record['body_candidate'] = any(record[p].get('kind') == 'body_scan' for p in ('old', 'deepseek', 'qwen'))
        rows.append(record)
    if len(rows) != len(providers['qwen']) or len(rows) != len(config['asset_ids']):
        raise ValueError('incomplete_model_coverage')
    save_json(root/'classification-comparison.json', rows)
    save_json(root/'background-candidate-ids.json', [r['asset_id'] for r in rows if r['body_candidate'] and not r['reference_material']])
    dest = root/'intake-review'; dest.mkdir(exist_ok=True)
    font = ImageFont.truetype('/root/autodl-fs/case-studio/fonts/NotoSansSC.ttf', 16)
    for name, selected in [('all', rows), ('candidates', [r for r in rows if r['body_candidate'] and not r['reference_material']]),
                           ('disagreements', [r for r in rows if not r['kind_agreement']])]:
        for start in range(0, len(selected), 20):
            sheet = Image.new('RGB', (1600, 1520), '#f5f4ef'); draw = ImageDraw.Draw(sheet)
            for index, row in enumerate(selected[start:start+20]):
                x = index%5*320; y = index//5*380
                with Image.open(row['source']) as im:
                    thumb = ImageOps.contain(ImageOps.exif_transpose(im).convert('RGB'), (310, 285), Image.Resampling.LANCZOS)
                    sheet.paste(thumb, (x+(320-thumb.width)//2, y+42+(285-thumb.height)//2))
                draw.text((x+6, y+2), row['asset_id']+' '+row['member'][:12], font=font, fill='#263e33')
                draw.text((x+6, y+23), '参考成品/说明' if row['reference_material'] else row['store'], font=font, fill='#52685b')
                if name != 'all':
                    draw.text((x+6, y+332), 'D: '+str(row['deepseek'].get('kind')), font=font, fill='#263e33')
                    draw.text((x+6, y+353), 'Q: '+str(row['qwen'].get('kind')), font=font, fill='#263e33')
            sheet.save(dest/f'{name}-{start//20+1:02d}.jpg', quality=92)
    text = '<!doctype html><meta charset="utf-8"><title>全量素材复核</title><style>body{font:16px sans-serif;background:#f5f4ef}img{max-width:100%}</style><h1>'+str(len(rows))+' 张门店静态图片全量盘点</h1>'
    for path in sorted(dest.glob('all-*.jpg')):
        text += '<img loading="lazy" src="'+html.escape(path.name)+'">'
    (dest/'index.html').write_text(text, encoding='utf-8')
    print(json.dumps({'total':len(rows), 'reference':sum(r['reference_material'] for r in rows),
        'candidate_inputs':sum(r['body_candidate'] and not r['reference_material'] for r in rows),
        'kind_disagreements':sum(not r['kind_agreement'] for r in rows)}, ensure_ascii=False))


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__); parser.add_argument('--root', type=Path, required=True)
    build(parser.parse_args().root)

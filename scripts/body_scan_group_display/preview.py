"""Portable comparison sheets and a read-only report, all derived from actual outputs."""
import html
import json
import zipfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

VARIANTS = [('baseline', '原标准化'), ('uniform', '统一取景 · 等比参考'), ('display', '展示版 · 轻微纵向调整')]


def make_previews(out):
    out = Path(out)
    items = json.loads((out/'summary.json').read_text(encoding='utf-8'))
    groups = json.loads((out/'groups.json').read_text(encoding='utf-8'))
    counts = json.loads((out/'counts.json').read_text(encoding='utf-8'))
    lookup = {r['asset_id']: r for r in items}
    font_path = Path('/root/autodl-fs/case-studio/fonts/NotoSansSC.ttf')
    font = ImageFont.truetype(str(font_path), 23) if font_path.exists() else ImageFont.load_default()
    small = ImageFont.truetype(str(font_path), 17) if font_path.exists() else font
    sheets = out/'previews'; sheets.mkdir(exist_ok=True)
    sections = []
    for group in groups:
        title = f"{group['group_id']} · {group['store']} / {group['member']}"
        sections.append('<section><h2>'+html.escape(title)+'</h2>')
        for cohort in group['cohorts']:
            accepted = [lookup[aid] for aid in cohort['asset_ids'] if lookup[aid]['status'] == 'displayed']
            if not accepted:
                sections.append('<p class="review">'+html.escape(cohort['cohort_id']+' · 待复核 · '+cohort.get('reason', ''))+'</p>')
                continue
            plan = cohort['plan']
            caption = (f"{plan['label']} · {len(accepted)} 张 · {plan['output_size'][0]}×{plan['output_size'][1]}"
                       f" · 纵向相对缩放 {plan['vertical_stretch']:.3f} · 同一肩部基准 / 同一取景框")
            sections.append('<h3>'+html.escape(caption)+'</h3>')
            # Split large cohorts into readable sheets; all pages use the same plan.
            for start in range(0, len(accepted), 6):
                page = accepted[start:start+6]
                width = max(900, 230*len(page)); cell = width/len(page)
                sheet = Image.new('RGB', (width, 1400), '#eeece5')
                draw = ImageDraw.Draw(sheet)
                draw.text((18, 12), title, font=font, fill='#26352c')
                draw.text((18, 46), caption, font=small, fill='#52624c')
                for row_number, (variant, label) in enumerate(VARIANTS):
                    top = 85+row_number*430
                    draw.text((18, top), label, font=font, fill='#26352c')
                    for i, item in enumerate(page):
                        path = out/'images'/item['asset_id']/(variant+'.png')
                        with Image.open(path) as im:
                            thumb = ImageOps.contain(im.convert('RGB'), (int(cell)-16, 365), Image.Resampling.LANCZOS)
                            sheet.paste(thumb, (round(cell*i+(cell-thumb.width)/2), top+36+(365-thumb.height)//2))
                        draw.text((round(cell*i+12), top+402), item['asset_id'], font=small, fill='#26352c')
                sheet.save(sheets/f"{cohort['cohort_id']}-{start//6+1}.jpg", quality=92)
            for variant, label in VARIANTS:
                sections.append('<details'+(' open' if variant == 'display' else '')+'><summary>'+label+'</summary><div class="photos">')
                for item in accepted:
                    rel = 'images/'+item['asset_id']+'/'+variant+'.png'
                    sections.append('<figure><a href="'+rel+'"><img loading="lazy" src="'+rel+'"></a><figcaption>'
                                    +html.escape(item['asset_id'])+'</figcaption></figure>')
                sections.append('</div></details>')
        if group['needs_review_asset_ids']:
            sections.append('<details><summary>待复核 '+str(len(group['needs_review_asset_ids']))+' 张</summary><ul>')
            for aid in group['needs_review_asset_ids']:
                item = lookup[aid]
                sections.append('<li>'+html.escape(aid+'：'+item.get('reason', ''))+'</li>')
            sections.append('</ul></details>')
        sections.append('</section>')
    (out/'index.html').write_text('<!doctype html><html lang="zh-CN"><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1"><title>同组统一取景与展示版</title>'
        '<style>body{max-width:1500px;margin:32px auto;padding:0 20px;background:#eeece5;color:#26352c;font:16px sans-serif}'
        'section{border-top:1px solid #ccd0c2;margin-top:36px;padding:20px 0}.photos{display:flex;gap:12px;overflow:auto}'
        'figure{margin:18px 0}img{height:400px;width:auto}summary{cursor:pointer;padding:12px 0}.review{color:#884a32}'
        'a{color:#405f43}</style><h1>同组统一取景与展示版</h1><p>同店同名 → 当前可见身体范围分组 → 肩部共同矩形 → 有限纵向调整。</p>'
        '<p>原标准化保留；等比参考不额外改变体形比例。展示版采用轻微非等比缩放，仅用于展示，不能用作真实体形测量。</p>'
        '<p>'+html.escape(str(counts['items']))+' · 上游未放行 '+str(counts['upstream_excluded'])+' 张</p>'
        '<p><a href="body-scan-group-display-results.zip">下载全部图片、对照图与记录</a> · <a href="verification.json">查看验证</a></p>'
        +''.join(sections)+'</html>', encoding='utf-8')
    with zipfile.ZipFile(out/'body-scan-group-display-results.zip', 'w', zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(out.rglob('*')):
            if path.is_file() and path.suffix not in ('.zip', '.log'):
                archive.write(path, path.relative_to(out))

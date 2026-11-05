"""Portable review page with labels/evidence; thumbnails keep aspect ratio."""
import html
import json
from collections import defaultdict
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

from .inputs import read_json

LABELS = {'before': '训练前', 'after': '训练后', 'unknown': '待复核'}
SOURCES = {'comparison_position_rule': '左右拼图规则', 'explicit_marker': '明确文字',
           'vlm_explicit_markers': '模型读取文字', 'vlm_appearance': '模型外观推断',
           'mixed_model_evidence': '模型多项证据', 'unresolved': '证据不足'}
VIEWS = {'front': '正面', 'back': '背面', 'side_left': '左侧', 'side_right': '右侧', 'side': '侧面'}
REASONS = {'no_same_view_counterpart': '当前输入中缺少同朝向配对照片',
           'not_comparable_pose_or_view': '姿势或朝向不具备可比性',
           'appearance_signals_conflict': '体形、体态或肌肉线索互相冲突',
           'insufficient_visual_evidence': '可见差异不足以可靠判断',
           'swapped_review_disagrees': '交换输入顺序后模型判断不一致',
           'swapped_review_insufficient': '交换顺序复核未达到接受条件',
           'pairwise_assignments_conflict': '同组多张照片的判断互相冲突',
           'identical_source_images': '两张照片实际为同一原图',
           'visible_marker_conflict': '外观判断与可见文字标记冲突'}


def preview(out):
    out = Path(out); items = read_json(out/'summary.json'); counts = read_json(out/'counts.json')
    comparisons = read_json(out/'comparisons.json')
    images = out/'previews'; images.mkdir()
    font_path = '/root/autodl-fs/case-studio/fonts/NotoSansSC.ttf'
    font = ImageFont.truetype(font_path, 18)
    groups = defaultdict(list); sections = []; esc = html.escape
    for item in items:
        groups[(item['store'], item['member'])].append(item)
        for field in ('source', 'uniform'):
            with Image.open(item[field]) as original:
                thumb = ImageOps.contain(ImageOps.exif_transpose(original).convert('RGB'), (440, 700), Image.Resampling.LANCZOS)
                thumb.save(images/f"{item['asset_id']}-{field}.jpg", quality=90)
    for number, (key, group) in enumerate(sorted(groups.items()), 1):
        title = ' / '.join(key)
        group.sort(key=lambda r: (('before', 'after', 'unknown').index(r['phase']), r['view'], r['asset_id']))
        sections.append('<section><h2>'+esc(title)+'</h2><div class="photos">')
        sheet = Image.new('RGB', (max(720, 230*len(group)), 560), '#f2f0e9')
        draw = ImageDraw.Draw(sheet); draw.text((12, 10), title, font=font, fill='#243b30')
        for i, item in enumerate(group):
            aid = item['asset_id']; label = LABELS[item['phase']]; origin = SOURCES[item['phase_source']]
            reason = REASONS.get(item['reason'], item['reason'])
            suggestion = item.get('suggestion', {})
            hint = ('AI初步建议：'+LABELS[suggestion['phase']]+'（未采用）') if suggestion else ''
            uniform = 'previews/'+aid+'-uniform.jpg'; source = 'previews/'+aid+'-source.jpg'
            sections.append('<article><h3>'+esc(label+' · '+VIEWS[item['view']])+'</h3><a href="'+uniform+'"><img src="'+uniform+'" loading="lazy"></a>'
                            '<p>'+esc(aid+' · '+origin)+'</p><p>'+esc(reason)+'</p>'
                            +('<p>'+esc(hint)+'</p>' if hint else '')
                            +('<p>模型置信度：'+str(round(item['confidence'], 3))+'</p>' if item['confidence'] is not None else '')
                            +'<details><summary>原图参考</summary><a href="'+source+'"><img src="'+source+'" loading="lazy"></a></details></article>')
            with Image.open(out/uniform) as im:
                thumb = ImageOps.contain(im, (214, 410), Image.Resampling.LANCZOS)
                sheet.paste(thumb, (i*230+(230-thumb.width)//2, 80))
            draw.text((i*230+10, 47), label+' · '+VIEWS[item['view']], font=font, fill='#243b30')
            draw.text((i*230+10, 500), aid, font=font, fill='#243b30')
            sheet_label = ('AI建议'+LABELS[suggestion['phase']]+' · 待核') if suggestion else origin
            draw.text((i*230+10, 527), sheet_label, font=font, fill='#57665d')
        sheet.save(images/f'g{number:03d}.jpg', quality=92)
        sections.append('</div></section>')
    details = []
    for pair in comparisons:
        decision = pair['decision']
        details.append('<details><summary>'+esc(pair['pair_id']+' · '+pair['member']+' · '+VIEWS[pair['view']]+' · '
                       +REASONS.get(decision['reason'], decision['reason']))+'</summary><div class="photos">')
        for aid in pair['asset_ids']:
            details.append('<article><h3>'+esc(aid)+'</h3><img src="previews/'+aid+'-source.jpg"><img src="previews/'+aid+'-uniform.jpg"></article>')
        details.append('</div><pre>'+esc(json.dumps(pair, ensure_ascii=False, indent=2))+'</pre></details>')
    (out/'index.html').write_text('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
        '<title>训练前后标注复核</title><style>body{max-width:1550px;margin:32px auto;padding:0 20px;background:#f2f0e9;color:#243b30;font:16px sans-serif}'
        '.photos{display:flex;gap:16px;overflow:auto}article{min-width:230px;max-width:270px}img{height:390px;max-width:270px;object-fit:contain}'
        'p{line-height:1.6}section{border-top:1px solid #ccd3c9;margin:24px 0}pre{white-space:pre-wrap}summary{cursor:pointer;padding:12px 0}a{color:#365b42}</style>'
        '<h1>训练前后标注</h1><p>左右对比图：左前右后。无标记的同组同朝向照片：比较体形、体态、肌肉；通过交换顺序复核后采用。'
        '这里展示等比参考，未使用非等比展示版判断。</p><p>模型外观推断不代表已核实的拍摄时间；差异不明确、线索冲突或缺少配对的照片保留待复核。</p>'
        '<p>当前验证子集 '+str(counts['total'])+' 张：'+esc(str(counts['phases']))+'；不是整个上传包。</p>'
        '<p>其中 '+str(counts.get('tentative_suggestions', 0))+' 张保留AI初步建议，未进入已采用的训练前后槽位。</p>'
        '<p><a href="summary.json">完整标签</a> · <a href="slots.json">成品槽位候选</a> · <a href="comparisons.json">模型原始判断</a></p>'
        +''.join(sections)+'<h2>逐对比较依据</h2>'+''.join(details)+'</html>', encoding='utf-8')

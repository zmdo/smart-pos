"""Offline review of session membership, decisions and original photographs."""
import html
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

from scripts.body_scan_phase.inputs import read_json
from scripts.body_scan_phase.preview import LABELS, VIEWS

SOURCES = {'comparison_position_rule': '左右拆分规则', 'explicit_marker': '明确文字',
           'vlm_explicit_markers': '双向读取文字', 'session_marker_propagation': '同批次文字标签',
           'session_visual_propagation': 'AI推断 · 同批次继承', 'multi_view_observation': 'AI推断 · 多朝向印证',
           'paired_clear_observation': 'AI推断 · 清楚变化', 'unresolved': '待复核'}
REASONS = {'session_assignment_conflict': '同组判断存在冲突，未自动采用',
           'single_subtle_view': '仅一个朝向有轻微变化，保留建议',
           'no_same_view_counterpart': '当前输入缺少可比较的同朝向照片',
           'no_usable_difference': '未观察到足以排序的差异', 'not_comparable': '姿势、朝向或可见范围不可比',
           'swapped_direction_conflict': '交换输入顺序后方向相反', 'swapped_evidence_insufficient': '换序复核证据不足',
           'consistent_visual_evidence': '可见变化通过一致性规则', 'reliable_session_marker': '可靠同批次已有阶段标签',
           'accepted_single_clear': '采用：清楚变化且换序一致', 'accepted_multi_view': '采用：多个朝向相互印证',
           'tentative': '初步建议：单朝向轻微变化', 'cross_view_conflict': '不同朝向指向相反阶段',
           'reliable_marker_conflict': '与可靠标签冲突', 'connected_assignment_conflict': '关联批次判断存在冲突',
           'observation_directions_conflict': '不同外观线索方向冲突', 'same_session_not_chronological_comparison': '同批次不推断先后'}
FIELDS = {'leaner': '更瘦／腰腹收紧', 'better_posture': '体态偏差较轻', 'more_muscular': '肌肉更明显'}


def preview(out):
    out = Path(out); rows = read_json(out/'summary.json'); groups = read_json(out/'groups.json'); counts = read_json(out/'counts.json')
    lookup = {r['asset_id']: r for r in rows}; esc = html.escape
    dest = out/'previews'; dest.mkdir()
    font = ImageFont.truetype('/root/autodl-fs/case-studio/fonts/NotoSansSC.ttf', 18)
    for row in rows:
        for kind in ('source', 'uniform'):
            with Image.open(row[kind]) as im:
                ImageOps.contain(ImageOps.exif_transpose(im).convert('RGB'), (480, 760), Image.Resampling.LANCZOS).save(
                    dest/f"{row['asset_id']}-{kind}.jpg", quality=91)
    content = []
    for group in groups:
        title = group['group_id']+' · '+group['store']+' / '+group['member']
        content.append('<section><h2>'+esc(title)+'</h2>')
        units = sorted(group['units'], key=lambda u: (('before', 'after', 'unknown').index(u.get('phase', 'unknown')), u['unit_id']))
        members = [lookup[aid] for unit in units for aid in unit['members']]
        sheet = Image.new('RGB', (max(720, 230*len(members)), 610), '#f2f0e9'); draw = ImageDraw.Draw(sheet)
        draw.text((12, 12), title, font=font, fill='#263e33')
        for i, row in enumerate(members):
            aid = row['asset_id']
            with Image.open(dest/(aid+'-uniform.jpg')) as im:
                thumb = ImageOps.contain(im, (214, 400), Image.Resampling.LANCZOS)
                sheet.paste(thumb, (i*230+(230-thumb.width)//2, 85))
            draw.text((i*230+8, 48), LABELS[row['phase']]+' · '+VIEWS[row['view']], font=font, fill='#263e33')
            draw.text((i*230+8, 505), aid, font=font, fill='#263e33')
            draw.text((i*230+8, 535), SOURCES[row['phase_source']], font=font, fill='#52685b')
            draw.text((i*230+8, 566), row['session_id'], font=font, fill='#52685b')
        sheet.save(dest/(group['group_id']+'.jpg'), quality=93)
        for unit in units:
            joined = unit['membership'] == 'reviewed_session'
            content.append('<h3>'+esc(unit['unit_id']+' · '+('拍摄批次归属已复核' if joined else '单张保留，未跨图并批'))+'</h3>')
            if joined:
                content.append('<p>'+esc(unit['session_evidence']['reason'])+'</p>')
            content.append('<div class="photos">')
            for aid in unit['members']:
                row = lookup[aid]; suggestion = row.get('suggestion')
                hint = '<p class="hint">AI初步建议：'+LABELS[suggestion['phase']]+'（未采用）</p>' if suggestion else ''
                content.append('<article><b class="'+row['phase']+'">'+LABELS[row['phase']]+'</b> · '+VIEWS[row['view']]
                    +'<a href="previews/'+aid+'-uniform.jpg"><img src="previews/'+aid+'-uniform.jpg" loading="lazy"></a>'
                    +'<p>'+esc(aid+' · '+SOURCES[row['phase_source']])+'</p><p>'+esc(REASONS.get(row['reason'], row['reason']))+'</p>'+hint
                    +'<details><summary>原图参考</summary><a href="previews/'+aid+'-source.jpg"><img src="previews/'+aid+'-source.jpg" loading="lazy"></a></details></article>')
            content.append('</div>')
        content.append('<details><summary>拍摄批次分组依据</summary><pre>'+esc(json.dumps(group['session_candidates'], ensure_ascii=False, indent=2))+'</pre></details>')
        for pair in group['comparisons']:
            a, b = pair['asset_ids']; decision = pair['decision']; result = pair.get('resolution', decision['reason'])
            content.append('<details><summary>'+esc(a+' ↔ '+b+' · '+REASONS.get(result, result))+'</summary><div class="photos">')
            for aid in (a, b):
                content.append('<article><p>'+esc(('A' if aid == a else 'B')+' = '+aid)+'</p><img src="previews/'+aid+'-source.jpg" loading="lazy"></article>')
            content.append('</div><table><tr><th>观察项</th><th>初次</th><th>换序复核（映射回原编号）</th></tr>')
            for key, title2 in FIELDS.items():
                cells = []
                for stage in ('primary', 'swapped'):
                    raw = pair['audit'].get(stage, {}).get('result', {})
                    observations = raw.get('observations', {}) if isinstance(raw, dict) else {}
                    value = observations.get(key) if isinstance(observations, dict) else None
                    if not isinstance(value, dict):
                        cells.append('未取得有效结果'); continue
                    image = value.get('image', 'unknown')
                    if stage == 'swapped':
                        image = {'A':'B', 'B':'A'}.get(image, image)
                    label = {'A': a, 'B': b, 'equal':'无明显变化', 'unknown':'无法判断'}.get(image, '无法判断')
                    strength = {'clear':'清楚', 'subtle':'轻微', 'none':'无依据'}.get(value.get('clarity'), '')
                    cells.append(label+' · '+strength+(' · 受拍摄因素影响' if value.get('confounded') else '')+'：'+str(value.get('reason', '')))
                content.append('<tr><td>'+title2+'</td><td>'+esc(cells[0])+'</td><td>'+esc(cells[1])+'</td></tr>')
            content.append('</table><details><summary>完整调用与判定记录</summary><pre>'+esc(json.dumps(pair, ensure_ascii=False, indent=2))+'</pre></details></details>')
        content.append('</section>')
    baseline_path = out/'baseline-comparison.json'
    baseline = read_json(baseline_path) if baseline_path.exists() else None
    intro = ('上一版：'+str(baseline['before'])+' → 本版：'+str(counts['phases'])) if baseline else str(counts['phases'])
    (out/'index.html').write_text('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
        '<title>训练前后 · 拍摄批次与多朝向判断</title><style>body{max-width:1520px;margin:32px auto;padding:0 22px;background:#f2f0e9;color:#263e33;font:16px sans-serif}'
        'h1{font-size:30px}.photos{display:flex;gap:20px;overflow:auto}article{min-width:230px;max-width:280px}img{display:block;height:390px;max-width:280px;object-fit:contain;margin-top:12px}'
        'p{line-height:1.65}section{border-top:1px solid #c8d2c8;margin-top:32px}summary{padding:12px 0;cursor:pointer}pre{white-space:pre-wrap;overflow-wrap:anywhere}'
        'table{width:100%;border-collapse:collapse}td,th{border:1px solid #c8d2c8;padding:10px;text-align:left}.before{color:#74559a}.after{color:#237246}.unknown,.hint{color:#956324}a{color:#315c45}</style>'
        '<h1>训练前后：先分批次，再综合变化</h1><p>左右拆分规则优先。其余比较原图和等比参考，先描述变化，再映射前后；清楚变化经换序复核可采用，轻微变化需可靠批次的多个朝向印证。置信度作为参考。</p>'
        '<p>AI标签属于外观推断；批次归属不可靠时不传播标签，冲突不靠多数票消除。原图与既有成品保留。</p><p>'+esc(intro)+'</p><p>'
        +str(counts['total'])+' 张 · '+str(counts['groups'])+' 人 · '+str(counts['reviewed_multi_image_sessions'])+' 个复核通过的多图批次 · 当前验证子集，非完整上传包。</p>'
        '<p><a href="summary.json">标签记录</a> · <a href="groups.json">分组与判断证据</a> · <a href="slots.json">成品槽位</a> · <a href="verification.json">校验</a></p>'
        +''.join(content)+'</html>', encoding='utf-8')

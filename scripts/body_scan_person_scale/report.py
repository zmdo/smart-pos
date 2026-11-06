"""Make remote-rendered before/after review sheets, with numerical limitations."""
import argparse
import html
import json
from collections import Counter
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from scripts.body_scan.geometry import project
from scripts.body_scan.landmarks import member_key
from scripts.body_scan.pipeline import save_json, VIEW_ORDER
from .solve import spread


def read(path):
    return json.loads(Path(path).read_text())


def torso_length(row):
    kp = np.asarray(row['upstream_report']['pose']['keypoints_source'])
    points = project(kp[:, :2], np.asarray(row['output']['H_source_to_display']))
    pairs = row['upstream_report']['pose']['selected_pairs']
    return float(np.mean([np.linalg.norm(points[b]-points[a]) for a, b in pairs]))


def sheet(ids, old, new, before, after, dest, title, font):
    width, height = 220, 514
    canvas = Image.new('RGB', (width*len(ids)+40, 2*(height+65)+100), '#f2f0e9')
    draw = ImageDraw.Draw(canvas)
    draw.text((20, 12), title, font=font, fill='#243b32')
    for j, (lookup, root, label) in enumerate(((old, before, '原版'), (new, after, '新实验'))):
        y = 65+j*(height+65)
        for i, aid in enumerate(ids):
            x = 20+i*width; row = lookup[aid]
            if row['status'] == 'displayed':
                im = Image.open(root/'images'/aid/'display.png').convert('RGB')
                im.thumbnail((width-8, height))
                canvas.paste(im, (x+(width-8-im.width)//2, y+50))
            else:
                draw.text((x, y+90), '待复核', font=font, fill='#9c472c')
            draw.text((x, y), f'{label} {aid}', font=font, fill='#243b32')
            size = row.get('group_plan', {}).get('output_size')
            draw.text((x, y+23), str(size or row['status']), font=font, fill='#62736b')
    canvas.save(dest, quality=92)


def run(standardized, before, after, out, font_path, focus_ids=None):
    standardized, before, after, out = map(Path, (standardized, before, after, out))
    out.mkdir(parents=True, exist_ok=False)
    rows = read(standardized/'summary.json')
    old = {r['asset_id']: r for r in read(before/'summary.json')}
    new = {r['asset_id']: r for r in read(after/'summary.json')}
    font = ImageFont.truetype(str(font_path), 18)
    groups = {}; metrics = []; sections = []
    for r in rows:
        if r['status'] == 'rectangular':
            groups.setdefault(member_key(r), []).append(r)
    for index, (key, members) in enumerate(sorted(groups.items()), 1):
        members.sort(key=lambda r: (VIEW_ORDER.get(r['classification']['view'], 5), r['asset_id']))
        ids = [r['asset_id'] for r in members]; name = f'group-{index:02d}.jpg'
        title = '/'.join(key)
        sheet(ids, old, new, before, after, out/name, title+' · 上：原版 / 下：新实验', font)
        grid = {}
        for row in members:
            audit = row['person_scale']; pitch = audit.get('background', {}).get('grid_pitch')
            if pitch:
                grid.setdefault(audit['semantic']['background_group'], []).append((row, pitch))
        grid_metrics = []
        for bg, candidates in grid.items():
            if len(candidates) >= 2:
                grid_metrics.append({'background_group': bg, 'asset_ids': [r['asset_id'] for r, _ in candidates],
                    'old_grid_scale_spread': spread([p*r['person_scale']['previous_frame']['uniform_scale'] for r, p in candidates]),
                    'new_grid_scale_spread': spread([p*r['frame']['uniform_scale'] for r, p in candidates])})
        metrics.append({'store': key[0], 'member': key[1], 'assets': ids, 'grid_scale_consistency': grid_metrics})
        table = []
        for r in members:
            a = r['person_scale']; aid = r['asset_id']; labels = {'calibrated': '已校准', 'retained': '小于2%，保留', 'retained_for_review': '保留并待复核'}
            details = a.get('reason', '')+'; '+'; '.join(a.get('review_reasons', []))
            table.append(f'<tr><td>{html.escape(aid)}</td><td>{labels[a["status"]]}</td>'
                         f'<td>{(a["relative_scale"]-1)*100:+.2f}%</td><td>{html.escape(details)}</td></tr>')
        sections.append(f'<section><h2>{html.escape(title)}</h2><a href="{name}"><img src="{name}"></a>'
                        '<table><tr><th>图片</th><th>尺度处理</th><th>等比缩放变化</th><th>依据/复核原因</th></tr>'+''.join(table)+'</table></section>')
    focus = None
    if focus_ids:
        if any(i not in new or new[i]['status'] != 'displayed' or old[i]['status'] != 'displayed' for i in focus_ids):
            raise ValueError('focus_requires_displayed_images')
        sheet(focus_ids, old, new, before, after, out/'focus.jpg', '重点对比 · 上：原版 / 下：新实验', font)
        lengths = {i: {'old': torso_length(old[i]), 'new': torso_length(new[i])} for i in focus_ids}
        focus = {'asset_ids': focus_ids, 'visible_shoulder_hip_pixels': lengths,
                 'old_length_spread': spread([v['old'] for v in lengths.values()]),
                 'new_length_spread': spread([v['new'] for v in lengths.values()]),
                 'limitation': '2D shoulder-hip lengths vary with pose; this is a diagnostic, not physical height ground truth'}
    summary = {'groups': metrics, 'focus': focus, 'calibration_counts': dict(Counter(r['person_scale']['status'] for r in rows if r['status']=='rectangular')),
               'display_counts': read(after/'counts.json'), 'source_verification': read(standardized/'verification.json')}
    save_json(out/'metrics.json', summary)
    page = '''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>同人尺度校准实验</title>
<style>body{font:16px system-ui;max-width:1450px;margin:40px auto;padding:0 24px;color:#253e34;background:#f6f5ef}h1{font-size:30px}p{line-height:1.8}section{background:white;padding:24px;margin:30px 0;border-radius:12px}img{max-width:100%;display:block}table{width:100%;border-collapse:collapse;font-size:13px}th,td{text-align:left;padding:10px;border-bottom:1px solid #ddd}td:last-child{overflow-wrap:anywhere}</style>
<h1>同一人物：共同尺度 → 肩部定位 → 同一取景框</h1>
<p>上排原版，下排新实验，点击图片查看大图。每张只调整等比尺度和位置，沿用已批准的镜头几何；最终展示版沿用组内统一画幅和共享比例调整。保留待复核的图片仍是原尺度，不能视为已校准成功。</p>
<p>网格间距用于验证同一背景下的尺度一致性，不等于真实身高；肩髋长度受姿势影响，只作为辅助诊断。所有原图、旧成品和最佳实践保留。</p>'''
    if focus:
        page += '<section><h2>重点样例</h2><a href="focus.jpg"><img src="focus.jpg"></a></section>'
    (out/'index.html').write_text(page+''.join(sections)+'<p><a href="metrics.json">完整验证数据</a></p></html>', encoding='utf-8')
    return summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('standardized', 'before', 'after', 'out'):
        parser.add_argument('--'+name, type=Path, required=True)
    parser.add_argument('--font', type=Path, default=Path('/root/autodl-fs/case-studio/fonts/NotoSansSC.ttf'))
    parser.add_argument('--focus', nargs='+')
    a = parser.parse_args()
    run(a.standardized, a.before, a.after, a.out, a.font, a.focus)

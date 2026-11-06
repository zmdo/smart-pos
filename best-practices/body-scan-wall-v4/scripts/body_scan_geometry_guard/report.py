"""Compare an experimental run to an immutable prior display, with actual file hashes."""
import argparse
import html
import json
import math
from collections import defaultdict
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageOps

from scripts.body_scan.geometry import project
from scripts.body_scan.pipeline import save_json, VIEW_ORDER
from .pipeline import digest

FONT = Path('/root/autodl-fs/case-studio/fonts/NotoSansSC.ttf')


def torso_angle(row, H):
    kp = np.asarray(row['pose']['keypoints_source'])
    pairs = row['pose']['selected_pairs']
    points = [kp[[p[0] for p in pairs], :2].mean(axis=0), kp[[p[1] for p in pairs], :2].mean(axis=0)]
    a, b = project(points, H)
    return math.degrees(math.atan2(b[0]-a[0], b[1]-a[1]))


def put_image(sheet, path, box):
    x, y, width, height = box
    with Image.open(path) as im:
        thumb = ImageOps.contain(im.convert('RGB'), (width, height), Image.Resampling.LANCZOS)
    sheet.paste(thumb, (x+(width-thumb.width)//2, y+(height-thumb.height)//2))


def build(root, previous):
    root, previous = Path(root), Path(previous)
    standardized = root/'standardized'; current = root/'display'
    verification = json.loads((standardized/'verification.json').read_text())
    rows = json.loads((standardized/'summary.json').read_text())
    new = {r['asset_id']: r for r in json.loads((current/'summary.json').read_text())}
    old = {r['asset_id']: r for r in json.loads((previous/'summary.json').read_text())}
    font = ImageFont.truetype(str(FONT), 24); small = ImageFont.truetype(str(FONT), 18)
    previews = root/'comparison'; previews.mkdir(exist_ok=True)
    changed_groups = {(r['store'], r['member']) for r in rows if r['asset_id'] in verification['changed_asset_ids']}
    grouped = defaultdict(list); same = []; different = []; measurements = {}
    for row in rows:
        if row['status'] != 'rectangular':
            continue
        aid = row['asset_id']; key = (row['store'], row['member'])
        grouped[key].append(row)
        if aid not in old or aid not in new or old[aid]['source_sha256'] != row['source_sha256']:
            raise ValueError('comparison_source_mismatch: '+aid)
        if new[aid]['status'] != 'displayed':
            raise ValueError('new_display_missing: '+aid)
        matches = all(digest(current/'images'/aid/(name+'.png')) == digest(previous/'images'/aid/(name+'.png'))
                      for name in ('uniform', 'display'))
        (same if matches else different).append(aid)
        if key not in changed_groups and not matches:
            raise AssertionError('unaffected_group_display_changed: '+aid)
        if aid in verification['changed_asset_ids']:
            before = old[aid]['upstream_report']; H = np.asarray(before['geometry']['H_source_to_corrected'])
            measurements[aid] = {'original_torso_axis_deg': torso_angle(row, np.eye(3)),
                'previous_torso_axis_deg': torso_angle(before, H),
                'new_torso_axis_deg': torso_angle(row, np.asarray(row['geometry']['H_source_to_corrected'])),
                'wall_metrics': row['geometry_guard']['wall_metrics'], 'decision': row['geometry_guard']['reason']}
    result = {**verification, 'displayed': len(same)+len(different), 'display_byte_identical_ids': same,
              'display_changed_ids': different, 'changed_group_names': [list(g) for g in sorted(changed_groups)],
              'measurements': measurements, 'unaffected_group_display_byte_identical': True}
    save_json(root/'validation.json', result)
    parts = ['<h1>非网格校正检查 · 小批量对照</h1>',
             f'<p>{len(grouped)} 组 / {len(same)+len(different)} 张。标准化回退 {len(verification["changed_asset_ids"])} 张，'
             f'其余 {len(verification["byte_identical_asset_ids"])} 张标准化成品及遮罩逐字节不变。'
             f'最终展示 {len(same)} 张逐字节不变；{len(different)} 张发生变化，逐张记录如下。</p>',
             '<p>原图与旧结果保持不变。人物姿态没有被强行扶正；只撤回缺乏可靠支持的相机变换。'
             '本页属于独立实验，尚未替换默认流程或最佳实践。</p>',
             '<p><a href="display/index.html">新组图及下载</a> · <a href="validation.json">校验记录</a></p>']
    for row in rows:
        aid = row['asset_id']
        if aid not in measurements:
            continue
        title = row['store']+' / '+row['member']+' · '+aid
        sheet = Image.new('RGB', (1260, 1020), '#f2efe7'); draw = ImageDraw.Draw(sheet)
        draw.text((25, 18), title, fill='#293b32', font=font)
        for i, (label, path) in enumerate([
            ('原始单图（几何未变）', row['source']),
            ('旧版最终展示', previous/'images'/aid/'display.png'),
            ('检查回退后最终展示', current/'images'/aid/'display.png')]):
            draw.text((25+i*415, 65), label, fill='#293b32', font=small)
            put_image(sheet, path, (20+i*415, 110, 390, 800))
        m = measurements[aid]
        draw.text((25, 940), f'肩髋轴线偏离竖直：原图 {abs(m["original_torso_axis_deg"]):.2f}° → '
                  f'旧版 {abs(m["previous_torso_axis_deg"]):.2f}° → 回退 {abs(m["new_torso_axis_deg"]):.2f}°',
                  fill='#293b32', font=small)
        draw.text((25, 975), '角度仅用于说明变化，不作为人物扶正目标。', fill='#617365', font=small)
        filename = 'focus-'+aid+'.jpg'; sheet.save(previews/filename, quality=94)
        parts.append('<h2>'+html.escape(title)+'</h2><img src="comparison/'+filename+'">')
    group_records = []
    for number, (key, members) in enumerate(sorted(grouped.items()), 1):
        members.sort(key=lambda r: (VIEW_ORDER.get(r['classification'].get('view'), 5), r['asset_id']))
        width = max(900, len(members)*230+25)
        sheet = Image.new('RGB', (width, 1230), '#f2efe7'); draw = ImageDraw.Draw(sheet)
        title = ' / '.join(key)
        draw.text((20, 12), title, font=font, fill='#293b32')
        draw.text((20, 50), '上：旧版最终展示    下：本次实验最终展示（同组同尺寸）', font=small, fill='#293b32')
        for i, row in enumerate(members):
            aid = row['asset_id']; x = 15+i*230
            draw.text((x, 85), aid, font=small, fill='#293b32')
            put_image(sheet, previous/'images'/aid/'display.png', (x, 120, 215, 490))
            put_image(sheet, current/'images'/aid/'display.png', (x, 690, 215, 490))
        size = new[members[0]['asset_id']]['group_plan']['output_size']
        assert all(new[r['asset_id']]['group_plan']['output_size'] == size for r in members)
        draw.text((20, 640), f'本组统一尺寸：{size[0]} × {size[1]}', font=font, fill='#293b32')
        filename = f'group-{number:02d}.jpg'; sheet.save(previews/filename, quality=92)
        label = '整组最终成品逐字节不变' if key not in changed_groups else '仅本组重新计算共同取景'
        parts.append('<h2>'+html.escape(title)+' · '+label+'</h2><img loading="lazy" src="comparison/'+filename+'">')
        group_records.append({'store': key[0], 'member': key[1], 'preview': 'comparison/'+filename,
                              'output_size': size, 'asset_ids': [r['asset_id'] for r in members]})
    save_json(root/'comparison-groups.json', group_records)
    (root/'index.html').write_text('<!doctype html><html lang="zh"><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1"><title>非网格校正检查对照</title>'
        '<style>body{max-width:1500px;margin:32px auto;padding:0 24px;background:#f2efe7;color:#293b32;'
        'font:17px/1.7 sans-serif}img{max-width:100%;height:auto}a{color:#315d4b}h2{margin-top:48px}</style>'
        + ''.join(parts)+'</html>', encoding='utf-8')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--previous-display', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.root, args.previous_display), ensure_ascii=False, indent=2))

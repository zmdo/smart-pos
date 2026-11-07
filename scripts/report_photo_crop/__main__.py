"""Crop a fixed-ratio rectangle directly from original report pixels."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import html
import json
from pathlib import Path
import re

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageOps

from scripts.body_scan_full_eval.client import MeasuredClient
from .geometry import make_frame, parse_ratio

VERSION = 'report-photo-crop-v3'
LOCALIZATION_VERSION = 'report-photo-rect-localization-v1'
PROMPT = '''你是报告图片取景助手。只判断原图中的有效报告区域，不修改图片、不展平、不推断训练前后。
坐标全部为相对于整张输入图片的0到1000归一化坐标，左上为(0,0)、右下为(1000,1000)。
先分成 screenshot（电子文档/电子表格/手机电脑截图或平整电子导出图）、paper_photo（实拍纸张）、other。
电子截图：content_box紧贴所有有用的报告正文，包含正文标题、身份/日期、指标表格、报告结论、教练备注等；
排除手机状态栏、文档查看器标题栏/工具栏、推荐功能按钮、翻页提示，以及正文上下左右大块空白。
正文标题（如UP健身会员阶段性训练成果报告）要保留，应用程序标题栏不保留。表格最下方文字和末行不能截断。
实拍纸张：定位主要报告纸张的全部可见部分，包含标题、日期、全部表格和报告页脚；
paper_box为主纸张的轴对齐外接矩形框，排除桌面、墙和旁边其他纸张的大块外围区域。
不要把正文内部的图表/小人当成纸张边界。边缘在画面外时用画面边界。不要为了矩形而裁掉斜纸张四角。
content_box覆盖主纸张可见的所有有用文字图表（可以比paper_box小），用于优先完整保留正文。
只输出矩形范围，不需要多边形或蒙版。矩形中包含的少量背景将作为原图的一部分保留。
卷曲、倾斜和折痕保持原样。不应把相邻报告或卷起的另一张纸上的字算作主报告正文。
若上方有翻起的纸页背面、倒置文字或右侧有另一份报告，这些是外围杂物；
paper_box应从正常阅读方向的主要报告纸面边缘开始，不要把整张照片直接当成纸张。
纸张铺满画面、确实没有外围杂物时才可以选择整幅。content_box同样不能把这些额外纸页的文字包含进来。
若纸张正文有遮挡、裁断、边界不确定，请在issues说明，不能补造缺失信息。
不要输出报告数值的转录。confidence表示你对区域定位的主观把握，不是核验正确率。
仅返回JSON：{"is_report":true,"medium":"screenshot|paper_photo|other",
"content_box":[x1,y1,x2,y2],"paper_box":[x1,y1,x2,y2],
"confidence":0.0,
"reason":"中文说明为什么这样取景","issues":["需关注的问题"]}。
电子截图的paper_box为null。无法可靠定位则medium=other并给原因。'''

PRIORITY_VERSION = 'report-photo-priority-v2'
PRIORITY_PROMPT = '''你只负责定位报告中的主要数据区域，不负责设计取景框或计算比例，不修改图像。
程序会根据你的区域定位另行计算矩形取景范围；因此你不能声称最终裁剪已完整保留某列或某行。
对于训练报告/电子表格：最优先定位“指标名称+训练前数值+训练后数值”三个核心列；
特别是宽表格，应紧贴这三列，不要把右侧的变化量、单位列也塞进primary_box。变化量/单位作为次要内容可舍弃。
对于InBody或其他体测报告：优先身体成分、体重、骨骼肌、体脂、BMI、腰臀比等主要指标，评分与测试日期能保留则保留。
标题Logo、会员介绍、教练介绍、训练目标、宣传文字、运动处方/运动消耗表、版权页脚的优先级低于核心指标，可裁掉。
primary_box必须紧贴主要数据，不要为了包含低优先级内容而框整页。
坐标是相对于整张输入图的0到1000归一化坐标。不要转录数值，不判断训练阶段顺序，不编造不可见信息。
只报告真实核心区域，不要把归一化坐标比例当成图像实际比例，不要给取景方案。取景完整性由程序计算。
仅输出JSON：{"primary_box":[x1,y1,x2,y2],"reason":"主要内容是什么以及取景优先级",
"can_crop_away":["允许舍弃的次要部分"],"issues":["定位不确定或核心无法全部容纳的问题"]}。'''


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def sources(audit_path, root, ids):
    rows, seen = [], set()
    for row in json.loads(audit_path.read_text()):
        if row.get('qwen', {}).get('kind') not in ('body_report', 'training_report'):
            continue
        aid = row['asset_id']
        if ids and aid not in ids:
            continue
        relative = row['source'].split('/私教会员案例项目/', 1)[-1]
        parts = Path(relative).parts
        if not parts or not parts[0].endswith('店') or parts[0] != row['store']:
            raise ValueError('not_store_material')
        path = (root/relative).resolve()
        if not path.is_relative_to(root.resolve()):
            raise ValueError('source_path_escape')
        if not re.fullmatch(r'a[0-9]+', aid) or aid in seen:
            raise ValueError('invalid_or_duplicate_asset_id')
        if sha(path) != row['source_sha256']:
            raise ValueError('source_hash_mismatch: ' + aid)
        seen.add(aid)
        rows.append((row, path))
    if not rows or (ids and ids != seen):
        raise ValueError('missing_requested_report')
    return rows


def reused_selections(path, selected):
    prior = json.loads(path.read_text())
    if prior.get('version') not in ('report-photo-crop-v1', 'report-photo-crop-v2', VERSION):
        raise ValueError('unsupported_selection_bundle')
    rows = prior['rows']
    indexed = {r['asset_id']: r for r in rows}
    if len(indexed) != len(rows):
        raise ValueError('duplicate_prior_asset_ids')
    for current, _ in selected:
        record = indexed.get(current['asset_id'])
        if (not record or record.get('source_sha256') != current['source_sha256']
                or not isinstance(record.get('selection'), dict)):
            raise ValueError('selection_source_mismatch: ' + current['asset_id'])
    return indexed


def gallery(out, rows, ratio):
    cards = []
    for row in rows:
        aid = row['asset_id']
        label = html.escape(f"{row['store']} / {row['member']} · {aid}")
        if 'geometry' not in row:
            cards.append(f'<section id="{aid}" data-status="needs_review"><h2>{label}</h2><p>未生成：{html.escape(row["error"])}</p></section>')
            continue
        e = row['geometry']
        kind = '电子截图：正文矩形取景' if e['medium'] == 'screenshot' else '纸张照片：原图矩形取景'
        notes = html.escape('；'.join(e['review_reasons']) or '暂无明确缺失；请检查正文边缘。')
        completeness = ('已包住正文定位框' if e['content_fully_contained'] else
                        '主要内容优先 · 完整保留核心定位区域' if e['priority_fully_contained'] else '核心内容仍超框 · 待审核')
        download = '下载高清裁剪图' if row['status'] == 'cropped' else '下载受限候选（待审核）'
        priority_note = html.escape(row.get('priority', {}).get('reason', ''))
        cards.append(f'<section id="{aid}" data-kind="{e["medium"]}" data-priority="{str(e["priority_used"]).lower()}" data-status="{row["status"]}"><h2>{label}</h2>'
                     f'<p>{kind} · {completeness} · 核心框覆盖 {e["priority_box_coverage"]:.1%}</p>'
                     f'<div class="pair"><figure><figcaption>原图中的实际取景框</figcaption><a href="{aid}/original.png" target="_blank">'
                     f'<img loading="lazy" src="{aid}/framing-preview.jpg"></a></figure>'
                     f'<figure><figcaption>固定比例 {ratio[0]}:{ratio[1]} · {e["frame_size"][0]} × {e["frame_size"][1]}</figcaption>'
                     f'<a href="{aid}/frame.png" target="_blank"><img loading="lazy" src="{aid}/frame-preview.jpg"></a></figure></div>'
                     f'<p>{priority_note}</p><p>{notes}</p><a href="{aid}/frame.png" download>{download}</a> · '
                     f'<a href="{aid}/crop.png" target="_blank">查看未缩放裁剪图</a></section>')
    page = '''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>报告取景 · 保持纸张原形</title><style>
body{margin:0;background:#f3f1ed;color:#293b34;font:16px/1.65 system-ui,sans-serif}main{max-width:1350px;margin:auto;padding:30px}
h1{font-size:30px}h2{font-size:21px}.intro,p{color:#64736b}section{background:white;border:1px solid #dce3dc;border-radius:16px;padding:24px;margin:24px 0}
.pair{display:grid;grid-template-columns:1fr 1fr;gap:24px}figure{margin:0;min-width:0}figcaption{font-weight:600;margin-bottom:12px}
figure img{display:block;max-width:100%;width:100%;height:660px;object-fit:contain;background:#e8ebe6;border:1px solid #d3dbd2}
a{color:#386447}button{font:inherit;padding:8px 18px;margin:5px;border:1px solid #bbc9ba;border-radius:20px;background:white;cursor:pointer}
button.active{background:#365b46;color:white}section[data-status="needs_review"]{border:2px solid #c98b3a}nav{position:sticky;top:0;background:#f3f1edf2;padding:10px 0;z-index:1}
[hidden]{display:none!important}@media(max-width:700px){main{padding:12px}section{padding:12px}.pair{gap:10px}figure img{height:420px}}
</style><main><h1>报告照片 · 原图内的矩形取景</h1>
<p class="intro">比例约束直接作用于原图上的矩形取景框，框可以移动和调整大小。右图就是框内的原始像素，包含少量背景也照原样保留。
绿色框已包住正文，蓝色框优先核心数据并允许裁去次要部分；橙色框表示核心区域仍超出原图内的取景框，只作待审核候选。
覆盖率针对模型定位框，不代表逐字核验。
不做多边形、不抠图、不补白、不展平。默认输出原始分辨率，点击可看高清图。以下未重新判定训练前后。</p>
<nav><button class="active" data-filter="all">全部</button><button data-filter="paper_photo">纸张照片</button><button data-filter="screenshot">电子截图</button><button data-filter="priority">核心内容优先</button><button data-filter="review">核心超框 / 待审核</button></nav>
'''
    page += ''.join(cards) + '''</main><script>
document.querySelectorAll('button').forEach(b=>b.onclick=()=>{document.querySelectorAll('button').forEach(x=>x.classList.toggle('active',x===b));
document.querySelectorAll('section').forEach(s=>s.hidden=b.dataset.filter==='review'?s.dataset.status!=='needs_review':b.dataset.filter==='priority'?s.dataset.priority!=='true':b.dataset.filter!=='all'&&s.dataset.kind!==b.dataset.filter)});
</script></html>'''
    (out/'index.html').write_text(page)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('audit', 'input-root', 'out'):
        p.add_argument('--'+name, type=Path, required=True)
    p.add_argument('--selections', type=Path, help='Reuse source-bound localization; optional settings allow core-priority model calls')
    p.add_argument('--settings', type=Path)
    p.add_argument('--cache', type=Path)
    p.add_argument('--ratio', type=parse_ratio, default=(3, 4))
    p.add_argument('--max-side', type=int, help='Optional export pixel cap; default preserves source crop pixels')
    p.add_argument('--workers', type=int, default=3)
    p.add_argument('--ids', nargs='*')
    args = p.parse_args()
    if args.out.exists():
        raise ValueError('output_must_be_new')
    if not 1 <= args.workers <= 4 or (args.max_side is not None and args.max_side < 100):
        raise ValueError('invalid_cap_or_workers')
    selected = sources(args.audit, args.input_root, set(args.ids or []))
    if args.selections:
        prior = reused_selections(args.selections, selected)
        client = MeasuredClient(args.settings, args.cache, 'qwen') if args.settings and args.cache else None
    else:
        if not args.settings or not args.cache:
            p.error('use --selections or both --settings and --cache')
        prior = None
        client = MeasuredClient(args.settings, args.cache, 'qwen')
    args.out.mkdir(parents=True)
    rows = []
    def work(item):
        row, source = item
        aid = row['asset_id']
        result = {k: row[k] for k in ('asset_id', 'store', 'member', 'source_sha256')}
        result['kind'] = row['qwen']['kind']
        dest = args.out/aid
        dest.mkdir()
        try:
            with Image.open(source) as raw:
                original = ImageOps.exif_transpose(raw).convert('RGB')
            if prior is not None:
                record = prior[aid]
                if record.get('source_size') != list(original.size):
                    raise ValueError('selection_source_size_mismatch')
                selection = record['selection']
                result['model_trace'] = {'reused': True, 'request_count': 0}
            else:
                selection, trace = client.ask([cv2.cvtColor(np.asarray(original), cv2.COLOR_RGB2BGR)], PROMPT, LOCALIZATION_VERSION)
                result['model_trace'] = {k: trace.get(k) for k in ('cached', 'request_count', 'key', 'requested_model')}
            # Historical polygons are not consumed by the renderer or carried forward.
            selection = {k: selection.get(k) for k in ('is_report', 'medium', 'content_box', 'paper_box', 'confidence', 'reason', 'issues')}
            result['selection'] = selection
            output, crop, geometry = make_frame(original, selection, args.ratio, args.max_side)
            if not geometry['content_fully_contained']:
                priority = prior[aid].get('priority') if prior is not None else None
                if priority:
                    result['priority_trace'] = {'reused': True, 'request_count': 0}
                elif client is not None:
                    try:
                        priority, trace = client.ask([cv2.cvtColor(np.asarray(original), cv2.COLOR_RGB2BGR)], PRIORITY_PROMPT, PRIORITY_VERSION)
                        result['priority_trace'] = {k: trace.get(k) for k in ('cached', 'request_count', 'key', 'requested_model')}
                    except ValueError as error:
                        result['priority_error'] = str(error)
                        result['priority_trace'] = getattr(error, 'trace', {})
                if priority:
                    result['priority'] = priority
                    output, crop, geometry = make_frame(original, selection, args.ratio, args.max_side, priority)
            original.save(dest/'original.png')
            thumb = original.copy()
            thumb.thumbnail((900, 1600), Image.Resampling.LANCZOS)
            thumb.save(dest/'original-preview.jpg', quality=91)
            sx, sy = thumb.width/original.width, thumb.height/original.height
            rect = geometry['crop_xyxy']
            ImageDraw.Draw(thumb).rectangle((rect[0]*sx, rect[1]*sy,
                                            min(thumb.width-2, rect[2]*sx-1), min(thumb.height-2, rect[3]*sy-1)),
                                           outline=('#3e8050' if geometry['content_fully_contained'] else
                                                    '#3681bd' if geometry['priority_fully_contained'] else '#db8c20'), width=4)
            thumb.save(dest/'framing-preview.jpg', quality=93)
            crop.save(dest/'crop.png')
            output.save(dest/'frame.png')
            preview = output.copy()
            preview.thumbnail((1200, 1600), Image.Resampling.LANCZOS)
            preview.save(dest/'frame-preview.jpg', quality=94)
            result.update(status='cropped' if geometry['priority_fully_contained'] else 'needs_review',
                          geometry=geometry, source_size=list(original.size),
                          frame_sha256=sha(dest/'frame.png'))
            if sha(source) != row['source_sha256']:
                raise ValueError('source_changed_during_run')
        except (ValueError, OSError, TypeError, KeyError) as error:
            result.update(status='needs_review', error=str(error))
        (dest/'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n')
        print(aid, result['status'], result.get('geometry', {}).get('medium'), result.get('error', ''), flush=True)
        return result
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for f in as_completed([pool.submit(work, item) for item in selected]):
            rows.append(f.result())
    rows.sort(key=lambda r: (r['store'], r['member'], r['asset_id']))
    manifest = {'version': VERSION, 'ratio': list(args.ratio), 'max_side': args.max_side,
                'localization_version': 'inherited_from_bundle' if args.selections else LOCALIZATION_VERSION,
                'priority_version': PRIORITY_VERSION,
                'selection_bundle_sha256': sha(args.selections) if args.selections else None,
                'selection_mode': 'reuse_bound_boxes' if args.selections else 'visual_model',
                'audit_sha256': sha(args.audit), 'prompt_sha256': None if args.selections else hashlib.sha256(PROMPT.encode()).hexdigest(),
                'dewarping_calls': 0, 'phase_classification_calls': 0, 'rows': rows}
    (args.out/'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+'\n')
    gallery(args.out, rows, args.ratio)
    print(json.dumps({'selected': len(rows), 'complete_crops': sum(r['status']=='cropped' for r in rows),
                      'needs_review': sum(r['status']=='needs_review' for r in rows)}), flush=True)


if __name__ == '__main__':
    main()

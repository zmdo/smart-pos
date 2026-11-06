"""Export verified report records as a standalone HTML table; no model calls."""
import argparse
import hashlib
import html
import json
import math
import re
import unicodedata
from datetime import date
from pathlib import Path


METRICS = [('height', '身高'), ('weight', '体重'), ('fat', '体脂率'),
           ('bmi', 'BMI'), ('waist', '腰围'), ('hip', '臀围'),
           ('chest', '胸围'), ('arm', '臂围'), ('muscle', '骨骼肌量')]


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def esc(value):
    return html.escape(str(value), quote=True)


def values(numbers, signed=False):
    return ' / '.join((('+' if n > 0 else '') if signed else '') + f'{n:g}' for n in numbers)


def metric_row(report, key, title):
    metric = report.get('metrics', {}).get(key)
    if not metric:
        reason = report.get('rejected_metrics', {}).get(key)
        status = '原文核验未通过' if reason else '报告未记录'
        return f'<tr class="missing"><th scope="row">{title}</th><td>—</td><td>—</td><td>—</td><td>—</td><td>—</td><td>{status}</td></tr>'
    before, after = metric['before_values'], metric['after_values']
    if not before or len(before) != len(after) or any(not math.isfinite(n) for n in before+after):
        raise ValueError('invalid_metric_values')
    delta = [round(b-a, 4) for a, b in zip(before, after)]
    if len(delta) != len(metric['computed_delta']) or any(abs(a-b) > 1e-8 for a,b in zip(delta,metric['computed_delta'])):
        raise ValueError('stored_delta_disagrees_with_values')
    warnings = report.get('warnings', [])
    notes = []
    if f'{key}: stated_delta_disagrees_with_cells' in warnings:
        notes.append('原填变化与两列数值不一致')
    if not metric['usable']:
        notes.append('原值保留，不用于阶段推断')
    if key == 'bmi' and any('bmi_disagrees_with_height_weight' in w for w in warnings):
        height, weight = report['metrics']['height'], report['metrics']['weight']
        calculated = [weight[phase][0]/(height[phase][0]/100)**2 for phase in ('before_values','after_values')]
        notes.append(f'按身高体重计算约 {calculated[0]:.2f} → {calculated[1]:.2f}')
    if len(before) > 1:
        notes.append('双项按原文顺序保留，未擅自标左右')
    warning = not metric['usable'] or any(w.startswith(key+':') for w in warnings)
    status = '；'.join(notes) if notes else '两列数值已核对'
    unit = '无量纲' if metric['unit'] == '无' else metric['unit']
    delta_unit = ' 个百分点' if key == 'fat' else ''
    return (f'<tr data-metric="{key}" class="{"warning" if warning else ""}">'
            f'<th scope="row">{title}</th><td>{esc(unit)}</td>'
            f'<td class="numeric">{values(before)}</td><td class="numeric">{values(after)}</td>'
            f'<td class="numeric delta">{values(delta, True)}{delta_unit}</td>'
            f'<td class="numeric original">{esc(metric["delta"])}</td><td>{esc(status)}</td></tr>')


def report_section(report, inventory, directory):
    rid = report['report_id']
    if not re.fullmatch(r'r\d+', rid):
        raise ValueError('invalid_report_id')
    audit_path = directory/rid/'audit.json'
    raw = read(audit_path).get('result', {}) if audit_path.exists() else {}
    stated = report.get('stated_days', raw.get('stated_days'))
    # Only display a transcribed duration as source data if it occurs with its unit.
    extracted = directory/rid/'extracted.txt'
    text = unicodedata.normalize('NFKC', extracted.read_text()) if extracted.exists() else ''
    duration_verified = type(stated) is int and ('stated_days' in report or bool(re.search(rf'(?<!\d){stated}\s*天', text)))
    try:
        elapsed = (date.fromisoformat(report['after_date'])-date.fromisoformat(report['before_date'])).days
    except (ValueError, KeyError, TypeError):
        elapsed = None
    notes = []
    if report.get('date_issue'):
        notes.append('报告日期未核验或与前后列冲突；不用于报告辅助判断。')
    if duration_verified and elapsed is not None and stated != elapsed:
        notes.append(f'报告填写 {stated} 天，按日期相减为 {elapsed} 天，请核对填写天数。')
    if 'bmi: stated_delta_disagrees_with_cells' in report.get('warnings', []):
        notes.append('BMI 原填变化量与前后值相减不一致，表内同时保留两种数值。')
    if not report['metrics'].get('bmi', {}).get('usable', True):
        notes.append('BMI 与身高、体重不一致，保留原报告值并标记不用于阶段推断。')
    source = next((r['relative_path'] for r in inventory if r.get('report_id') == rid), Path(report['source']).name)
    duration = f'{elapsed} 天' if elapsed is not None else '未核验'
    stated_text = f'{stated} 天' if duration_verified else '未核验'
    goals = '、'.join(report.get('checked_goals', [])) or '未确认勾选'
    source_rows = []
    for key, title in METRICS:
        metric = report.get('metrics', {}).get(key)
        if metric:
            location = ('表格 ' if Path(report['source']).suffix.lower() == '.docx' else '页 ') + str(metric['page'])
            source_rows.append('<tr>'+''.join(f'<td>{esc(v)}</td>' for v in (
                title, location, metric['before'], metric['after'], metric['delta'], metric['source_row']))+'</tr>')
    alerts = ''.join(f'<p class="alert">{esc(n)}</p>' for n in notes)
    return f'''<section class="report" id="{rid}" data-member="{esc(report['member'])}" data-store="{esc(report['store'])}">
<div class="section-heading"><h2>{esc(report['member'])}</h2><span>{esc(report['store'])}</span></div>
<div class="meta"><div><small>训练前日期</small><strong>{esc(report.get('before_date') or '未记录')}</strong></div><div><small>训练后日期</small><strong>{esc(report.get('after_date') or '未记录')}</strong></div><div><small>日期间隔 / 原填天数</small><strong>{duration} / {stated_text}</strong></div><div><small>报告勾选目标</small><strong>{esc(goals)}</strong></div></div>
{alerts}<div class="table-scroll"><table class="standard"><thead><tr><th>指标</th><th>单位</th><th>训练前</th><th>训练后</th><th>变化量（后 − 前）</th><th>原填变化</th><th>核验说明</th></tr></thead><tbody>{''.join(metric_row(report,k,title) for k,title in METRICS)}</tbody></table></div>
<details><summary>原文与来源</summary><p class="source">来源：{esc(source)}</p><p>前列：{esc(report['columns']['before'])}；后列：{esc(report['columns']['after'])}。按明确列标题对应，不按数值好坏排序。</p><div class="table-scroll"><table><thead><tr><th>指标</th><th>位置</th><th>前列原文</th><th>后列原文</th><th>变化原文</th><th>原始行</th></tr></thead><tbody>{''.join(source_rows)}</tbody></table></div></details></section>'''


def export(directory, output):
    directory = Path(directory).resolve(); output = Path(output)
    if output.exists():
        raise ValueError('output_must_not_exist')
    reports = [r for r in read(directory/'reports.json') if r.get('status') == 'verified_transcription']
    inventory = read(directory/'inventory.json')
    ids = [r['report_id'] for r in reports]
    if len(ids) != len(set(ids)) or any(not r['store'].endswith('店') for r in reports):
        raise ValueError('invalid_report_partition')
    sections = ''.join(report_section(r,inventory,directory) for r in reports)
    unmatched = [r for r in inventory if r['status'] != 'excluded' and r.get('report_id') not in ids]
    unmatched_html = ''.join(f'<tr><td>{esc(r["relative_path"])}</td><td>'+(
        '尚未提取：当前无唯一对应的合格照片组；不代表文件中没有数据。'
        if r.get('reason') == 'no_unique_eligible_photo_group' else '报告尚未通过原文核验，未填充指标。')+'</td></tr>' for r in unmatched)
    metric_count = sum(len(r.get('metrics', {})) for r in reports)
    options = ''.join(f'<option value="{esc(r["report_id"])}">{esc(r["store"])} / {esc(r["member"])}</option>' for r in reports)
    page = '''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>会员训练报告标准表</title><style>
:root{color-scheme:light;--ink:#23382e;--muted:#69766d;--green:#365b46;--line:#dce3db;--paper:#f5f5ef}*{box-sizing:border-box}body{margin:0;background:var(--paper);color:var(--ink);font:15px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC",sans-serif}main{max-width:1280px;margin:0 auto;padding:38px 30px 60px}header{padding-bottom:22px;border-bottom:1px solid #b7c6b8}h1{font-size:30px;margin:0 0 10px;letter-spacing:.03em}header p{margin:7px 0;color:var(--muted);max-width:1050px}.toolbar{display:flex;gap:14px;align-items:center;flex-wrap:wrap;margin:22px 0}select,button{font:inherit;border-radius:7px;padding:9px 14px;border:1px solid #b5c5b7;background:white;color:var(--ink)}button{cursor:pointer;margin-left:auto}button:hover{background:#e6ede3}#visible-count{color:var(--muted)}section.report{background:white;border:1px solid var(--line);border-radius:12px;padding:25px;margin:22px 0}.section-heading{display:flex;align-items:center;gap:15px;margin-bottom:16px}h2{font-size:23px;margin:0}.section-heading span{color:var(--muted)}.meta{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;padding:16px 18px;background:#f2f5ef;border-radius:8px;margin-bottom:16px}.meta small{display:block;color:var(--muted);font-size:12px;margin-bottom:3px}.meta strong{font-weight:550}.alert{font-size:13px;color:#7c5317;background:#fff4dc;border-left:3px solid #cfaa5d;padding:9px 13px;margin:8px 0}.table-scroll{overflow-x:auto;margin:15px 0 8px}table{width:100%;border-collapse:collapse;font-size:14px}th,td{padding:11px 12px;border-bottom:1px solid #e7ebe5;text-align:left;vertical-align:middle}thead th{background:var(--green);color:white;font-size:13px;font-weight:550;white-space:nowrap}tbody th{font-weight:550;white-space:nowrap}.numeric{font-variant-numeric:tabular-nums;text-align:right;white-space:nowrap}.delta{font-weight:600}.original{color:#72786f}.standard th:nth-child(1){width:95px}.standard th:nth-child(2){width:75px}.standard th:nth-child(7){width:350px}tr.warning{background:#fff9eb}.warning td:last-child{color:#8c5e18}.missing{color:#929a91;background:#fafbf8}details{border-top:1px solid var(--line);margin-top:15px;padding-top:13px;font-size:13px}summary{cursor:pointer;color:var(--green);font-weight:550}.source{overflow-wrap:anywhere}details td{font-size:12px}details table{min-width:850px}aside{padding:20px 0;font-size:13px;color:var(--muted)}aside h2{font-size:18px}aside table{background:white;font-size:13px}footer{font-size:12px;color:var(--muted);padding-top:16px;border-top:1px solid var(--line)}[hidden]{display:none!important}@media(max-width:700px){main{padding:23px 14px}h1{font-size:25px}section.report{padding:16px}.meta{grid-template-columns:1fr 1fr}.standard{min-width:920px}button{margin-left:0}}@media print{body{background:white}main{padding:0;max-width:none}.toolbar{display:none}section.report{break-inside:avoid;border-radius:0;margin:15px 0;padding:15px}thead{display:table-header-group}.table-scroll{overflow:visible}details:not([open]){display:none}th,td{padding:7px}*{-webkit-print-color-adjust:exact;print-color-adjust:exact}h1{font-size:24px}}
</style></head><body><main>'''
    page += f'''<header><h1>会员训练报告标准表</h1><p>{len(reports)} 份报告 · {metric_count} 项已提取指标 · {len(unmatched)} 份门店报告尚未匹配</p><p>变化量统一为训练后减训练前；体脂变化使用“百分点”。原填值保留，不覆盖核验异常。双项臂围按原文顺序保留；缺失数据不填零。</p><p>日期为报告记录，不表示照片拍摄日期。</p></header><div class="toolbar"><label for="member">查看会员</label><select id="member"><option value="all">全部会员</option>{options}</select><span id="visible-count">显示 {len(reports)} 份报告</span><button id="print" type="button">打印 / 保存为 PDF</button></div>{sections}'''
    if unmatched:
        page += f'<aside id="unmatched"><h2>尚未匹配的门店报告</h2><table><thead><tr><th>来源文件</th><th>说明</th></tr></thead><tbody>{unmatched_html}</tbody></table></aside>'
    page += '<footer>参考模板和说明文件未纳入此表。本页仅整理既有提取结果，不重新判断照片阶段。</footer><script>const select=document.getElementById("member");select.addEventListener("change",()=>{let count=0;document.querySelectorAll("section.report").forEach(section=>{section.hidden=select.value!=="all"&&section.id!==select.value;if(!section.hidden)count++;});document.getElementById("visible-count").textContent="显示 "+count+" 份报告";});document.getElementById("print").addEventListener("click",()=>window.print());</script></main></body></html>'
    output.parent.mkdir(parents=True, exist_ok=True); output.write_text(page, encoding='utf-8')
    return {'reports':len(reports),'metrics':metric_count,'unmatched_store_reports':len(unmatched),
            'report_input_sha256':hashlib.sha256((directory/'reports.json').read_bytes()).hexdigest(),
            'html_sha256':hashlib.sha256(output.read_bytes()).hexdigest(),'output':str(output)}


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reports',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    print(json.dumps(export(args.reports,args.out),ensure_ascii=False,indent=2))

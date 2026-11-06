"""Offline review cards with full context, region evidence and report provenance."""
import html
import json
from pathlib import Path

PHASE = {'before':'训练前','after':'训练后','unknown':'待复核',None:'待复核'}
CUE = {'waist_shape':'腰腹收紧','posture':'体态偏差','upper_muscle':'肩背肌肉','leg_shape':'腿部纤细','lower_muscle':'腿部肌肉'}


def esc(value):
    return html.escape(str(value))


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def decision_text(value):
    if value['after'] is None:
        return '待复核'
    return '推断 '+value['after']+' 为训练后 / '+('清楚' if value['strength']=='clear' else '轻微，需多朝向支持')


def preview(out):
    out = Path(out); groups = read(out/'groups.json'); counts = read(out/'counts.json')
    reports = {r['report_id']:r for r in read(out/'reports/reports.json')}
    variants = {name:{r['asset_id']:r for r in read(out/file)} for name,file in
                (('baseline','baseline-summary.json'),('regional','regional-summary.json'),('fused','summary.json'))}
    nav = ''.join(f'<a href="#{g["group_id"]}">{esc(g["store"])} / {esc(g["member"])}</a>' for g in groups)
    metrics = ''.join(f'<tr><td>{label}</td><td>{sum(n for p,n in counts[key]["phases"].items() if p != "unknown")}</td>'
                      f'<td>{counts[key]["phases"].get("unknown",0)}</td><td>{counts[key]["evidence_kinds"].get("inferred",0)}</td></tr>'
                      for key,label in (('baseline','原整体观察（相同输入）'),('regional','局部可比性 + 换序'),('fused','局部 + 报告辅助')))
    sections = []
    for g in groups:
        rows = []; report_html = []
        for rid in g['report_ids']:
            r = reports[rid]
            table = ''.join(f'<tr><td>{esc(v["row_label"])}</td><td>{esc(v["before"])}</td><td>{esc(v["after"])}</td>'
                            f'<td>{esc(v["computed_delta"])}</td></tr>' for v in r.get('metrics',{}).values())
            warnings = '；'.join(r.get('warnings',[])) or '未发现已检查的算术异常'
            page_links = ''.join(f'<a href="reports/{rid}/{p.name}">报告第 {p.stem.split("-")[-1]} 页</a> '
                                 for p in sorted((out/'reports'/rid).glob('page-*.png')))
            report_html.append(f'<div class="report"><h3>报告 {rid} · {esc(r.get("before_date"))} → {esc(r.get("after_date"))}</h3>'
                f'<p>已勾选目标：{esc("、".join(r.get("checked_goals",[])) or "未确认")}。报告与照片批次尚无可靠日期绑定。</p>'
                f'<table><tr><th>项目</th><th>报告训练前</th><th>报告训练后</th><th>重算差值</th></tr>{table}</table>'
                f'<p class="warn">{esc(warnings)}</p><p>{page_links}<a href="reports/{rid}/report.json">转录与校验</a></p></div>')
        for aid in g['asset_ids']:
            row = variants['fused'][aid]
            labels = ' → '.join(PHASE[variants[v][aid]['phase']] for v in ('baseline','regional','fused'))
            source = {'source_rule':'原始位置/文字规则','explicit_text':'两次读取一致的文字','inferred':'外观推断，未证实拍摄日期','needs_review':'证据不足或冲突'}[row['evidence_kind']]
            rows.append(f'<article class="photo"><a href="images/{aid}/source.jpg"><img loading="lazy" src="images/{aid}/uniform.jpg"></a>'
                f'<b>{aid} · {esc(row["view"])}</b><span>{labels}</span><small>{source}</small>'
                f'<small>{esc(row.get("reason"))}</small></article>')
        pairs = []
        for p in g['comparisons']:
            pid = p['pair_id']; primary = p['regional_audit'].get('primary',{}).get('result',{}).get('observations',{})
            reverse = p['regional_audit'].get('swapped',{}).get('result',{}).get('observations',{})
            evidence_rows = []
            for name,label in CUE.items():
                a,b = primary.get(name,{}),reverse.get(name,{})
                stable = p['regional_decision'].get('stable_cues',{}).get(name)
                state = f'{stable["image"]} / {stable["clarity"]}' if stable else '不采用'
                evidence_rows.append(f'<tr><td>{label}</td><td>{esc(state)}</td><td>{esc(a.get("reason","请求不可用"))}</td>'
                                     f'<td>{esc(b.get("reason","未完成"))}</td><td>{esc(a.get("confounds",[]))}</td></tr>')
            decisions = ''.join(f'<p><b>{label}：</b>{esc(decision_text(p[key+"_decision"]))} '
                                f'<small>{esc(p[key+"_decision"]["reason"])}</small></p>'
                                for key,label in (('baseline','原版'),('regional','局部版'),('fused','报告辅助')))
            frames = ''.join(f'<figure><a href="pairs/{pid}/{name}.jpg"><img loading="lazy" src="pairs/{pid}/{name}.jpg"></a><figcaption>{label}</figcaption></figure>'
                             for name,label in (('context','原图 A / B'),('reference','等比参考与取证区域'),('upper','肩背局部'),('waist','腰腹局部'),('legs','腿部局部')))
            pairs.append(f'<details><summary>{pid} · A={p["asset_ids"][0]} / B={p["asset_ids"][1]} · {esc(p["view_family"])} · '
                         f'{esc(decision_text(p["fused_decision"]))}</summary>{decisions}<p>正序与换序必须指向同一原图、同一观察项。局部图和原图只算一份证据。</p>'
                         f'<div class="frames">{frames}</div><div class="scroll"><table><tr><th>观察项</th><th>稳定结果</th><th>正序依据</th><th>换序依据</th><th>干扰</th></tr>'
                         f'{"".join(evidence_rows)}</table></div><p><a href="pairs/{pid}/evidence.json">完整审计 JSON</a></p></details>')
        sessions = '；'.join(', '.join(s['members'])+'：'+('可传播' if s['reliable'] else '不传播 / '+s['reliability_reason']) for s in g['session_candidates'])
        sections.append(f'<section id="{g["group_id"]}"><h2>{esc(g["store"])} / {esc(g["member"])}</h2>'
                        f'<p class="muted">标签顺序：原整体观察 → 局部观察 → 报告辅助。点击单图查看原图。</p><div class="photos">{"".join(rows)}</div>'
                        f'<p>批次判定：{esc(sessions or "固定规则已覆盖，无需推测批次")}</p>{"".join(report_html)}{"".join(pairs)}</section>')
    page = '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>局部证据与训练报告对照</title>'
    page += '''<style>body{margin:0;background:#f4f5ef;color:#24382e;font:15px/1.7 system-ui,sans-serif}main{max-width:1480px;margin:auto;padding:32px}h1{font-size:30px}h2{font-size:25px}h3{font-size:18px}a{color:#365f47}nav{display:flex;flex-wrap:wrap;gap:8px 20px;padding:20px;background:white;border-radius:12px}section{margin:32px 0;padding:24px;background:#fff;border-radius:14px;border:1px solid #dce3d7}.photos{display:flex;gap:12px;overflow:auto}.photo{width:180px;flex-shrink:0;display:flex;flex-direction:column;gap:6px}.photo img{width:100%;height:340px;object-fit:contain;background:#ecede7}.photo small{overflow-wrap:anywhere;color:#687767}table{border-collapse:collapse;width:100%}td,th{text-align:left;padding:9px 12px;border-bottom:1px solid #dce3d7;vertical-align:top}th{background:#edf1e7}small,.muted{color:#6a776b}.warn{color:#96612d}.report{background:#f6f8f2;padding:18px;margin:20px 0}details{border-top:1px solid #dce3d7;padding:18px 0}summary{cursor:pointer;font-weight:600}.frames{display:flex;overflow:auto;gap:14px}.frames figure{margin:0;min-width:320px;width:420px;flex-shrink:0}.frames img{width:100%;height:520px;object-fit:contain;background:#f6f7f3}.scroll{overflow:auto}.note{padding:16px;border-left:4px solid #688366;background:#eaf0e5}.stats{max-width:850px}@media(max-width:700px){main{padding:15px}section{padding:14px}.frames figure{width:320px}}</style>'''
    page += f'<main><h1>局部证据与训练报告对照</h1><p>本轮 {counts["total"]} 张 / {counts["groups"]} 个会员组 / {counts["comparisons"]} 对比较。'
    page += '保留原始人物姿态，不做轮廓强行重叠；展示版的非等比拉伸不参与判断。</p>'
    page += '<p class="note">采纳数量不是准确率。报告的前后列有明确来源，但报告日期尚未与照片批次绑定；外观推断依然可能出错。原版和两种新策略使用同一套原图与等比参考。</p>'
    page += f'<table class="stats"><tr><th>策略</th><th>已标注</th><th>待复核</th><th>其中外观推断</th></tr>{metrics}</table>'
    page += f'<p><a href="counts.json">统计</a> · <a href="verification.json">输入与规则校验</a> · <a href="controls.json">同图负对照</a> · <a href="reports/inventory.json">报告覆盖清单</a></p><nav>{nav}</nav>{"".join(sections)}</main></html>'
    (out/'index.html').write_text(page,encoding='utf-8')

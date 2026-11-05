"""Portable all-store coverage ledger, old/new photographs, and model comparison."""
import argparse
import html
from collections import Counter, defaultdict
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

from scripts.body_scan.pipeline import save_json
from scripts.body_scan_phase.inputs import digest
from .metrics import read, compare


LABELS={'before':'训练前','after':'训练后','unknown':'待复核'}
REASONS={
    'reference_folder_excluded':'参考模板／说明目录，整目录排除',
    'non_still_image':'视频或文档，不进入静态体测图流程',
    'not_body_scan':'非体测图，保留原素材',
    'poster_background_excluded':'主要背景为海报，标准化阶段排除',
    'feathered_composite_not_supported':'渐变拼接，按规则淘汰',
    'seam_detail_uncertain':'整图与接缝局部判断不一致，无法确认硬拼接',
    'vlm_subject_classification_conflict':'主体定位复核未能可靠确认单名主体',
    'camera_estimate_outside_experiment_limits':'相机估计超出当前校正范围',
    'shoulder_pose_not_reliable_across_contexts':'肩部关键点在不同上下文中不稳定',
}


def thumbnail(source, target, size=(440,700)):
    with Image.open(source) as im:
        ImageOps.contain(ImageOps.exif_transpose(im).convert('RGB'),size,Image.Resampling.LANCZOS).save(target,quality=91)


def coverage(root):
    local=read(root/'local-inventory.json')['files']
    remote=read(root/('final-inventory.json' if (root/'final-inventory.json').exists() else 'remote-inventory.json'))['files']
    if Counter(r['sha256'] for r in local)!=Counter(r['sha256'] for r in remote):
        raise ValueError('local_remote_inventory_mismatch')
    ledger=read(root/'intake-ledger.json');by_path={r['path']:r for r in ledger}
    display={r['asset_id']:r for r in read(root/'display/summary.json')}
    excluded={r['asset_id']:r for r in read(root/'display/upstream-excluded.json')}
    pair={r['asset_id']:r for r in read(root/'pairs/summary.json')}
    standardized={r['asset_id']:r for name in ('standardized-singles','standardized-pairs') for r in read(root/name/'summary.json')}
    def outcome(aid):
        if aid in display:
            row=display[aid];return {'asset_id':aid,'stage':'group_display','status':row['status'],'reason':row.get('reason')}
        row=standardized.get(aid) or excluded.get(aid)
        if row:return {'asset_id':aid,'stage':'standardization','status':row.get('status',row.get('upstream_status')),'reason':row.get('reason')}
        raise ValueError('processed_input_without_final_outcome_'+aid)
    files=[]
    for original in remote:
        entry={**original};intake=by_path.get(original['path'])
        # Files absent from the historical job (e.g. PSD) are still accounted for.
        parts=Path(original['path']).parts
        directory=parts[1] if parts and parts[0]=='私教会员案例项目' else parts[0]
        entry['in_scope']=directory.endswith('店')
        if not entry['in_scope']:
            entry.update(stage='intake',status='excluded',reason='reference_folder_excluded');files.append(entry);continue
        if intake is None:raise ValueError('store_file_missing_from_original_job_'+original['path'])
        entry.update(intake)
        if entry['status']=='selected_single':entry.update(outcome(entry['asset_id']))
        elif entry['status']=='selected_pair':
            parent=pair.get(entry['asset_id'])
            if parent is None:raise ValueError('comparison_parent_not_attempted')
            entry.update(stage='split',status=parent['status'],reason=parent.get('reason'))
            entry['children']=[outcome(c['asset_id']) if c['status']=='ready' else
                {'asset_id':c['asset_id'],'stage':'split_child_classification','status':c['status'],'reason':c.get('reason')}
                for c in parent['children']]
        files.append(entry)
    if any((r.get('store') or '').startswith('（') for r in display.values()):raise ValueError('reference_entered_display')
    result={'all_files':len(files),'matching_local_remote_files':len(files),
        'store_files':sum(r['in_scope'] for r in files),'excluded_reference_files':sum(not r['in_scope'] for r in files),
        'store_still_images':sum(r['in_scope'] and r['extension'] in ('.jpg','.jpeg','.png','.webp') for r in files),
        'store_non_images':sum(r['in_scope'] and r['extension'] not in ('.jpg','.jpeg','.png','.webp') for r in files),
        'original_file_statuses':dict(Counter(r['status'] for r in files if r['in_scope'])),
        'generated_child_images':sum(len(r.get('children',[])) for r in files),
        'displayed_images':sum(r['status']=='displayed' for r in display.values()),
        'display_review_images':sum(r['status']!='displayed' for r in display.values()),
        'standardization_statuses':dict(Counter(r['status'] for r in standardized.values())),
        'all_files_accounted_for':True,'no_reference_in_results':True}
    save_json(root/'coverage.json',files);save_json(root/'coverage-counts.json',result)
    return files,result


def build(root, baseline, old_display):
    root=Path(root);baseline=Path(baseline);old_display=Path(old_display)
    files,counts=coverage(root);metrics=compare(root,baseline);save_json(root/'model-comparison.json',metrics)
    dest=root/'previews';dest.mkdir(exist_ok=True)
    sources=root/'source-previews';sources.mkdir(exist_ok=True)
    classifications=read(root/'classification-comparison.json')
    for row in classifications:thumbnail(row['source'],sources/(row['asset_id']+'.jpg'))
    rows=read(root/'display/summary.json');groups=read(root/'display/groups.json')
    old={r['asset_id']:r for r in read(old_display/'summary.json') if r['status']=='displayed'}
    phases={p:{r['asset_id']:r for r in read(root/('phase-'+p)/'summary.json')} for p in ('deepseek','qwen')}
    group_rows=defaultdict(list)
    for row in rows:
        if row['status']=='displayed':group_rows[(row['store'],row['member'])].append(row)
    input_groups=defaultdict(list)
    for row in files:
        if row['in_scope']:input_groups[(row['store'],row['member'])].append(row)
    font_path='/root/autodl-fs/case-studio/fonts/NotoSansSC.ttf'
    font=ImageFont.truetype(font_path,19);small=ImageFont.truetype(font_path,15)
    esc=lambda x:html.escape(str(x))
    sections=[];group_summary=[]
    for index,(key,raw_files) in enumerate(sorted(input_groups.items()),1):
        gid=f'g{index:03d}';members=sorted(group_rows.get(key,[]),key=lambda r:r['asset_id'])
        old_ids=[aid for aid,r in old.items() if (r['store'],r['member'])==key]
        info={'group_id':gid,'store':key[0],'member':key[1],'input_files':len(raw_files),
            'input_images':sum(r['extension'] in ('.jpg','.jpeg','.png','.webp') for r in raw_files),
            'old_images':len(old_ids),'new_images':len(members),'new_asset_ids':[r['asset_id'] for r in members],
            'before_after':{p:dict(Counter(phases[p][r['asset_id']]['phase'] for r in members)) for p in phases}}
        group_summary.append(info)
        sections.append('<section data-name="'+esc('/'.join(key))+'"><h2>'+esc('/'.join(key))+'</h2><p>旧子集 '+str(len(old_ids))+' 张 → 全量 '+str(len(members))+' 张</p>')
        for start in range(0,len(members),6):
            page=members[start:start+6];width=max(720,245*len(page))
            sheet=Image.new('RGB',(width,1080),'#f3f0e7');draw=ImageDraw.Draw(sheet)
            draw.text((12,10),'/'.join(key)+' · 旧子集 / 全量门店数据',font=font,fill='#233d31')
            for i,row in enumerate(page):
                aid=row['asset_id'];x=i*245
                for kind,top,label in [('old',75,'旧子集'),('new',535,'本次全量')]:
                    draw.text((x+8,top-28),label+' · '+aid,font=small,fill='#3e5c4a')
                    path=(old_display/'images'/aid/'display.png') if kind=='old' else root/'display/images'/aid/'display.png'
                    if kind=='old' and aid not in old:
                        draw.text((x+25,top+165),'旧版未纳入',font=font,fill='#906f42');continue
                    with Image.open(path) as im:
                        thumb=ImageOps.contain(im.convert('RGB'),(225,390),Image.Resampling.LANCZOS)
                        sheet.paste(thumb,(x+(245-thumb.width)//2,top+(390-thumb.height)//2))
                draw.text((x+8,955),'DeepSeek：'+LABELS[phases['deepseek'][aid]['phase']],font=small,fill='#233d31')
                draw.text((x+8,985),'Qwen：'+LABELS[phases['qwen'][aid]['phase']],font=small,fill='#233d31')
                draw.text((x+8,1022),'AI 标签 ≠ 已核实拍摄时间',font=small,fill='#906f42')
            image_name=f'{gid}-{start//6+1}.jpg';sheet.save(dest/image_name,quality=92)
            sections.append('<a href="previews/'+image_name+'"><img class="sheet" loading="lazy" src="previews/'+image_name+'"></a>')
        issues=[]
        for r in raw_files:
            if r['stage'] in ('classification','intake'):continue
            if r['status'] not in ('displayed','split_ready'):
                issues.append((r.get('asset_id',''),r.get('reason') or r['status']))
            for child in r.get('children',[]):
                if child['status']!='displayed':issues.append((child['asset_id'],child.get('reason') or child['status']))
        if issues:sections.append('<ul>'+''.join('<li>'+esc(a+'：'+REASONS.get(reason,reason))+'</li>' for a,reason in issues)+'</ul>')
        sections.append('</section>')
    save_json(root/'group-comparison.json',group_summary)
    table=[]
    for p in ('deepseek','qwen'):
        model=metrics['providers'][p];phase=model['phase'];obs=model['fixed_observations'];timing=model['timing_tokens_cost']['cls-v3-wall-full-eval']
        rule=phase['phase_sources'].get('comparison_position_rule',0);accepted=phase['total']-phase['phases'].get('unknown',0)
        table.append('<tr>'+''.join('<td>'+esc(v)+'</td>' for v in [p,accepted,rule,accepted-rule,phase['phases'].get('unknown',0),
            str(obs['stable_direction_after_swap'])+'/'+str(obs['primary_directional_pairs']),
            str(obs['controls_without_invented_direction_both_orders'])+'/'+str(obs['controls']),
            str(timing['latency_p50_seconds'])+' / '+str(timing['latency_p95_seconds'])+' s'])+'</tr>')
    coverage_rows=[]
    for r in files:
        if not r['in_scope']:continue
        aid=r.get('asset_id','');name=esc(r['path'].removeprefix('私教会员案例项目/'))
        if (sources/(aid+'.jpg')).exists():name='<a href="source-previews/'+aid+'.jpg">'+name+'</a>'
        outcome=r['status']+('：'+REASONS.get(r.get('reason'),r.get('reason','')) if r.get('reason') else '')
        if r.get('children'):outcome+='；'+', '.join(c['asset_id']+' '+c['status'] for c in r['children'])
        coverage_rows.append('<tr><td>'+esc(aid)+'</td><td>'+name+'</td><td>'+esc(outcome)+'</td></tr>')
    page='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>全量门店数据 · DeepSeek / Qwen 对比</title><style>
body{max-width:1540px;margin:36px auto;padding:0 22px;background:#f3f0e7;color:#233d31;font:16px/1.7 system-ui,sans-serif}
h1{font-size:32px}h2{font-size:24px}.cards{display:flex;gap:18px;flex-wrap:wrap}.card{padding:16px 24px;background:#fffdf7;border-radius:14px}.card b{font-size:28px}
table{border-collapse:collapse;width:100%;font-size:14px}th,td{padding:10px;border-bottom:1px solid #cbd3c9;text-align:left}section{border-top:1px solid #cbd3c9;margin-top:35px;padding:16px 0}.sheet{max-width:100%;display:block;margin:16px 0}a{color:#426950}input{padding:12px;width:300px;border:1px solid #a9b8a5;border-radius:7px;background:#fffdf7}summary{cursor:pointer;padding:12px}pre{white-space:pre-wrap}nav{display:flex;gap:22px;flex-wrap:wrap}.note{color:#86663d}
</style><h1>全量门店数据与视觉模型对比</h1>'''
    page+='<p>只处理景田店、石厦店、宝安店。参考模板与说明目录共 '+str(counts['excluded_reference_files'])+' 个文件整目录排除，包括模板内原始素材。</p>'
    page+='<div class="cards">'+''.join('<div class="card"><b>'+str(n)+'</b><br>'+label+'</div>' for n,label in [
        (counts['store_files'],'门店文件已核对'),(counts['store_still_images'],'图片全部完成分类'),(counts['displayed_images'],'成品图片'),(len(input_groups),'会员组全量追踪')])+'</div>'
    page+='<p>旧子集 '+str(len(old))+' 张；新增和被拦截的图片均有去向记录。视频／文档 '+str(counts['store_non_images'])+' 个保留，不进入静态体测图流程。</p>'
    page+='<nav><a href="display/index.html">全部取景效果及下载</a><a href="phase-deepseek/index.html">DeepSeek 判断证据</a><a href="phase-qwen/index.html">Qwen 判断证据</a><a href="model-comparison.json">完整量化指标</a><a href="coverage.json">逐文件覆盖清单</a></nav>'
    cm=metrics['classification']
    page+='<h2>相同图片、相同提示词、相同规则</h2><p>门店图片体测／非体测二分类一致 '+str(cm['body_binary_agreement_real_sources'])+'/'+str(cm['real_source_images'])+'。几何校正与取景固定，两模型使用相同原图和等比参考判断前后。展示拉伸版不用于判断。</p>'
    page+='<table><tr><th>模型</th><th>采用标签</th><th>其中左右规则</th><th>其他文字／AI依据</th><th>待复核</th><th>初次有方向且换序保持</th><th>重复图控制通过</th><th>分类 P50 / P95</th></tr>'+''.join(table)+'</table>'
    page+='<h3>固定配对与接口成本</h3><table><tr><th>模型</th><th>外观答复结构有效</th><th>39 对中保留稳定方向</th><th>评测输入 / 输出 token</th><th>门店评测公开价估算</th></tr>'
    for provider in ('deepseek','qwen'):
        m=metrics['providers'][provider];o=m['fixed_observations'];t=m['timing_tokens_cost']['all'];cost=t['cost_estimate']
        price=('¥'+format(cost['amount'],'.2f')) if cost['currency']=='CNY' else ('$'+format(cost['offpeak'],'.4f')+'–$'+format(cost['peak'],'.4f'))
        values=[provider,str(o['validated_response_stages'])+'/'+str(o['response_stages']),str(o['pair_policy_retained_directions'])+'/'+str(o['fixed_pairs']),
                str(t['input_tokens'])+' / '+str(t['output_tokens']),price]
        page+='<tr>'+''.join('<td>'+esc(v)+'</td>' for v in values)+'</tr>'
    page+='</table><p>本批现有提示词下，基础分类与海报过滤没有体现更换模型的收益；DeepSeek 更快。复杂外观比较优先试用 Qwen，同时保留来源规则、去重、换序复核和冲突拦截。未直接修改生产模型设置。</p>'
    page+='<p class="note">反例：Qwen 对卢家俊同一背面照片重复输入时，声称 B 的腰侧略收紧（自报 0.85），实际输入像素相同；程序拦截了该方向。DeepSeek 的部分答复则存在 confidence / reason 嵌套层级错误或无法解析的 JSON；这与视觉没有明显变化是不同原因。</p>'
    page+='<p><a href="observations-deepseek/summary.json">DeepSeek 固定配对原始记录</a> · <a href="observations-qwen/summary.json">Qwen 固定配对原始记录</a></p>'
    page+='<p class="note">采用标签数与换序一致性不是准确率。未取得独立拍摄时间真值；AI 视觉推断单独标记。费用和失败统计见完整指标，Qwen 按人民币、DeepSeek 按美元记录。</p>'
    page+='<h2>各组新旧效果与标签</h2><input id="search" placeholder="筛选门店或会员姓名" aria-label="筛选门店或会员姓名">'+''.join(sections)
    page+='<details><summary>查看全部 '+str(counts['store_files'])+' 个门店文件去向</summary><table><tr><th>ID</th><th>文件（点击看原图）</th><th>处理结果</th></tr>'+''.join(coverage_rows)+'</table></details>'
    page+='<script>document.getElementById("search").addEventListener("input",e=>{const q=e.target.value.trim();document.querySelectorAll("section[data-name]").forEach(s=>s.hidden=!s.dataset.name.includes(q))})</script></html>'
    (root/'index.html').write_text(page,encoding='utf-8')
    print(counts)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for arg in ('root','baseline','old-display'):parser.add_argument('--'+arg,type=Path,required=True)
    a=parser.parse_args();build(a.root,a.baseline,a.old_display)

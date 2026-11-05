"""Measured comparison; acceptance and consistency are not chronology accuracy."""
import json
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def measured_calls(root, provider):
    paths=[]
    for directory in ('classification-'+provider,'background-'+provider,'background-children-'+provider):
        paths.extend((root/directory/'calls/history').glob('*.json'))
    paths.extend((root/('phase-calls-'+provider)/'history').glob('*.json'))
    with ThreadPoolExecutor(max_workers=16) as pool:
        traces=list(pool.map(read,paths))
    by_stage={}
    versions=sorted({t['version'] for t in traces})
    for stage in [*versions,'all']:
        selected=traces if stage=='all' else [t for t in traces if t['version']==stage]
        attempts=[a for t in selected for a in t['attempts']]
        latency=[t['elapsed_seconds'] for t in selected]
        input_tokens=output_tokens=cached=0
        for a in attempts:
            usage=a.get('usage',{})
            input_tokens+=usage.get('prompt_tokens',0);output_tokens+=usage.get('completion_tokens',0)
            cached+=usage.get('prompt_cache_hit_tokens',usage.get('prompt_tokens_details',{}).get('cached_tokens',0))
        uncached=max(0,input_tokens-cached)
        by_stage[stage]={'logical_calls':len(selected),'http_attempts':len(attempts),
            'timing_scope':'Sum of HTTP attempt wall times; excludes image encoding, cache replay and retry backoff.',
            'retries':sum(max(0,t['request_count']-1) for t in selected),
            'failed_logical_calls':sum(not t['success'] for t in selected),
            'failed_attempts':sum('error' in a for a in attempts),
            'latency_p50_seconds':round(float(np.percentile(latency,50)),3) if latency else None,
            'latency_p95_seconds':round(float(np.percentile(latency,95)),3) if latency else None,
            'latency_mean_seconds':round(float(np.mean(latency)),3) if latency else None,
            'input_tokens':input_tokens,'output_tokens':output_tokens,'cached_input_tokens':cached,
            'returned_models':dict(Counter(a.get('returned_model') for a in attempts)),
            'cost_estimate':({'currency':'CNY','amount':round((uncached*12+cached*1.5+output_tokens*36)/1e6,6)}
                if provider=='qwen' else {'currency':'USD','offpeak':round((uncached*.15+cached*.003+output_tokens*.6)/1e6,6),
                    'peak':round((uncached*.3+cached*.006+output_tokens*1.2)/1e6,6)})}
    return by_stage


def fixed_observations(rows):
    controls=[r for r in rows if r['kind']=='identical_photo_control']
    pairs=[r for r in rows if r['kind']=='same_view_candidate']
    directional=stable=opposed=lost=unusable=invalid=swap_unavailable=primary_unavailable=0
    both_directions=0
    for row in pairs:
        a=row['primary_direction'];b=row['swapped_direction']
        if a is None or b is None:invalid+=1
        if a is None:primary_unavailable+=1;continue
        if b is None:
            if a.get('after'):directional+=1;swap_unavailable+=1
            else:unusable+=1
            continue
        after=a.get('after');swapped={'A':'B','B':'A'}.get(b.get('after'))
        if after:
            directional+=1
            if swapped:
                both_directions+=1
                if swapped==after:stable+=1
                else:opposed+=1
            else:lost+=1
        else:unusable+=1
    stages=[r[k] for r in pairs for k in ('primary','swapped')]
    return {'fixed_pairs':len(pairs),'all_pairs_asked_in_both_orders':True,'invalid_response_pairs':invalid,
        'validated_response_stages':sum('error' not in s for s in stages),'response_stages':len(stages),
        'response_errors':dict(Counter(s['error'] for s in stages if 'error' in s)),
        'primary_directional_pairs':directional,'stable_direction_after_swap':stable,
        'opposite_direction_after_swap':opposed,'direction_lost_after_swap':lost,'no_primary_direction':unusable,
        'primary_response_unavailable_pairs':primary_unavailable,'directional_primary_but_swap_unavailable':swap_unavailable,
        'pair_policy_retained_directions':sum(r['decision']['after'] is not None for r in pairs),
        'policy_reasons':dict(Counter(r['decision']['reason'] for r in pairs if not r['decision']['after'])),
        'direction_stability_fraction':round(stable/directional,4) if directional else None,
        'controls':len(controls),
        'controls_without_invented_direction_both_orders':sum(
            all(r[k] is not None and r[k].get('after') is None for k in ('primary_direction','swapped_direction')) for r in controls),
        'scope':'Repeated-order consistency and identical-image controls; no historical chronology gold labels.'}


def compare(root, baseline):
    root=Path(root);baseline=Path(baseline)
    classes=read(root/'classification-comparison.json')
    actual=[r for r in classes if not r['reference_material']]
    result={'classification':{'all_images':len(classes),'real_source_images':len(actual),
        'kind_agreement_all':sum(r['kind_agreement'] for r in classes),
        'body_binary_agreement_real_sources':sum((r['deepseek'].get('kind')=='body_scan')==(r['qwen'].get('kind')=='body_scan') for r in actual),
        'body_inputs_by_provider':{p:sum(r[p].get('kind')=='body_scan' for r in actual) for p in ('deepseek','qwen')},
        'kind_disagreements':[{k:r[k] for k in ('asset_id','member','deepseek','qwen')} for r in classes if not r['kind_agreement']],
        'anatomical_side_label_disagreements':sum(r['deepseek'].get('view')!=r['qwen'].get('view') and
            str(r['deepseek'].get('view')).startswith('side') and str(r['qwen'].get('view')).startswith('side') for r in actual)},
        'providers':{}}
    singles=set(read(root/'single-ids.json'))
    for p in ('deepseek','qwen'):
        backgrounds={r['asset_id']:r['background'] for r in read(root/('background-'+p)/'summary.json')}
        single_bg={aid:backgrounds[aid] for aid in singles}
        children=read(root/('background-children-'+p)/'summary.json') if (root/('background-children-'+p)/'summary.json').exists() else []
        result['providers'][p]={'timing_tokens_cost':measured_calls(root,p),
            'single_background':{'total':len(single_bg),'classes':dict(Counter(r['primary_background'] for r in single_bg.values())),
                'poster_ids':sorted(aid for aid,r in single_bg.items() if r['primary_background']=='poster_wall')},
            'child_background':{'total':len(children),'classes':dict(Counter(r['background']['primary_background'] for r in children)),
                'poster_ids':sorted(r['asset_id'] for r in children if r['background']['primary_background']=='poster_wall')},
            'fixed_observations':fixed_observations(read(root/('observations-'+p)/'summary.json')),
            'phase':read(root/('phase-'+p)/'counts.json')}
    phases={p:{r['asset_id']:r for r in read(root/('phase-'+p)/'summary.json')} for p in ('deepseek','qwen')}
    if set(phases['deepseek'])!=set(phases['qwen']):raise ValueError('phase_provider_input_sets_differ')
    for aid in phases['deepseek']:
        for key in ('source_sha256','uniform_sha256'):
            if phases['deepseek'][aid][key]!=phases['qwen'][aid][key]:raise ValueError('phase_provider_pixels_differ')
    result['phase_comparison']={'same_input_ids_and_pixels':True,'images':len(phases['deepseek']),
        'phase_agreement':sum(r['phase']==phases['qwen'][aid]['phase'] for aid,r in phases['deepseek'].items()),
        'differences':[{'asset_id':aid,'member':r['member'],'deepseek':r['phase'],'qwen':phases['qwen'][aid]['phase'],
            'deepseek_source':r['phase_source'],'qwen_source':phases['qwen'][aid]['phase_source']}
            for aid,r in phases['deepseek'].items() if r['phase']!=phases['qwen'][aid]['phase']]}
    old={r['asset_id']:r for r in read(baseline/'summary.json')};new=phases['deepseek'];common=set(old)&set(new)
    result['old_subset_comparison']={'old_images':len(old),'new_images':len(new),'common_images':len(common),
        'added_ids':sorted(set(new)-set(old)),'removed_ids':sorted(set(old)-set(new)),
        'common_phase_changes':[{'asset_id':aid,'old':old[aid]['phase'],'new':new[aid]['phase']} for aid in sorted(common) if old[aid]['phase']!=new[aid]['phase']],
        'common_source_hashes_match':all(old[aid]['source_sha256']==new[aid]['source_sha256'] for aid in common),
        'common_uniform_unchanged_ids':sorted(aid for aid in common if old[aid]['uniform_sha256']==new[aid]['uniform_sha256']),
        'old_counts':read(baseline/'counts.json')}
    result['limits']=['未取得独立的真实拍摄时间或人工前后标签，不能把采用数量和自报置信度称为准确率。',
        '几何校正、取景和标签决策规则固定；两模型独立比较分类、背景、照片外观和拍摄批次，不是两套不同裁剪结果的对比。',
        '费用按公开标准价和接口 usage 估算，未包含账户折扣或失败请求未返回的计费用量；人民币和美元不做未经核实的汇率换算。',
        '费用仅统计门店范围的双模型评测调用；共同几何管线、此前范围收窄前的参考目录调用及连通性探测不计入模型差额统计。',
        '原样重复照片控制仅证明该小样本未虚构变化，不代表全部场景的准确率。']
    return result

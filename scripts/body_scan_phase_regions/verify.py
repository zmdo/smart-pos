"""Independent artifact/provenance audit; no model calls and no phase guesses."""
import argparse
import json
from html.parser import HTMLParser
from pathlib import Path

from scripts.body_scan.pipeline import save_json
from scripts.body_scan_phase.inputs import digest
from .evidence import CUES, usable, validate


class Links(HTMLParser):
    def __init__(self):
        super().__init__(); self.links=[]

    def handle_starttag(self,tag,attrs):
        for key,value in attrs:
            if key in ('src','href') and value and not value.startswith(('#','http')):
                self.links.append(value)


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def verify(directory):
    root=Path(directory);manifest=read(root/'sources.json'); groups=read(root/'groups.json')
    counts=read(root/'counts.json'); config=read(root/'config.json')
    if any(digest(p)!=sha for p,sha in manifest.items()):
        raise ValueError('source_changed')
    variants=[read(root/p) for p in ('baseline-summary.json','regional-summary.json','summary.json')]
    ids=[{r['asset_id'] for r in rows} for rows in variants]
    if any(len(rows)!=counts['total'] or len(idset)!=len(rows) or idset!=ids[0] for rows,idset in zip(variants,ids)):
        raise ValueError('strategy_coverage_mismatch')
    for rows in variants:
        if any(not r['store'].endswith('店') or r['verified_chronology'] is not False for r in rows):
            raise ValueError('scope_or_chronology_claim_invalid')
    original={r['asset_id']:r for r in read(Path(config['baseline'])/'summary.json')}
    fixed=[]
    for row in variants[-1]:
        if row['evidence_kind']=='source_rule':
            if any(next(r for r in rows if r['asset_id']==row['asset_id'])['phase']!=original[row['asset_id']]['phase'] for rows in variants):
                raise ValueError('fixed_label_changed')
            fixed.append(row['asset_id'])
    stable_count=0;pair_count=0
    for group in groups:
        for strategy in group['strategies'].values():
            members=[aid for unit in strategy['units'] for aid in unit['members']]
            if sorted(members)!=sorted(group['asset_ids']):
                raise ValueError('unit_partition_changed')
            for unit in strategy['units']:
                if len(unit['members'])>1 and (unit['membership']!='reviewed_session' or not unit['session_evidence']['reliable']):
                    raise ValueError('unreliable_group_propagation')
        for pair in group['comparisons']:
            pair_count+=1
            stable=pair['regional_decision'].get('stable_cues',{})
            if stable:
                one=validate(pair['regional_audit']['primary']['result'])
                two=validate(pair['regional_audit']['swapped']['result'])
                for name,value in stable.items():
                    a,b=one['observations'][name],two['observations'][name]
                    if not usable(a) or not usable(b) or a['image']!={'A':'B','B':'A'}[b['image']]:
                        raise ValueError('invalid_stable_observation')
                    if value['image']!=a['image'] or not all(m['regions'][CUES[name][0]]['available'] for m in pair['crop_metadata']):
                        raise ValueError('invalid_region_evidence')
                    stable_count+=1
            fused=pair['fused_decision'];regional=pair['regional_decision']
            if fused['report_assistance']['status']=='compatible_inference':
                if not stable or fused['strength']=='clear' and not any(v['clarity']=='clear' for v in stable.values()):
                    raise ValueError('report_manufactured_evidence')
                if fused['report_assistance']['photo_batch_link']!='unverified':
                    raise ValueError('unproven_report_photo_link')
            for region in ('upper','waist','legs'):
                rects=[m['regions'][region].get('rectangle_uniform_xyxy') for m in pair['crop_metadata']]
                if all(rects) and (rects[0][2]-rects[0][0],rects[0][3]-rects[0][1])!=(rects[1][2]-rects[1][0],rects[1][3]-rects[1][1]):
                    raise ValueError('paired_windows_differ_in_size')
    controls=read(root/'controls.json')
    if any(c['decision']['after'] is not None for c in controls):
        raise ValueError('identical_image_assigned_phase')
    for control in controls:
        if 'negative_control' not in control['audit']:
            raise ValueError('negative_control_execution_incomplete')
        for stage in ('primary','swapped'):
            if 'error' in control['audit'].get(stage,{}) or 'result' not in control['audit'].get(stage,{}):
                raise ValueError('negative_control_model_failure')
            validate(control['audit'][stage]['result'])
    links=Links();links.feed((root/'index.html').read_text())
    if any(not (root/p).is_file() for p in links.links):
        raise ValueError('preview_has_missing_local_link')
    result={'passed':True,'rows':counts['total'],'groups':len(groups),'comparisons':pair_count,
            'stable_cues_checked':stable_count,'fixed_source_labels_preserved':len(fixed),
            'input_files_unchanged':len(manifest),'preview_links_checked':len(links.links),
            'negative_controls_blocked':len(controls),'verified_photo_chronology':False,
            'scope':'artifact, provenance and policy audit; not human-verified phase accuracy'}
    save_json(root/'independent-verification.json',result)
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--out',type=Path,required=True)
    print(verify(parser.parse_args().out))

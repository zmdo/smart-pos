"""Create an immutable derived input job from a source-bound visual intake audit."""
import argparse
import copy
import json
from pathlib import Path

from scripts.body_scan.pipeline import save_json, eligibility
from scripts.body_scan_phase.inputs import digest
from .sweep import is_reference


def prepare(root, audit):
    root=Path(root).resolve(); audit=Path(audit).resolve()
    config=json.loads((root/'classification-deepseek/config.json').read_text())
    job_path=Path(config['job']); job=json.loads(job_path.read_text())
    comparison=json.loads((root/'classification-comparison.json').read_text())
    reviews=json.loads(audit.read_text())
    decisions={r['asset_id']:r for r in reviews['items']}
    if len(decisions)!=len(reviews['items']):raise ValueError('duplicate_intake_decision')
    lookup={r['asset_id']:r for r in comparison}
    candidates={r['asset_id'] for r in comparison if r['body_candidate'] and not r['reference_material']}
    if not candidates.issubset(decisions):raise ValueError('candidate_without_visual_intake_decision')
    out=root/'dataset';out.mkdir(exist_ok=False);(out/'input').symlink_to(job_path.parent/'input',target_is_directory=True)
    singles=[];pairs=[];ledger=[];assets=[]
    for asset in job['assets']:
        aid=asset['id'];row=lookup.get(aid)
        entry={'asset_id':aid,'path':asset['path'],'store':asset.get('store'),'member':asset.get('member')}
        if is_reference(asset):
            entry.update(stage='intake',status='excluded',reason='reference_folder_excluded');ledger.append(entry);continue
        if row is None:
            if Path(asset['path']).suffix.lower() in ('.jpg','.jpeg','.png','.webp'):
                raise ValueError('store_image_missing_from_classification_'+aid)
            entry.update(stage='intake',status='excluded',reason='non_still_image');ledger.append(entry);continue
        entry['source_sha256']=row['source_sha256']
        if digest(job_path.parent/'input'/asset['path'])!=row['source_sha256']:raise ValueError('intake_source_changed')
        review=decisions.get(aid)
        if not review:
            if any(row[p].get('kind')=='body_scan' for p in ('deepseek','qwen','old')):raise ValueError('unreviewed_body_candidate')
            entry.update(stage='classification',status='excluded',reason='not_body_scan',classification=row['deepseek'])
            ledger.append(entry);continue
        if review['source_sha256']!=row['source_sha256']:raise ValueError('intake_review_source_mismatch')
        if not review.get('reason'):raise ValueError('intake_review_missing_reason')
        if review['action'] not in ('single','pair','exclude','review'):raise ValueError('invalid_intake_action')
        entry['intake_review']=review
        if review['action'] in ('exclude','review'):
            entry.update(stage='classification',status='excluded' if review['action']=='exclude' else 'needs_review',reason=review['reason'])
            ledger.append(entry);continue
        selected=copy.deepcopy(row[review.get('provider','deepseek')])
        selected.update(review.get('overrides',{}))
        if selected.get('kind')!='body_scan':raise ValueError('selected_non_body_class')
        updated=copy.deepcopy(asset);updated['class']=selected
        updated['classification_evidence']={'source':'source_verified_full_intake_audit','source_sha256':row['source_sha256'],
            'audit_sha256':digest(audit),'prompt_version':'cls-v3-wall','reason':review['reason']}
        if review['action']=='single':
            reason=eligibility(selected)
            if reason:raise ValueError('invalid_single_intake_'+aid+'_'+reason)
            singles.append(aid)
        else:
            selected['is_comparison']=True;selected['phase']='both';pairs.append(aid)
        assets.append(updated);entry.update(stage='intake',status='selected_'+review['action'],classification=selected);ledger.append(entry)
    save_json(out/'job.json',{'version':'full-model-eval-derived-v1','parent_job':str(job_path),
        'parent_job_sha256':digest(job_path),'intake_audit':str(audit),'assets':assets})
    save_json(root/'intake-ledger.json',ledger);save_json(root/'single-ids.json',singles);save_json(root/'pair-ids.json',pairs)
    print(json.dumps({'singles':len(singles),'comparison_parents':len(pairs),'ledger_assets':len(ledger)}))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--audit',type=Path,required=True);args=parser.parse_args();prepare(args.root,args.audit)

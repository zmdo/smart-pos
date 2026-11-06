"""Immutable delivery revisions and optimistic, idempotent human correction."""
import copy
import fcntl
import hashlib
import json
import re
import shutil
import tempfile
import uuid
import zipfile
from collections import Counter,defaultdict
from datetime import datetime,timezone
from pathlib import Path

from PIL import Image

from . import VERSION
from scripts.body_scan_contracts.labels import decorate
from scripts.body_scan_contracts.bundles import load_labels, load_reports
from .render import plan,render,sha


def read(path):return json.loads(Path(path).read_text(encoding='utf-8'))


def save(path,value):
    path=Path(path);tmp=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    tmp.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');tmp.replace(path)


def digest_json(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()


def stamp():return datetime.now(timezone.utc).isoformat()


def bind(path,manifest,expected=None):
    path=Path(path).resolve();actual=sha(path)
    if expected is not None and actual!=expected:raise ValueError('source_hash_changed')
    if str(path) in manifest and manifest[str(path)]!=actual:raise ValueError('source_changed_during_load')
    manifest[str(path)]=actual;return path


def publish(directory,rows,source,revision,previous=None,changes=None,request_id=None):
    root=Path(directory);number=f'r{revision:04d}';dest=root/'revisions'/number
    staging=Path(tempfile.mkdtemp(prefix='.building-',dir=root/'revisions'))
    try:
        assets={r['asset_id']:r for r in rows};photos=source['photos']
        for path,expected in source['bindings'].items():
            if sha(path)!=expected:raise ValueError('bound_source_changed_before_generation')
        plans,gaps,selections=plan(rows)
        outputs=render(plans,rows,photos,staging,source['font'],previous)
        (staging/'photos').mkdir()
        for aid in assets:
            with Image.open(photos[aid]) as image:
                image=image.convert('RGB');image.thumbnail((360,650));image.save(staging/'photos'/(aid+'.jpg'),quality=90)
        for row in rows:
            row['affected_output_ids']=[o['product_id'] for o in outputs if row['asset_id'] in o['asset_ids']]
            row['thumbnail']='photos/'+row['asset_id']+'.jpg'
        needs=[{k:r.get(k) for k in ('asset_id','store','member','view','phase','label','label_kind','confidence','confidence_semantics',
                                    'assignment_reason','analysis_reason','review_flags','candidates','affected_output_ids','thumbnail')}
               for r in rows if r['requires_review']]
        manifest_hash=digest_json(source['bindings'])
        result={'schema_version':VERSION,'delivery_id':root.name,'revision':revision,'created_at':stamp(),
                'parent_revision':revision-1 if previous else None,'source_manifest_sha256':manifest_hash,
                'status':'generated_requires_review' if needs or any(o['requires_review'] for o in outputs) else 'generated',
                'counts':{'images':len(rows),'members':len({(r['store'],r['member']) for r in rows}),
                          'label_kinds':dict(Counter(r['label_kind'] for r in rows)),
                          'requires_review':len(needs),'products':len(outputs),'review_products':sum(o['requires_review'] for o in outputs),
                          'rendered_products':sum(not o['reused'] for o in outputs),'reused_products':sum(o['reused'] for o in outputs)},
                'items':rows,'outputs':outputs,'gaps':gaps,'slot_selections':selections,
                'review':{'required':bool(needs),'asset_ids':[r['asset_id'] for r in needs],
                          'output_ids':[o['product_id'] for o in outputs if o['requires_review']],
                          'file':'review.json','correction_template':'review-template.json',
                          'submit_url':f'/api/productions/{root.name}/review'},
                'download':'products.zip','preview':'index.html','request_id':request_id,'applied_changes':changes or [],
                'review_request_sha256':source.get('review_request_sha256'),
                'generation_scope':'body-photo singles, same-view VS, complete front/side/back grid',
                'verified_photo_chronology':False}
        if source.get('report_bundle'):
            reports=Path(source['report_bundle']);(staging/'reports').mkdir()
            for filename in ('index.html','reports.json','inventory.json'):
                shutil.copyfile(reports/filename,staging/'reports'/filename)
            result['report_comparison']={'preview':'reports/index.html','data':'reports/reports.json',
                'inventory':'reports/inventory.json','bundle_sha256':sha(reports/'bundle.json'),
                'review_report_ids':[r['report_id'] for r in read(reports/'reports.json')
                    if r['status']!='verified_transcription' or r.get('warnings') or r.get('rejected_metrics')]}
            result['generation_scope']+='; verified report comparison HTML and data'
        save(staging/'result.json',result)
        save(staging/'review.json',{'delivery_id':root.name,'base_revision':revision,'source_manifest_sha256':manifest_hash,
                                   'items':needs,'outputs_requiring_review':[o for o in outputs if o['requires_review']]})
        save(staging/'review-template.json',{'delivery_id':root.name,'base_revision':revision,'source_manifest_sha256':manifest_hash,
                                           'request_id':str(uuid.uuid4()),'changes':[]})
        from .preview import preview
        preview(result,staging)
        with zipfile.ZipFile(staging/'products.zip','w',zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(staging.rglob('*')):
                if path.is_file() and path.name!='products.zip':archive.write(path,path.relative_to(staging))
        if dest.exists():raise ValueError('revision_already_exists')
        staging.rename(dest)
        save(root/'current.json',{'revision':revision,'path':'revisions/'+number,'result_sha256':sha(dest/'result.json')})
        return result
    except Exception:
        if staging.exists():shutil.rmtree(staging)
        raise


def create(phase_dir,root,font,reports=None):
    if not re.fullmatch(r'[A-Za-z0-9_-]{8,80}',Path(root).name):raise ValueError('invalid_delivery_id')
    rows,photos,bindings,report_link=load_labels(phase_dir)
    if reports is None and report_link['path']:
        reports=Path(report_link['path'])
    if reports:
        reports=Path(reports).resolve()
        load_reports(reports,bindings)
        if sha(reports/'bundle.json')!=report_link['sha256']:
            raise ValueError('reports_differ_from_classification')
    elif report_link['sha256']:
        raise ValueError('classification_report_bundle_missing')
    root=Path(root);root.mkdir(parents=True,exist_ok=False);(root/'revisions').mkdir()
    font=str(bind(font,bindings))
    source={'phase_input':str(Path(phase_dir).resolve()),'photos':photos,'bindings':bindings,'font':font,'version':VERSION,
            'classification_schema':'body-scan-phase-labels-v1','report_bundle':str(reports) if reports else None}
    save(root/'private-inputs.json',source)
    return publish(root,rows,source,1)


class ReviewConflict(ValueError):pass


def current(root):
    root=Path(root);pointer=read(root/'current.json');directory=root/pointer['path']
    if sha(directory/'result.json')!=pointer['result_sha256']:raise ValueError('current_revision_changed')
    return read(directory/'result.json'),directory


def correct(root,request):
    root=Path(root)
    with (root/'review.lock').open('a+') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        if not isinstance(request,dict) or set(request)-{'delivery_id','base_revision','source_manifest_sha256','request_id','changes'}:
            raise ValueError('invalid_review_request')
        rid=request.get('request_id')
        if not isinstance(rid,str) or not re.fullmatch(r'[A-Za-z0-9_-]{8,80}',rid):raise ValueError('invalid_request_id')
        fingerprint=digest_json(request)
        # Check immutable committed revisions so a crash after commit cannot
        # create a duplicate revision on an idempotent retry.
        for path in (root/'revisions').glob('r*/result.json'):
            previous=read(path)
            if previous.get('request_id')==rid:
                if previous.get('review_request_sha256')!=fingerprint:raise ReviewConflict('request_id_reused_with_different_payload')
                active,_=current(root)
                if previous['revision']>active['revision']:
                    if previous['parent_revision']!=active['revision']:raise ReviewConflict('orphan_revision_chain')
                    save(root/'current.json',{'revision':previous['revision'],'path':str(path.parent.relative_to(root)),
                                              'result_sha256':sha(path)})
                return previous
        latest,directory=current(root)
        if request.get('delivery_id')!=root.name or request.get('source_manifest_sha256')!=latest['source_manifest_sha256']:
            raise ReviewConflict('review_source_mismatch')
        if type(request.get('base_revision')) is not int or request['base_revision']!=latest['revision']:
            raise ReviewConflict('stale_review_revision')
        changes=request.get('changes')
        if not isinstance(changes,list) or not changes or len(changes)>len(latest['items']):raise ValueError('empty_or_invalid_changes')
        rows=copy.deepcopy(latest['items']);lookup={r['asset_id']:r for r in rows};seen=set()
        for change in changes:
            if not isinstance(change,dict) or set(change)-{'asset_id','phase','confirm','note'}:raise ValueError('invalid_change_fields')
            aid=change.get('asset_id')
            if aid not in lookup or aid in seen or change.get('phase') not in ('before','after') or change.get('confirm') is not True:
                raise ValueError('invalid_or_unconfirmed_asset_change')
            if not isinstance(change.get('note',''),str) or len(change.get('note',''))>500:raise ValueError('invalid_review_note')
            seen.add(aid);row=lookup[aid]
            row.update(phase=change['phase'],label_kind='human',assignment_reason='explicit_user_review',
                       human_review={'request_id':rid,'at':stamp(),'previous_phase':row['phase'],
                                     'previous_model_confidence':row['confidence'],'note':change.get('note','')},
                       confidence=None,review_flags=[])
            decorate(row)
        source=read(root/'private-inputs.json')
        # Include request identity before publication; pointer must never expose
        # a revision missing its idempotency fingerprint.
        source={**source,'review_request_sha256':fingerprint}
        return publish(root,rows,source,latest['revision']+1,directory,changes,rid)

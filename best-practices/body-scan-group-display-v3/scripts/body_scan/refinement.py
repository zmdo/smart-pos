"""Opt-in second pass: verified wall structure and group scale, sampling originals."""
import argparse
import copy
import hashlib
import json
import shutil
from pathlib import Path

import cv2
import numpy as np

from .framing import UniformConfig,uniform_plan,compose_full_source,required_subject_rectangle,select_rectangle,rectangular_image
from .landmarks import landmarks,member_key
from .pipeline import save_json,group_records
from .preview import make_previews
from .reference import VisualEvidence,SELECT,SELECT_VERSION,SCALE,SCALE_VERSION
from .segmentation import SamSegmenter
from . import wall_geometry as wall
from . import group_scale
from .background_screening import BackgroundScreening, VERSION as BACKGROUND_SCREENING_VERSION, apply_screening


def compose(source,row,H,config,scale_plan=None):
    pose=landmarks(row['pose']['keypoints_source'],H,row['subject_box'],row['classification']['view'])
    framing_pose=copy.deepcopy(pose)
    if scale_plan is not None:
        scale=scale_plan['uniform_scale']
        framing_pose['torso_length']=config.height*config.torso_fraction/scale
        framing_pose['anchor'][1]=pose['hip_anchor'][1]-(scale_plan['target_hip_y']-(config.height*config.shoulder_y-.5))/scale
    plan=uniform_plan(framing_pose,config);A=np.asarray(plan['H_corrected_to_aligned'])
    full,available,coverage=compose_full_source(source,A@H,config)
    rect,metrics=select_rectangle(available,required_subject_rectangle(pose,A,config))
    image,used=rectangular_image(full,available,rect,config.background_rgb)
    frame={**plan,**coverage,**metrics,'H_source_to_aligned':(A@H).tolist(),
           'content_rectangle_xyxy':rect,'available_pixels':int(np.count_nonzero(available)),
           'used_pixels':int(np.count_nonzero(used)),'padding_fraction':float(np.mean(used==0)),
           'framing_anchor_corrected':framing_pose['anchor'],
           'framing_torso_length':framing_pose['torso_length'],'group_scale':scale_plan}
    return image,available,used,pose,frame


def save_render(out,row,result):
    image,available,used,pose,frame=result
    row.update({'pose':pose,'frame':frame})
    for name,value in [('aligned.png',image),('available_mask.png',available),('content_mask.png',used)]:
        if not cv2.imwrite(str(out/row['asset_id']/name),value):
            raise OSError('refinement_image_write_failed')


def group_sheet(members,out,replacement=None):
    thumbs=[]
    for c in sorted(members,key=lambda c:c['row']['asset_id']):
        aid=c['row']['asset_id']
        image=replacement[1] if replacement and replacement[0]==aid else cv2.imread(str(out/aid/'aligned.png'))
        thumb=cv2.resize(image,(240,560),interpolation=cv2.INTER_AREA)
        cv2.putText(thumb,aid,(5,22),cv2.FONT_HERSHEY_SIMPLEX,.55,(0,0,0),3)
        cv2.putText(thumb,aid,(5,22),cv2.FONT_HERSHEY_SIMPLEX,.55,(255,255,255),1)
        thumbs.append(thumb)
    return np.concatenate(thumbs,axis=1)


def apply_group_scale(out,target,plan,members,config,evidence):
    row=target['row'];aid=row['asset_id'];audit=row['refinement']
    audit['group_scale_proposal']=plan
    try:
        H=np.asarray(row['geometry']['H_source_to_corrected'])
        result=compose(target['source'],row,H,config,plan)
        cv2.imwrite(str(out/aid/'scale-candidate.png'),result[0])
        if result[4]['padding_fraction']>row['frame']['padding_fraction']+.04:
            audit['scale_status']='retained_padding_limit'
        else:
            answer,trace=evidence.ask([group_sheet(members,out),group_sheet(members,out,(aid,result[0]))],SCALE,SCALE_VERSION)
            audit['scale_review']={'result':answer,**trace}
            accepted=(answer.get('accept') is True and answer.get('scale_improved') is True
                      and answer.get('new_severe_crop') is False)
            if accepted:
                save_render(out,row,result)
                audit['scale_status']='registered_wall_scale'
            else:
                audit['scale_status']='retained_visual_review'
    except (ValueError,OSError) as error:
        audit['scale_status']='retained_scale_unavailable'
        audit['scale_error']=str(error)
    save_json(out/aid/'report.json',row)


def run(baseline,out,evidence=None,group_ids=None,enable_group_scale=True,background_screening=None):
    baseline,out=Path(baseline),Path(out)
    rows=json.loads((baseline/'summary.json').read_text(encoding='utf-8'))
    config_data=json.loads((baseline/'config.json').read_text(encoding='utf-8'))
    if config_data.get('version')!='body-scan-unified-v2-pinhole' or config_data.get('non_grid_transform')!='pinhole':
        raise ValueError('refinement_requires_approved_pinhole_baseline')
    groups=json.loads((baseline/'groups.json').read_text(encoding='utf-8'))
    selected={aid for g in groups if not group_ids or g['group_id'] in group_ids for aid in g['asset_ids']}
    if group_ids and set(group_ids)-{g['group_id'] for g in groups}:
        raise ValueError('unknown_refinement_groups')
    for row in rows:
        if row['status']=='rectangular':
            if hashlib.sha256(Path(row['source']).read_bytes()).hexdigest()!=row['source_sha256']:
                raise ValueError('refinement_source_changed: '+row['asset_id'])
    out.mkdir(parents=True,exist_ok=False)
    config=UniformConfig(**{k:config_data[k] for k in ('width','height','torso_fraction','shoulder_y','background_rgb')})
    save_json(out/'config.json',{**config_data,'version':'body-scan-wall-v3','baseline':str(baseline),
                              'background_screening_version':BACKGROUND_SCREENING_VERSION,
                              'baseline_summary_sha256':hashlib.sha256((baseline/'summary.json').read_bytes()).hexdigest()})
    evidence=evidence or VisualEvidence();segmenter=SamSegmenter();contexts=[]
    background_screening=background_screening or BackgroundScreening()
    for row in rows:
        aid=row['asset_id']
        if row['status']!='rectangular':
            if row.get('background_screening'):
                (out/aid).mkdir()
                save_json(out/aid/'report.json',row)
            continue
        # Recheck originals even for a legacy baseline or a non-selected refinement group.
        source=cv2.imread(row['source'])
        if not apply_screening(row,source,background_screening):
            (out/aid).mkdir()
            save_json(out/aid/'report.json',row)
            print(aid,row['status'],row['reason'],flush=True)
            continue
        shutil.copytree(baseline/aid,out/aid)
        save_json(out/aid/'report.json',row)
        if row['route']!='non_grid' or aid not in selected:
            continue
        audit={'status':'retained_pinhole'};row['refinement']=audit
        try:
            scene,trace=evidence.scene(source);audit.update({'scene':scene,'scene_trace':trace})
            if not wall.scene_valid(scene):
                raise ValueError('wall_semantics_not_reliable')
            person=segmenter(source,[row['subject_box']])[0]
            audit['person_mask_fallback']=segmenter.last_fallback
            context={'row':row,'source':source,'scene':scene,'person':person}
            context['features']=group_scale.features(source,scene,person)
            contexts.append(context)
            lines=wall.candidates(source,scene,person);audit['line_candidates']=lines
            if not lines:
                raise ValueError('no_measured_wall_lines')
            annotated=wall.annotate(source,lines)
            cv2.imwrite(str(out/aid/'line-candidates.jpg'),annotated)
            answer,selection_trace=evidence.ask([source,annotated],SELECT,SELECT_VERSION)
            audit.update({'selection':answer,'selection_trace':selection_trace})
            horizontal,vertical=wall.selected_lines(lines,answer)
            H,geometry=wall.refine(row['geometry']['calibration'],source.shape,row['subject_box'],horizontal,vertical)
            rendered=compose(source,row,H,config)
            # Do not accept geometry at the expense of a large new loss of photo area.
            if rendered[4]['padding_fraction']>row['frame']['padding_fraction']+.04:
                raise ValueError('wall_padding_regression')
            cv2.imwrite(str(out/aid/'wall-candidate.png'),rendered[0])
            accepted,review=evidence.review(cv2.imread(str(baseline/aid/'aligned.png')),rendered[0])
            audit.update({'candidate_geometry':geometry,'quality_review':review})
            if not accepted:
                raise ValueError('wall_visual_review_declined')
            row['geometry']={**row['geometry'],'method':'non-grid-wall-v3','action':'wall_pinhole',
                             'base_geometry':copy.deepcopy(row['geometry']),
                             'canvas_matrix':geometry['canvas_matrix'],'output_size':geometry['output_size'],
                             'H_source_to_corrected':H.tolist(),'wall_refinement':geometry}
            save_render(out,row,rendered);audit['status']='wall_refined'
        except (ValueError,OSError) as error:
            audit['reason']=str(error)
        save_json(out/aid/'report.json',row)
        print(aid,audit['status'],audit.get('reason',''),flush=True)
    if enable_group_scale:
        bygroup={}
        for c in contexts:bygroup.setdefault(member_key(c['row']),[]).append(c)
        for members in bygroup.values():
            for target,plan in group_scale.proposals(members):
                apply_group_scale(out,target,plan,members,config,evidence)
                row=target['row']
                print(row['asset_id'],row['refinement']['scale_status'],round(plan['scale_multiplier'],4),flush=True)
    save_json(out/'summary.json',rows);save_json(out/'groups.json',group_records(rows))
    from collections import Counter
    save_json(out/'counts.json',dict(Counter(r['status'] for r in rows)))
    make_previews(out,rows,group_records(rows),Path('/root/autodl-fs/case-studio/fonts/NotoSansSC.ttf'),baseline,
                  stage_label='墙面参照校正与同组尺度修正')
    return rows


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--group',nargs='+')
    parser.add_argument('--no-group-scale',action='store_true')
    args=parser.parse_args();cv2.setNumThreads(4)
    run(args.baseline,args.out,group_ids=args.group,enable_group_scale=not args.no_group_scale)

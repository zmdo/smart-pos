"""Verify accepted refinements, original integrity and unchanged baseline outputs."""
import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

import cv2
import numpy as np

from .geometry import project
from .pipeline import save_json
from .wall_geometry import residual


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify(out):
    out=Path(out)
    config=json.loads((out/'config.json').read_text(encoding='utf-8'))
    baseline=Path(config['baseline'])
    assert digest(baseline/'summary.json')==config['baseline_summary_sha256']
    old={r['asset_id']:r for r in json.loads((baseline/'summary.json').read_text(encoding='utf-8'))}
    rows=json.loads((out/'summary.json').read_text(encoding='utf-8'))
    assert set(old)=={r['asset_id'] for r in rows}
    changed=[];retained=[];grids=[];scales=[];angles={};new_requests=0
    for row in rows:
        aid=row['asset_id'];prior=old[aid]
        assert row['status']==prior['status'],aid
        audit=row.get('refinement',{})
        for key in ('scene_trace','selection_trace','quality_review','scale_review'):
            new_requests+=audit.get(key,{}).get('request_count',0)
        if row['status']!='rectangular':
            continue
        assert digest(Path(row['source']))==row['source_sha256']==prior['source_sha256'],aid
        assert digest(out/aid/'original.png')==digest(baseline/aid/'original.png'),aid
        image=cv2.imread(str(out/aid/'aligned.png'))
        mask=cv2.imread(str(out/aid/'content_mask.png'),0)
        available=cv2.imread(str(out/aid/'available_mask.png'),0)
        assert image.shape==(config['height'],config['width'],3),aid
        frame=row['frame'];x1,y1,x2,y2=frame['content_rectangle_xyxy']
        expected=np.zeros_like(mask);expected[y1:y2,x1:x2]=255
        np.testing.assert_array_equal(mask,expected)
        assert available[y1:y2,x1:x2].all(),aid
        assert (image[mask==0]==config['background_rgb'][::-1]).all(),aid
        assert (x2-x1)*(y2-y1)==frame['selected_rectangle_area'],aid
        H=np.asarray(row['geometry']['H_source_to_corrected']);A=np.asarray(frame['H_corrected_to_aligned'])
        np.testing.assert_allclose(A[:2,:2],np.eye(2)*frame['uniform_scale'])
        np.testing.assert_allclose(frame['H_source_to_aligned'],A@H)
        np.testing.assert_array_equal(row['pose']['keypoints_source'],prior['pose']['keypoints_source'])
        np.testing.assert_allclose(row['pose']['keypoints_corrected'],project(np.asarray(row['pose']['keypoints_source'])[:,:2],H))
        scale=frame.get('group_scale')
        if scale:
            assert audit['scale_status']=='registered_wall_scale'
            review=audit['scale_review']['result']
            assert review['accept'] is True and review['scale_improved'] is True and review['new_severe_crop'] is False
            assert len(scale['reference_votes'])>=2
            assert len({v['reference_id'] for v in scale['reference_votes']})>=2
            assert 1.08<scale['scale_multiplier']<1.22
            np.testing.assert_allclose(project([row['pose']['hip_anchor']],A)[0,1],scale['target_hip_y'],atol=1e-8)
            assert abs(frame['framing_torso_length']*frame['uniform_scale']/config['height']-config['torso_fraction'])<1e-10
            scales.append({'asset_id':aid,'scale_multiplier':scale['scale_multiplier'],
                           'reference_ids':[v['reference_id'] for v in scale['reference_votes']]})
        else:
            np.testing.assert_allclose(project([row['pose']['anchor']],A)[0],
                                       [config['width']/2-.5,config['height']*config['shoulder_y']-.5],atol=1e-8)
            assert abs(row['pose']['torso_length']*frame['uniform_scale']/config['height']-config['torso_fraction'])<1e-10
        if audit.get('status')=='wall_refined':
            geometry=row['geometry'];cal=geometry['calibration'];wall=geometry['wall_refinement']
            K=np.asarray(cal['K']);R=np.asarray(cal['R']);Y=np.asarray(wall['yaw_rotation']);M=np.asarray(wall['canvas_matrix'])
            np.testing.assert_allclose(H,M@K@Y@R.T@np.linalg.inv(K))
            review=audit['quality_review']['result']
            assert review['accept'] is True and review['background_improved'] is True
            assert review['new_body_distortion'] is False and review['new_severe_crop'] is False
            errors=np.abs(residual(wall['horizontal_lines'],H))
            assert max(errors)<=1,aid
            angles[aid]={'before_median_abs_deg':float(np.median(np.abs(wall['horizontal_before_deg']))),
                         'after_median_abs_deg':float(np.median(errors)),'after_max_abs_deg':float(max(errors))}
        if audit.get('status')=='wall_refined' or scale:
            changed.append(aid)
        else:
            for name in ('aligned.png','available_mask.png','content_mask.png'):
                assert digest(out/aid/name)==digest(baseline/aid/name),(aid,name)
            retained.append(aid)
            if row['route']=='grid':grids.append(aid)
    result={'output_directory':str(out),'baseline':str(baseline),
            'counts':dict(Counter(r['status'] for r in rows)),
            'changed_asset_ids':changed,'byte_identical_retained_asset_ids':retained,
            'byte_identical_grid_asset_ids':grids,'wall_line_angles':angles,'group_scale_adjustments':scales,
            'retained_reasons':dict(Counter(r.get('refinement',{}).get('reason') for r in rows if r.get('refinement',{}).get('status')=='retained_pinhole')),
            'new_vlm_requests_in_final_refinement_run':new_requests,
            'source_integrity':'raw source SHA and baseline originals verified',
            'geometry_checks':'camera yaw composition, unchanged source keypoints, isotropic framing, hip/shoulder anchor policies and valid rectangle verified'}
    save_json(out/'validation.json',result)
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args();print(json.dumps(verify(args.out),ensure_ascii=False,indent=2))

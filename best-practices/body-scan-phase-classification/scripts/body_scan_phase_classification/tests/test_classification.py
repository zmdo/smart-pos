import copy
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch
from scripts.body_scan_phase_classification.assignment import assign,required_ranking
from scripts.body_scan_phase_classification.ranking import parse,rank
from scripts.body_scan_phase_classification.pipeline import finalize
from scripts.body_scan_contracts.io import save,read,sha

class WorkflowSourceTests(unittest.TestCase):
    def test_explicit_job_binding_accepts_v4_lineage_and_rejects_changed_job(self):
        from scripts.body_scan_phase.inputs import load
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);job=root/'combined/job.json';source=job.parent/'input/a.png';source.parent.mkdir(parents=True);source.write_bytes(b'source')
            display=root/'display';uniform=display/'images/a/uniform.png';uniform.parent.mkdir(parents=True);uniform.write_bytes(b'uniform')
            standard=root/'standard';save(standard/'config.json',{'inputs':['approved-v4']})
            asset=dict(id='a',path='a.png',store='测试店',member='会员')
            save(job,{'assets':[asset]});save(display/'config.json',{'version':'body-scan-group-display-v2'})
            save(display/'summary.json',[dict(asset_id='a',store='测试店',member='会员',status='displayed',source=str(source),source_sha256=sha(source),input_directory=str(standard),output={'uniform_sha256':sha(uniform)},upstream_report={'classification':{'kind':'body_scan','view':'front'}})])
            manifest=root/'source-manifest.json';save(manifest,{'schema':'body-scan-source-jobs-v1','assets':{'a':{'job':str(job),'job_sha256':sha(job)}}})
            rows,_,bindings=load(display,manifest);self.assertEqual(len(rows),1);self.assertIn(str(manifest),bindings)
            save(job,{'assets':[dict(asset,member='被修改')]})
            with self.assertRaisesRegex(ValueError,'input_fingerprint_changed'):load(display,manifest)

    def test_relocated_pair_requires_exact_source_bytes_and_parent_crop(self):
        import cv2
        import numpy as np
        from scripts.body_scan_phase.inputs import split_assignment
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);image=np.zeros((20,30,3),np.uint8);image[:,15:]=220
            source=root/'parent.png';cv2.imwrite(str(source),image);children=[]
            for i,rect in enumerate(([0,0,15,20],[15,0,30,20]),1):
                path=root/f'child{i}.png';cv2.imwrite(str(path),image[:,(i-1)*15:i*15])
                children.append(dict(asset_id=f'a__p0{i}',panel_index=i,crop_parent_xyxy=rect,source=str(path),source_sha256=sha(path),status='ready'))
            report=root/'report.json';save(report,dict(asset_id='a',status='split_ready',store='测试店',member='会员',layout={'seam':{'kind':'hard'},'layout':'left_right','axis':0},children=children,
                attempts=[{'accepted':True,'review':{'result':{'accept':True,'independent_photos':True,'residual_other_photo':False,'residual_blend':False,'new_subject_cut':False}}}],source=str(source),source_sha256=sha(source),rectangles_parent_xyxy=[c['crop_parent_xyxy'] for c in children]))
            copied=root/'relocated.png';copied.write_bytes(Path(children[0]['source']).read_bytes())
            row=dict(asset_id='a__p01',store='测试店',member='会员',source=str(copied),source_sha256=sha(copied));asset={'pair_source':dict(parent_asset_id='a',panel_index=1,crop_parent_xyxy=[0,0,15,20])};override={'split_report':str(report),'split_report_sha256':sha(report)}
            phase,evidence=split_assignment(asset,root/'job.json',row,{},override)
            self.assertEqual(phase,'before');self.assertEqual(evidence['source'],'comparison_position_rule')
            cv2.imwrite(str(copied),np.ones((20,15,3),np.uint8))
            with self.assertRaisesRegex(ValueError,'input_fingerprint_changed'):split_assignment(asset,root/'job.json',row,{},override)

    def test_source_manifest_schema_is_required(self):
        from scripts.body_scan_phase.inputs import load
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);save(root/'config.json',{'version':'body-scan-group-display-v2'});save(root/'manifest.json',{'assets':{}})
            with self.assertRaisesRegex(ValueError,'invalid_source_job_manifest'):load(root,root/'manifest.json')

def row(aid,view='front',phase='unknown',kind='needs_review',suggestion=None):
    value={'asset_id':aid,'store':'测试店','member':'测试人','group_id':'g001','source_sha256':aid+'-sha',
           'view':view,'phase':phase,'evidence_kind':kind,'reason':'test','phase_source':'unresolved','confidence':None}
    if suggestion:value['suggestion']={'phase':suggestion}
    return value


def group(rows,reliable=False,pairs=None):
    units=[{'unit_id':'u'+str(i),'membership':'reviewed_session' if reliable else 'single_image','members':members}
           for i,members in enumerate(([r['asset_id'] for r in rows[::2]],[r['asset_id'] for r in rows[1::2]]) if reliable else [[r['asset_id']] for r in rows])]
    return {'asset_ids':[r['asset_id'] for r in rows],'comparisons':pairs or [],'strategies':{'fused':{'units':units}}}


def ranking(score):return {'after_score':score,'order_gap':0,'reason':'临时排序'}


class AssignmentTests(unittest.TestCase):
    def test_confirmed_human_label_overrides_rule_with_bound_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);analysis=root/'analysis';analysis.mkdir()
            save(analysis/'reports/reports.json',[])
            photo=root/'photo.png';photo.write_bytes(b'approved-image')
            original=row('a',phase='before',kind='source_rule');original['source_sha256']=sha(photo)
            g={**group([original]),'group_id':'g001','member':'测试人','store':'测试店'}
            correction=root/'correction.json'
            save(correction,[{'asset_id':'a','source_sha256':sha(photo),'phase':'after','confirm':True}])
            with patch('scripts.body_scan_phase_classification.pipeline.load_phase',return_value=(
                    [original],[g],{'a':str(photo)},{str(photo):sha(photo)})):
                finalize(analysis,root/'out',corrections=correction)
            result=read(root/'out/labels.json')[0]
            self.assertEqual(result['phase'],'after');self.assertEqual(result['label_kind'],'human')
            self.assertFalse(result['requires_review'])

    def test_tentative_inference_is_used_and_marked(self):
        rows=[row('a',suggestion='before'),row('b',suggestion='after')]
        result,_=assign(group(rows),rows)
        self.assertEqual([r['label'] for r in result],['训练前（推断）','训练后（推断）'])
        self.assertTrue(all(r['requires_review'] for r in result))

    def test_existing_ai_assignments_also_require_review(self):
        rows=[row('a',phase='before',kind='inferred')]
        result,_=assign(group(rows),rows)
        self.assertTrue(result[0]['requires_review']);self.assertEqual(result[0]['label_kind'],'inferred')

    def test_fixed_source_rule_preserved(self):
        rows=[row('a',phase='before',kind='source_rule'),row('b')]
        result,_=assign(group(rows),rows,{'a':ranking(.99),'b':ranking(.95)})
        self.assertEqual([r['phase'] for r in result],['before','after']);self.assertFalse(result[0]['requires_review'])

    def test_best_scoring_distinct_pair_selected(self):
        rows=[row('a'),row('b')]
        result,_=assign(group(rows),rows,{'a':ranking(.7),'b':ranking(.9)})
        self.assertEqual([r['phase'] for r in result],['before','after'])
        self.assertEqual(result[0]['label'],'训练前（待审）')
        self.assertIn('paired_or_session_constraint_overrode_individual_maximum',result[0]['review_flags'])

    def test_reliable_session_is_consistent_across_views(self):
        rows=[row('a'),row('b'),row('c','back'),row('d','back')]
        result,_=assign(group(rows,True),rows,{k:ranking(v) for k,v in [('a',.9),('b',.1),('c',.6),('d',.4)]})
        by_id={r['asset_id']:r for r in result}
        self.assertEqual(by_id['a']['phase'],by_id['c']['phase']);self.assertEqual(by_id['b']['phase'],by_id['d']['phase'])

    def test_zero_evidence_gets_explicit_placeholder_not_fake_confidence(self):
        rows=[row('a'),row('b')]
        result,audit=assign(group(rows),rows)
        self.assertEqual({r['phase'] for r in result},{'before','after'})
        self.assertTrue(all(r['confidence'] is None and r['label_kind']=='pending' for r in result))
        self.assertEqual(audit['equally_ranked_assignments'],2)




    def test_fallback_not_required_when_reliable_session_has_inference(self):
        rows=[row('a',phase='before',kind='inferred'),row('b',phase='after',kind='inferred'),row('c','back'),row('d','back')]
        self.assertEqual(required_ranking(group(rows,True),rows),[])

    def test_invalid_ranking_coverage_rejected(self):
        with self.assertRaises(ValueError):parse({'items':[{'image':'I1','after_score':.8,'reason':'x'}]},[row('a'),row('b')])

    def test_nan_or_boolean_ranking_rejected(self):
        for score in (True,float('nan'),2):
            with self.assertRaises(ValueError):parse({'items':[{'image':'I1','after_score':score,'reason':'x'}]},[row('a')])

    def test_unavailable_model_does_not_invent_confidence(self):
        values,_=rank(None,[row('a')],['a'])
        self.assertIsNone(values['a']['after_score'])

    def test_one_panel_per_source_prevents_original_reference_id_confusion(self):
        import numpy as np
        from unittest.mock import Mock
        client=Mock();client.ask.return_value=({'items':[{'image':'I1','after_score':.5,'reason':'待审'},
                                                         {'image':'I2','after_score':.5,'reason':'待审'}]}, {})
        with patch('scripts.body_scan_phase_classification.ranking.image_for',return_value=np.zeros((80,40,3),np.uint8)):
            result,audit=rank(client,[row('a'),row('b')],['a','b'])
        self.assertEqual(len(client.ask.call_args_list),2)
        self.assertTrue(all(len(call.args[0])==2 for call in client.ask.call_args_list))
        self.assertEqual(result['a']['after_score'],.5);self.assertNotIn('error',audit['primary'])



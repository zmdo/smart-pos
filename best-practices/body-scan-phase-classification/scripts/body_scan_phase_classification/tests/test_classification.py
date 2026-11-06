import copy
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch
from scripts.body_scan_phase_classification.assignment import assign,required_ranking
from scripts.body_scan_phase_classification.ranking import parse,rank
from scripts.body_scan_phase_classification.pipeline import finalize
from scripts.body_scan_contracts.io import save,read,sha

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



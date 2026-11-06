import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image
from fastapi import FastAPI
from fastapi.testclient import TestClient

from scripts.body_scan_phase_classification.assignment import assign,decorate,required_ranking
from scripts.body_scan_phase_classification.ranking import parse,rank
from scripts.body_scan_delivery.pipeline import publish,correct,current,read,save,sha,ReviewConflict
from scripts.body_scan_delivery.render import plan
from scripts.body_scan_delivery.api import router


FONT=Path('/root/autodl-fs/case-studio/fonts/NotoSansSC.ttf')


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

    def test_same_source_never_becomes_vs_pair(self):
        rows=[row('a',suggestion='before'),row('b',suggestion='after')];rows[1]['source_sha256']=rows[0]['source_sha256']
        labels,_=assign(group(rows),rows);products,_,_=plan(labels)
        self.assertTrue(all(p['kind']=='single' for p in products))

    def test_single_image_gets_a_label_without_fake_counterpart(self):
        rows=[row('a')];labels,_=assign(group(rows),rows,{'a':ranking(.8)})
        products,_,_=plan(labels)
        self.assertEqual(len(products),1);self.assertEqual(labels[0]['phase'],'after')

    def test_all_photos_preserved_when_multiple_share_slot(self):
        rows=[row('a',suggestion='before'),row('b',suggestion='before'),row('c',suggestion='after')]
        labels,_=assign(group(rows),rows);products,_,_=plan(labels)
        self.assertEqual(sum(p['kind']=='single' for p in products),3)

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


class RevisionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)/'delivery-test'
        (self.root/'revisions').mkdir(parents=True)
        photos={}
        rows=[row('a',phase='before',kind='inferred'),row('b',phase='after',kind='inferred'),row('c','back',phase='before',kind='source_rule')]
        labels,_=assign(group(rows),rows)
        for i,r in enumerate(rows):
            path=Path(self.temp.name)/(r['asset_id']+'.png');Image.new('RGB',(80,200),(i*60,90,70)).save(path);photos[r['asset_id']]=str(path)
        bindings={p:sha(p) for p in photos.values()};bindings[str(FONT)]=sha(FONT)
        self.source={'photos':photos,'font':str(FONT),'bindings':bindings};save(self.root/'private-inputs.json',self.source)
        self.first=publish(self.root,labels,self.source,1)
        self.request={'delivery_id':self.root.name,'base_revision':1,'source_manifest_sha256':self.first['source_manifest_sha256'],
                      'request_id':'review-test-0001','changes':[{'asset_id':'a','phase':'after','confirm':True}]}

    def tearDown(self):self.temp.cleanup()

    def test_correction_regenerates_only_changed_products_and_preserves_old(self):
        second=correct(self.root,self.request)
        self.assertEqual(second['revision'],2)
        a=next(r for r in second['items'] if r['asset_id']=='a')
        self.assertEqual(a['label'],'训练后');self.assertFalse(a['requires_review']);self.assertEqual(a['label_kind'],'human')
        self.assertEqual(second['counts']['reused_products'],2)
        self.assertEqual(read(self.root/'revisions/r0001/result.json')['items'][0]['phase'],'before')
        self.assertFalse(any(o['kind']=='vs' for o in second['outputs']))

    def test_same_phase_confirmation_clears_only_confirmed_badge(self):
        self.request['changes'][0]['phase']='before';second=correct(self.root,self.request)
        self.assertEqual(second['counts']['requires_review'],1)
        self.assertEqual(next(r for r in second['items'] if r['asset_id']=='b')['label'],'训练后（推断）')

    def test_retry_is_idempotent(self):
        a=correct(self.root,self.request);b=correct(self.root,self.request)
        self.assertEqual(a,b);self.assertEqual(len(list((self.root/'revisions').glob('r*'))),2)

    def test_stale_review_rejected(self):
        correct(self.root,self.request);other=copy.deepcopy(self.request);other['request_id']='another-review'
        with self.assertRaises(ReviewConflict):correct(self.root,other)

    def test_reused_request_id_with_changed_content_rejected(self):
        correct(self.root,self.request);self.request['changes'][0]['phase']='before'
        with self.assertRaises(ReviewConflict):correct(self.root,self.request)

    def test_wrong_source_manifest_rejected(self):
        self.request['source_manifest_sha256']='wrong'
        with self.assertRaises(ReviewConflict):correct(self.root,self.request)

    def test_unknown_duplicate_and_unconfirmed_changes_rejected(self):
        for changes in ([{'asset_id':'missing','phase':'before','confirm':True}],self.request['changes']*2,
                        [{'asset_id':'a','phase':'before','confirm':False}]):
            data={**self.request,'changes':changes}
            with self.assertRaises(ValueError):correct(self.root,data)
        self.assertEqual(current(self.root)[0]['revision'],1)

    def test_render_failure_does_not_publish_partial_revision(self):
        with patch('scripts.body_scan_delivery.pipeline.render',side_effect=OSError('failed renderer')):
            with self.assertRaises(OSError):correct(self.root,self.request)
        self.assertEqual(current(self.root)[0]['revision'],1)
        self.assertFalse((self.root/'revisions/r0002').exists())

    def test_source_mutation_is_rejected(self):
        Path(self.source['photos']['a']).write_bytes(b'changed')
        with self.assertRaises(ValueError):correct(self.root,self.request)
        self.assertEqual(current(self.root)[0]['revision'],1)

    def test_concurrent_reviews_cannot_overwrite_each_other(self):
        from concurrent.futures import ThreadPoolExecutor
        other=copy.deepcopy(self.request);other['request_id']='concurrent-review-2'
        def apply(value):
            try:return correct(self.root,value)['revision']
            except ReviewConflict:return 'conflict'
        with ThreadPoolExecutor(max_workers=2) as pool:
            values=list(pool.map(apply,[self.request,other]))
        self.assertCountEqual(values,[2,'conflict'])

    def test_retry_recovers_committed_revision_after_pointer_failure(self):
        real_save=save
        def interrupted(path,value):
            if Path(path).name=='current.json':raise OSError('simulated crash before pointer commit')
            return real_save(path,value)
        with patch('scripts.body_scan_delivery.pipeline.save',side_effect=interrupted):
            with self.assertRaises(OSError):correct(self.root,self.request)
        self.assertEqual(current(self.root)[0]['revision'],1)
        result=correct(self.root,self.request)
        self.assertEqual(result['revision'],2);self.assertEqual(current(self.root)[0]['revision'],2)

    def test_api_response_includes_review_and_download(self):
        app=FastAPI();app.include_router(router)
        with patch.dict('os.environ',{'CASE_DELIVERIES':str(self.root.parent)}),TestClient(app) as client:
            result=client.get('/api/productions/'+self.root.name).json()
            self.assertEqual(result['review']['asset_ids'],['a','b']);self.assertIn('preview_url',result)
            response=client.post('/api/productions/'+self.root.name+'/review',json=self.request)
            self.assertEqual(response.status_code,200);self.assertEqual(response.json()['revision'],2)
            self.assertEqual(client.get(response.json()['preview_url']).status_code,200)

    def test_api_never_serves_private_inputs_or_path_traversal(self):
        app=FastAPI();app.include_router(router)
        with patch.dict('os.environ',{'CASE_DELIVERIES':str(self.root.parent)}),TestClient(app) as client:
            prefix='/api/productions/'+self.root.name+'/files/r0001/'
            self.assertEqual(client.get(prefix+'private-inputs.json').status_code,404)
            self.assertEqual(client.get(prefix+'..%2F..%2Fprivate-inputs.json').status_code,404)


if __name__=='__main__':unittest.main()

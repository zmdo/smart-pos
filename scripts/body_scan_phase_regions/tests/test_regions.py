import copy
import tempfile
import unittest
import json
from pathlib import Path
from unittest.mock import Mock

import numpy as np

from scripts.body_scan_phase_regions.crops import crop_window, board, fitted_horizontal_window
from scripts.body_scan_phase_regions.evidence import CUES, compare, decision, prompt, validate
from scripts.body_scan_phase_regions.fusion import fuse
from scripts.body_scan_phase_regions.reports import validate_report, expected_changes
from scripts.body_scan_phase_regions.pipeline import inputs
from scripts.body_scan_phase.inputs import digest
from scripts.body_scan_phase_sessions.resolution import make_units, resolve
from scripts.body_scan_phase_sessions.tests.test_sessions import item, pair
from unittest.mock import patch


def observation(image='A', cue='waist_shape', clarity='clear'):
    return {'observations': {name:{'image':image if name==cue else 'unknown', 'clarity':clarity if name==cue else 'none',
            'comparable':True, 'confounds':[], 'reason':'可比部位的可见依据'} for name in CUES},
            'markers':{'A':'','B':''}, 'confidence':.6, 'reason':'逐部位评估'}


def packs():
    image = np.zeros((100,60,3), np.uint8)
    return [{'source':image.copy(),'uniform':image.copy(), 'crops':{r:image.copy() for r in ('upper','waist','legs')},
             'regions':{r:{'available':True,'reason':'ok'} for r in ('upper','waist','legs')}} for _ in range(2)]


def report_fixture():
    headers = ['类别','初始数据（训练前）','阶段数据（训练后）','变化量','单位']
    table = [headers,['时间','2026年1月1日','2026年2月1日','31','天'],
             ['身高','170','170','0','cm'],['体重','68','71','+3','kg'],['体脂率','17','13','-4','%'],
             ['BMI','23.5','22','-1.5','无'],['腰围','77','74','-3','cm']]
    raw = {'member':'测试人','store':'测试店','column_before':headers[1],'column_after':headers[2],
           'before_date':'2026-01-01','after_date':'2026-02-01','stated_days':31,'checked_goals':[],
           'goal_evidence':'无勾选','metrics':{}}
    for key,row in zip(('height','weight','fat','bmi','waist'),table[2:]):
        raw['metrics'][key] = dict(before=row[1],after=row[2],delta=row[3],unit=row[4],page=1,row_label=row[0],row_text=' | '.join(row))
    pages = ['姓名：测试人 门店：测试店\n'+'\n'.join(' | '.join(r) for r in table)]
    return raw,pages,[table]


class RegionTests(unittest.TestCase):
    def compare(self, first, second, data=None, **kwargs):
        client = Mock(); client.ask.side_effect=[(first,{}),(second,{})]
        return compare(client,data or packs(),**kwargs)

    def test_local_pose_problem_does_not_discard_other_region(self):
        a,b=observation(),observation('B')
        for raw in (a,b):
            raw['observations']['posture'].update(comparable=False,confounds=['pose'])
        result,_=self.compare(a,b)
        self.assertEqual(result['after'],'A')
        self.assertEqual(set(result['stable_cues']),{'waist_shape'})

    def test_changed_order_must_follow_image_not_slot(self):
        result,_=self.compare(observation(),observation())
        self.assertIsNone(result['after'])

    def test_cannot_switch_observation_to_pass_swap(self):
        result,_=self.compare(observation(),observation('B','upper_muscle'))
        self.assertIsNone(result['after'])

    def test_confounds_override_model_comparable_boolean(self):
        a,b=observation(),observation('B')
        a['observations']['waist_shape']['confounds']=['clothing']
        self.assertIsNone(self.compare(a,b)[0]['after'])

    def test_unavailable_crops_cannot_supply_evidence(self):
        data=packs();data[0]['regions']['waist']['available']=False
        self.assertIsNone(self.compare(observation(),observation('B'),data)[0]['after'])

    def test_conflicting_clear_view_not_erased_by_failed_swap(self):
        a=observation();a['observations']['upper_muscle'].update(image='B',clarity='clear')
        result,_=self.compare(a,observation('B'))
        self.assertEqual(result['reason'],'observation_directions_conflict')

    def test_same_image_production_guard_skips_model(self):
        client=Mock()
        result,_=compare(client,packs(),identical=True)
        client.ask.assert_not_called();self.assertIsNone(result['after'])

    def test_negative_control_records_raw_false_positive(self):
        result,audit=self.compare(observation(),observation('B'),identical=True,probe_identical=True)
        self.assertIsNone(result['after']);self.assertEqual(audit['negative_control']['raw_directional_claims'],2)
        self.assertTrue(audit['negative_control']['would_assign_without_identity_guard'])

    def test_report_not_in_visual_prompt(self):
        message=prompt(packs())
        self.assertNotIn('潘艺文',message);self.assertNotIn('2026',message)
        self.assertIn('没有训练报告',message)

    def test_subtle_remains_subtle(self):
        result,_=self.compare(observation(clarity='subtle'),observation('B'))
        self.assertEqual(result['strength'],'subtle')

    def test_schema_rejects_boolean_confidence(self):
        raw=observation();raw['confidence']=True
        with self.assertRaises(ValueError):validate(raw)

    def test_clip_is_marked_not_invented(self):
        image=np.full((100,100,3),42,np.uint8)
        crop,meta=crop_window(image,(0,50),80,80,[-.5,-.5,99.5,99.5])
        self.assertFalse(meta['available']);self.assertAlmostEqual(meta['real_pixel_fraction'],.5)
        self.assertTrue((crop[:,40:]==42).all());self.assertTrue((crop[:,:40]==235).all())

    def test_common_canvas_does_not_individually_rescale_narrow_body(self):
        a=np.zeros((200,100,3),np.uint8);b=np.zeros((200,50,3),np.uint8)
        output=board(a,b,'test')
        self.assertEqual(output.shape,(248,216,3))
        self.assertTrue((output[60:240,141:191]==0).all())

    def test_missing_background_does_not_mark_complete_torso_unavailable(self):
        edges=[-.5,-.5,767.5,1791.5]
        cx,width=fitted_horizontal_window(397,929,768,edges)
        image=np.zeros((1792,768,3),np.uint8)
        crop,meta=crop_window(image,(cx,700),width,574,edges)
        self.assertEqual(crop.shape[1],768)
        self.assertTrue(meta['available']);self.assertEqual(meta['real_pixel_fraction'],1.)

    def test_pair_uses_same_capped_width_without_rescaling(self):
        a=fitted_horizontal_window(300,900,600,[0,0,650,1800])
        b=fitted_horizontal_window(420,900,600,[0,0,768,1800])
        self.assertEqual(a[1],b[1]);self.assertEqual(a[1],600)


class ReportTests(unittest.TestCase):
    def checked(self,raw=None,pages=None,tables=None):
        r,p,t=report_fixture()
        return validate_report(raw or r,'测试店','测试人',pages or p,tables or t)

    def test_gain_weight_lose_fat_not_treated_as_regression(self):
        report=self.checked();trend=expected_changes(report)
        self.assertEqual(trend['directions'],{'waist_shape':'after'})
        self.assertFalse(report['metrics']['bmi']['usable'])
        self.assertIn('after: bmi_disagrees_with_height_weight',report['warnings'])

    def test_unchecked_goals_not_accepted_from_docx_text(self):
        raw,_,_=report_fixture();raw['checked_goals']=['增肌']
        self.assertEqual(self.checked(raw)['checked_goals'],[])

    def test_values_must_match_original_cells(self):
        raw,_,_=report_fixture();raw['metrics']['waist']['after']='70'
        report=self.checked(raw)
        self.assertNotIn('waist',report['metrics']);self.assertIn('waist',report['rejected_metrics'])

    def test_reversed_columns_are_read_by_labels(self):
        raw,pages,tables=report_fixture()
        for row in tables[0]:row[1],row[2]=row[2],row[1]
        pages=['测试店 测试人\n'+'\n'.join(' | '.join(r) for r in tables[0])]
        self.assertEqual(self.checked(raw,pages,tables)['metrics']['weight']['computed_delta'],[3.])

    def test_swapped_dates_block_report_use(self):
        raw,_,_=report_fixture();raw['before_date'],raw['after_date']=raw['after_date'],raw['before_date']
        report=self.checked(raw)
        self.assertEqual(expected_changes(report)['status'],'unavailable')

    def test_wrong_member_is_rejected(self):
        raw,_,_=report_fixture();raw['member']='另一人'
        with self.assertRaises(ValueError):self.checked(raw)

    def test_date_from_other_cell_cannot_be_used(self):
        raw,_,_=report_fixture();raw['before_date']='2026-02-01'
        self.assertIsNotNone(self.checked(raw)['date_issue'])

    def test_dates_truly_reversed_in_source_block_report(self):
        raw,pages,tables=report_fixture()
        raw['before_date'],raw['after_date']=raw['after_date'],raw['before_date']
        tables[0][1][1],tables[0][1][2]=tables[0][1][2],tables[0][1][1]
        self.assertEqual(self.checked(raw,pages,tables)['date_issue'],'report_dates_conflict_with_phase_columns')

    def test_incorrect_declared_change_sign_is_flagged(self):
        raw,pages,tables=report_fixture();raw['metrics']['waist']['delta']='+3'
        report=self.checked(raw,pages,tables)
        self.assertIn('waist: stated_delta_disagrees_with_cells',report['warnings'])
        self.assertEqual(report['metrics']['waist']['computed_delta'],[-3.])

    def test_bodyfat_outside_percentage_range_rejected(self):
        raw,pages,tables=report_fixture();tables[0][4][2]='130';raw['metrics']['fat']['after']='130'
        report=self.checked(raw,pages,tables)
        self.assertIn('fat',report['rejected_metrics'])

    def test_report_without_explicit_phase_headers_rejected(self):
        raw,_,_=report_fixture();raw['column_before']='第一次'
        with self.assertRaises(ValueError):self.checked(raw)

    def test_bodyfat_and_waist_conflict_does_not_guess_goal(self):
        report=self.checked();report['metrics']['waist']['computed_delta']=[3.]
        self.assertEqual(expected_changes(report)['status'],'unavailable')

    def test_bmi_and_weight_not_independent_votes(self):
        report=self.checked();del report['metrics']['waist']
        self.assertEqual(expected_changes(report)['status'],'unavailable')

    def test_arm_increase_does_not_imply_more_muscle(self):
        report=self.checked();report['metrics']['arm']={'computed_delta':[3.], 'usable':True}
        self.assertNotIn('upper_muscle',expected_changes(report)['directions'])


class FusionTests(unittest.TestCase):
    def setup_data(self,strength='subtle'):
        raw,pages,tables=report_fixture()
        report=validate_report(raw,'测试店','测试人',pages,tables)
        report.update(report_id='r1',expected_changes=expected_changes(report))
        observation={'after':'B','strength':strength,'reason':'stable_regional_observations','confidence':.6,'markers':{},
                     'stable_cues':{'waist_shape':{'image':'B','clarity':strength,'reason':'腰腹变化'}}}
        return observation,report

    def test_report_does_not_promote_subtle_or_claim_verified_chronology(self):
        obs,report=self.setup_data();result=fuse(obs,[report])
        self.assertEqual(result['strength'],'subtle')
        self.assertFalse(result['report_assistance']['verified_chronology'])

    def test_report_omission_does_not_erase_clear_independent_visual_cue(self):
        obs,report=self.setup_data();obs['strength']='clear'
        obs['stable_cues']['upper_muscle']={'image':'B','clarity':'clear','reason':'可比裸露肌肉'}
        result=fuse(obs,[report])
        self.assertEqual(result['strength'],'clear')
        self.assertEqual(result['report_assistance']['supporting_cues'],['waist_shape'])
        self.assertEqual(result['report_assistance']['visual_only_cues'],['upper_muscle'])

    def test_report_mapping_cannot_ignore_opposite_clear_visual_cue(self):
        obs,report=self.setup_data('clear')
        obs['stable_cues']['upper_muscle']={'image':'B','clarity':'clear','reason':'可比裸露肌肉'}
        report['expected_changes']['directions']['waist_shape']='before'
        self.assertIsNone(fuse(obs,[report])['after'])

    def test_no_visual_cue_cannot_infer_from_report_alone(self):
        obs,report=self.setup_data();obs.update(after=None,strength='none',stable_cues={})
        self.assertIsNone(fuse(obs,[report])['after'])

    def test_multiple_stage_reports_not_arbitrarily_selected(self):
        obs,report=self.setup_data()
        self.assertEqual(fuse(obs,[report,copy.deepcopy(report)])['report_assistance']['status'],'not_used')

    def test_documented_increase_can_map_leaner_to_before(self):
        obs,report=self.setup_data('clear');report['expected_changes']['directions']['waist_shape']='before'
        self.assertEqual(fuse(obs,[report])['after'],'A')

    def test_conflicting_visual_evidence_cannot_be_overridden_by_report(self):
        obs,report=self.setup_data();obs.update(after=None,reason='observation_directions_conflict')
        self.assertIsNone(fuse(obs,[report])['after'])

    def test_no_subtle_propagation_through_unreliable_batch(self):
        rows=[item('a'),item('b'),item('c','back'),item('d','back')]
        units=make_units(rows,[],'g')
        resolve(rows,units,[pair('p',['a','b'],strength='subtle'),pair('q',['c','d'],strength='subtle',view='back')])
        self.assertTrue(all(r['phase']=='unknown' for r in rows))

    def test_fixed_source_rule_survives_conflict(self):
        rows=[item('a',phase='before'),item('b',phase='after')]
        units=make_units(rows,[],'g');resolve(rows,units,[pair('p',['a','b'],after='A')])
        self.assertEqual([r['phase'] for r in rows],['before','after'])
        self.assertTrue(all('phase_warning' in r for r in rows))


class OverlayTests(unittest.TestCase):
    def fixture(self,root):
        base=root/'base';override=root/'override'
        base.mkdir();(override/'images/a1').mkdir(parents=True)
        source=root/'source.jpg';source.write_bytes(b'original')
        uniform=override/'images/a1/uniform.png';uniform.write_bytes(b'updated-reference')
        row={'asset_id':'a1','source':str(source),'source_sha256':digest(source),'uniform':'old',
             'uniform_sha256':'old-sha','store':'测试店','member':'会员','view':'front','phase':'before',
             'phase_source':'comparison_position_rule'}
        raw={'asset_id':'a1','source':str(source),'source_sha256':digest(source),'store':'测试店','member':'会员',
             'status':'displayed','output':{'uniform_sha256':digest(uniform)},
             'upstream_report':{'classification':{'kind':'body_scan','view':'front'}}}
        (base/'summary.json').write_text(json.dumps([raw]))
        (override/'summary.json').write_text(json.dumps([raw]))
        (override/'config.json').write_text(json.dumps({'version':'body-scan-group-display-v2'}))
        return base,override,row,raw

    def test_latest_reference_overlay_inherits_verified_source_rule(self):
        with tempfile.TemporaryDirectory() as tmp:
            base,over,row,_=self.fixture(Path(tmp))
            with patch('scripts.body_scan_phase_regions.pipeline.load',return_value=([row],[],{})):
                result,_,_,bindings=inputs(base,[over])
            self.assertEqual(result[0]['phase'],'before')
            self.assertEqual(result[0]['phase_source'],'comparison_position_rule')
            self.assertNotEqual(result[0]['uniform_sha256'],'old-sha')
            self.assertGreater(len(bindings),2)

    def test_override_cannot_substitute_another_person(self):
        with tempfile.TemporaryDirectory() as tmp:
            base,over,row,raw=self.fixture(Path(tmp));raw['member']='另一人'
            (over/'summary.json').write_text(json.dumps([raw]))
            with patch('scripts.body_scan_phase_regions.pipeline.load',return_value=([row],[],{})):
                with self.assertRaises(ValueError):inputs(base,[over])


if __name__=='__main__':unittest.main()

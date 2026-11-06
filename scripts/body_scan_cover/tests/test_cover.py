import unittest
from scripts.body_scan_cover.copy import compose
from scripts.body_scan_cover.framing import plan_pair
from scripts.body_scan_cover.render import story_lines


def report():
    return {'report_id':'r001','before_date':'2026-01-01','after_date':'2026-02-01','stated_days':31,
            'warnings':[],'metrics':{'weight':{'usable':True,'before_values':[70.],
            'after_values':[67.],'computed_delta':[-3.],'unit':'kg'}}}


def meta(shoulder=260, head='complete'):
    points=[[0,0] for _ in range(17)]
    points[5]=[230,shoulder];points[6]=[530,shoulder]
    points[11]=[270,shoulder+400];points[12]=[490,shoulder+400]
    return {'group_plan':{'H_normalized_to_display':[[1,0,0],[0,1,0],[0,0,1]]},
            'keypoints_normalized':points,'keypoint_confidence':[.95]*17,
            'visible_bounds_normalized':[100,20,660,1600],
            'visibility':{'head':head,'lower_extent':'feet_complete'}}


class CoverTests(unittest.TestCase):
    def test_loss_uses_kg_to_jin_and_not_report_example_numbers(self):
        words=compose('测试','测会员',report())
        self.assertEqual(words['headline'],'成功减重 6 斤')
        self.assertEqual(words['duration_days'],31)
        self.assertNotIn('52.8',words['story'])

    def test_conflicting_duration_omitted(self):
        r=report();r['stated_days']=30
        words=compose('测试','测会员',r)
        self.assertIsNone(words['duration_days'])
        self.assertNotIn('30',words['subtitle'])

    def test_gain_does_not_become_loss_or_invented_muscle_gain(self):
        r=report();r['metrics']['weight'].update(after_values=[73.],computed_delta=[3.])
        words=compose('测试','测会员',r)
        self.assertNotIn('减重',words['headline'])
        self.assertNotIn('增肌',words['story'])

    def test_missing_report_has_no_numeric_results_or_fake_coach(self):
        words=compose('测试','测会员',None)
        self.assertIsNone(words['coach'])
        self.assertFalse(any(ch.isdigit() for ch in words['story']))

    def test_user_story_replaces_auto_copy_without_modifying_facts(self):
        r=report();words=compose('测试','测会员',r,'某教练',{'story':'这是用户正文','title':'新的起点','coach':'','highlights':['用户正文']})
        self.assertEqual(words['story'],'这是用户正文')
        self.assertTrue(words['segments'][1]['emphasis'])
        self.assertEqual(words['coach'],'')
        self.assertEqual(words['facts']['weight']['delta'],-3.)

    def test_paired_crop_stays_in_bounds_and_scales_equally(self):
        plans=plan_pair([meta(),meta(270)],[(768,1792)]*2)
        self.assertAlmostEqual(plans[0]['scale'],plans[1]['scale'])
        for p in plans:
            self.assertAlmostEqual(p['scale_x'],p['scale_y'])
            x1,y1,x2,y2=p['crop_xyxy']
            self.assertTrue(0<=x1<x2<=768 and 0<=y1<y2<=1792)
            self.assertFalse(p['new_head_crop'])

    def test_existing_cut_head_is_recorded_not_reconstructed(self):
        plans=plan_pair([meta(100,'cut'),meta(110,'cut')],[(768,1100)]*2)
        self.assertTrue(all(p['head_already_incomplete'] for p in plans))

    def test_unreliable_pose_is_not_silently_center_cropped(self):
        m=meta();m['keypoint_confidence'][5]=.1
        with self.assertRaisesRegex(ValueError,'unreliable'):
            plan_pair([m,meta()],[(768,1792)]*2)

    def test_decimal_measurements_remain_one_token(self):
        lines=story_lines([{'text':'体重从 60.5kg 到 57.6kg。','emphasis':True}],
                          '/root/autodl-fs/case-studio/fonts/NotoSansSC.ttf',28,210)
        tokens=[word for row in lines for word,_,_ in row]
        self.assertIn('60.5kg',tokens)
        self.assertIn('57.6kg',tokens)

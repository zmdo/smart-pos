import unittest
from datetime import date
from scripts.body_report_compare.table_data import normalize,build_cases,valid_date
from scripts.body_report_compare.comparison_rows import summary_value

AS_OF=date(2026,11,7)
def source(sid):return {'source_id':sid,'store':'测试店','member':'会员甲','source_sha256':'a'*64}
def measurement(sid,day,weight):
 return normalize({'kind':'measurement','measurement_date':day,'metrics':[{'type':'体重','value':weight,'unit':'kg'}]},source(sid),AS_OF)
def summary(rows,before='2026-09-13',after='2026-10-16'):
 return normalize({'kind':'comparison_table','columns':{'before':'训练前','after':'训练后'},'before_date':before,'after_date':after,'rows':rows},source('t1'),AS_OF)
def cell(label,before,after,delta,unit):return {'type':label,'before':before,'after':after,'delta':delta,'unit':unit}

class OriginalFirstTests(unittest.TestCase):
 def test_invalid_future_and_non_20xx_years_rejected(self):
  for text in ('20266-09-13','1999-01-01','2100-01-01','2027-01-01','2026-11-08','2026-06-31'):
   self.assertIsNone(valid_date(text,AS_OF),text)
  self.assertEqual(valid_date('2026-11-07',AS_OF),'2026-11-07')
 def test_li_style_bad_date_and_summary_values_replaced(self):
  t=summary([cell('时间','20266年9月13日','2026年10月16日','333','天'),cell('体重','56，9','70','+13.1','kg'),cell('腰围','70','72','99','cm')],before='20266-09-13')
  c=build_cases([measurement('b','2026-09-13','56.9'),measurement('a','2026-10-16','63'),t],AS_OF)[0]
  rows={r['type']:r for r in c['rows']}
  self.assertEqual((rows['时间']['before'],rows['时间']['after'],rows['时间']['delta']),('2026-09-13','2026-10-16','33'))
  self.assertEqual((rows['体重']['before'],rows['体重']['after'],rows['体重']['delta']),('56.9','63','+6.1'))
  self.assertEqual(rows['体重']['sources']['before']['source_id'],'b')
  self.assertEqual(rows['腰围']['delta'],'+2');self.assertEqual(rows['腰围']['value_source_kind'],'summary_supplement')
  self.assertTrue(c['corrections'])
 def test_summary_only_days_and_deltas_recomputed(self):
  t=summary([cell('时间','2026年8月8日','2026年9月8日','30','天'),cell('体重','52.4','49.8','3.4','kg')],before='2026-08-08',after='2026-09-08')
  c=build_cases([t],AS_OF)[0];rows={r['type']:r for r in c['rows']}
  self.assertEqual(rows['时间']['delta'],'31');self.assertEqual(rows['体重']['delta'],'-2.6')
 def test_future_summary_not_printed_as_date(self):
  c=build_cases([summary([cell('时间','2030-01-01','2030-02-01','31','天'),cell('体重','60','59','-1','kg')],before='2030-01-01',after='2030-02-01')],AS_OF)[0]
  self.assertFalse(any(r['type']=='时间' for r in c['rows']))
  self.assertIsNone(c['pair'])
 def test_elapsed_days_cross_year_and_leap_day(self):
  t=summary([cell('体重','60','59','-1','kg')],before='2024-02-28',after='2024-03-01')
  self.assertEqual(build_cases([t],AS_OF)[0]['rows'][0]['delta'],'2')
  t=summary([cell('体重','60','59','-1','kg')],before='2025-12-31',after='2026-01-01')
  self.assertEqual(build_cases([t],AS_OF)[0]['rows'][0]['delta'],'1')
 def test_bilateral_and_combined_leg_deltas_not_averaged(self):
  t=summary([cell('臂围','L:32cm、R:32.5cm','L:30cm、R:30cm','wrong','cm'),
             cell('腿围','大腿:L68、R66.5 小腿:L39、R39','大腿:L66、R65 小腿:L39、R39','wrong','cm')])
  rows={r['type']:r for r in build_cases([t],AS_OF)[0]['rows']}
  self.assertEqual(rows['臂围']['delta'],'左:-2；右:-2.5')
  self.assertEqual(rows['腿围']['delta'],'大腿左:-2；大腿右:-1.5；小腿左:0；小腿右:0')
 def test_ambiguous_numeric_cell_not_guessed(self):
  self.assertIsNone(summary_value('56，9','kg','weight'))
 def test_missing_one_side_kept_blank_not_zero(self):
  c=build_cases([summary([cell('腰围','80','','+2','cm')])],AS_OF)[0]
  r=next(r for r in c['rows'] if r['type']=='腰围');self.assertEqual(r['after'],'');self.assertEqual(r['delta'],'')

 def test_bad_cell_cannot_be_hidden_by_plausible_model_date(self):
  t=summary([cell('时间','20266年9月13日','2026年10月16日','33','天'),cell('体重','60','59','-1','kg')])
  self.assertIsNone(t['before_date']);self.assertTrue(t['date_rejections'])
  c=build_cases([t],AS_OF)[0];self.assertFalse(any(r['type']=='时间' for r in c['rows']))
 def test_visible_date_cell_overrides_incorrect_model_metadata(self):
  t=summary([cell('时间','2026年9月13日','2026年10月15日','32','天'),cell('体重','60','59','-1','kg')])
  self.assertEqual(t['after_date'],'2026-10-15')
  self.assertEqual(build_cases([t],AS_OF)[0]['rows'][0]['delta'],'32')

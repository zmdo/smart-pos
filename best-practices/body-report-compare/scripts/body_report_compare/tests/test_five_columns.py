import unittest
from scripts.body_report_compare.table_data import normalize,derive,build_cases,number,cell_number

def source(sid='a1'):
    return {'source_id':sid,'store':'测试店','member':'会员甲','source_sha256':'a'*64}
def table():
    return {'kind':'comparison_table','member':'会员甲','columns':{'before':'初始数据（训练前）','after':'阶段数据（训练后）'},
       'rows':[{'type':'时间','before':'2026.1.1','after':'2026.2.1','delta':'31','unit':'天'},
               {'type':'未知指标','before':'60','after':'57','delta':'+3','unit':'分'}]}
def measurement(sid,day,value,unit='kg',name='体重'):
    return normalize({'kind':'measurement','measurement_date':day,'metrics':[{'type':name,'value':value,'unit':unit}]},source(sid))

class FiveColumnTests(unittest.TestCase):
    def test_transcription_preserves_unknown_rows_order_and_wrong_delta(self):
        r=normalize(table(),source());self.assertEqual([x['type'] for x in r['rows']],['时间','未知指标'])
        self.assertEqual(r['rows'][1]['delta'],'+3');self.assertEqual(r['rows'][1]['computed_delta'],'-3')
        self.assertTrue(r['rows'][1]['warnings'])
    def test_folder_and_printed_name_kept_distinct(self):
        raw=table();raw['member']='另一个人';r=normalize(raw,source())
        self.assertTrue(r['identity_ok']);self.assertTrue(r['warnings'])
        c=build_cases([r])[0];self.assertEqual(c['member'],'会员甲');self.assertEqual(c['display_member'],'另一个人')
    def test_report_store_authoritative_but_directory_preserved(self):
        raw=table();raw['store']='UP 健身私教馆';self.assertTrue(normalize(raw,source())['identity_ok'])
        raw['store']='别的店';r=normalize(raw,source());self.assertTrue(r['identity_ok'])
        c=build_cases([r])[0];self.assertEqual(c['store'],'测试店');self.assertEqual(c['display_store'],'别的店')
    def test_pair_uses_dates_even_when_weight_increased(self):
        a=measurement('a1','2026-02-01','70');b=measurement('a2','2026-01-01','60')
        case=build_cases([a,b])[0];self.assertEqual(case['pair']['before'],'a2');self.assertEqual(next(r for r in case['rows'] if r.get('key')=='weight')['delta'],'+10')
    def test_units_converted_before_calculation(self):
        a=measurement('a1','2026-01-01','120','斤');b=measurement('a2','2026-02-01','57')
        rows,_=derive(a,b);self.assertEqual(rows[0]['before'],'60');self.assertEqual(rows[0]['delta'],'-3');self.assertEqual(rows[0]['unit'],'kg')
    def test_missing_date_does_not_guess_order(self):
        a=measurement('a1',None,'60');b=measurement('a2','2026-02-01','57')
        case=build_cases([a,b])[0];self.assertIsNone(case['pair']);self.assertFalse(case['rows'])
    def test_original_measurement_has_priority_and_summary_fills_gaps(self):
        r=normalize(table(),source('a3'));a=measurement('a1','2026-01-01','60');b=measurement('a2','2026-02-01','57')
        c=build_cases([r,a,b])[0];self.assertEqual(c['table_origin'],'computed')
        self.assertEqual(next(r for r in c['rows'] if r['type']=='体重')['delta'],'-3')
        self.assertEqual(next(r for r in c['rows'] if r['type']=='未知指标')['delta'],'-3')
    def test_uncertain_or_missing_values_not_zero(self):
        a=measurement('a1','2026-01-01','60');b=measurement('a2','2026-02-01','')
        rows,skipped=derive(a,b);self.assertFalse(rows);self.assertTrue(skipped)
    def test_percent_delta_is_percentage_points(self):
        a=measurement('a1','2026-01-01','25','%','体脂率');b=measurement('a2','2026-02-01','20','%','体脂率')
        rows,_=derive(a,b);self.assertEqual(rows[0]['delta'],'-5');self.assertEqual(rows[0]['delta_semantics'],'percentage_points')
    def test_ambiguous_duplicate_metrics_not_silently_paired(self):
        a=measurement('a1','2026-01-01','60');a['metrics']*=2;b=measurement('a2','2026-02-01','57')
        rows,skipped=derive(a,b);self.assertFalse(rows);self.assertTrue(skipped)
    def test_explicit_table_dates_choose_matching_sessions(self):
        raw=table();raw.update(before_date='2026-02-01',after_date='2026-03-01');raw['rows'][0].update(before='2026.2.1',after='2026.3.1')
        r=normalize(raw,source('t1'))
        c=build_cases([r]+[measurement('a'+str(i),f'2026-0{i}-01',str(70-i)) for i in (1,2,3)])[0]
        self.assertEqual(c['pair']['before'],'a2');self.assertEqual(c['pair']['after'],'a3')

    def test_ambiguous_comma_is_not_multiplied_by_ten(self):
        self.assertIsNone(number("56，9"));self.assertEqual(str(number("1,200.5")),"1200.5")

    def test_attached_units_checked_without_changing_cells(self):
        self.assertEqual(str(cell_number("86.5kg","Kg")),"86.5")
        self.assertIsNone(cell_number("2026.10.12","天"))

    def test_missing_date_can_match_multiple_explicit_table_values(self):
        raw=table();raw.update(before_date='2026-01-01',after_date='2026-02-01',rows=[
            {'type':'体重','before':'60','after':'57','delta':'-3','unit':'kg'},
            {'type':'体脂率','before':'25','after':'20','delta':'-5','unit':'%'}])
        t=normalize(raw,source('t1'));a=measurement('a1',None,'60');b=measurement('a2','2026-02-01','57')
        a['metrics']+=measurement('m',None,'25','%','体脂率')['metrics']
        b['metrics']+=measurement('m',None,'20','%','体脂率')['metrics']
        c=build_cases([a,b,t])[0];self.assertEqual(c['pair']['before'],'a1')
        self.assertEqual(c['pair']['basis'],'matches_explicit_table_values')
        a['metrics']=a['metrics'][:1]
        self.assertIsNone(build_cases([a,b,t])[0]['pair'])

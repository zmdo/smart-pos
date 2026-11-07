import ast
import copy
import os
import tempfile
import unittest
from pathlib import Path
from PIL import Image
from report_comparison.render import render
from report_comparison.presentation import CORE_METRICS, select_display_rows

FONT=Path(os.environ.get('CASE_TEST_FONT','/root/autodl-fs/case-studio/fonts/NotoSansSC.ttf'))

class ReportProductTests(unittest.TestCase):
    def test_render_has_no_model_or_upstream_extraction_dependency(self):
        for path in Path(__file__).parents[1].glob('*.py'):
            tree=ast.parse(path.read_text());modules=[]
            for n in ast.walk(tree):
                if isinstance(n,ast.Import):modules.extend(x.name for x in n.names)
                elif isinstance(n,ast.ImportFrom):modules.append(n.module or '')
            self.assertFalse(any('body_report_compare' in m or 'client' in m or 'httpx' in m for m in modules))
    @unittest.skipUnless(FONT.exists(),'font not installed')
    def test_fixed_dimensions_uniform_scale_and_core_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);im=Image.new('RGB',(300,400),'#fac');im.save(root/'before.png');im.save(root/'after.png')
            c={'store':'测试店','member':'会员甲','table_origin':'transcribed','pair':{'before_date':'2026-01-01','after_date':'2026-02-01'},
                'rows':[dict(key=key,type=label,before='60',after='57',delta='-3',unit='kg') for key,label in CORE_METRICS]
                    +[dict(key='water',type='身体水分含量',before='42',after='41',delta='-1',unit='kg')]}
            r=render(c,{'before':root/'before.png','after':root/'after.png'},800,FONT,root/'out.png')
            with Image.open(root/'out.png') as output:self.assertEqual(output.size,(800,1000))
            self.assertEqual(r['row_count'],9)
            self.assertEqual(r['source_row_count'],10)
            self.assertTrue(all(x['uniform_scale'] and not x['content_clipped'] for x in r['images']))

    def test_available_core_rows_order_and_full_source_preserved(self):
        rows=[dict(key=k,type=t,before='60',after='57') for k,t in reversed(CORE_METRICS)]
        rows.append(dict(key='skeletal_muscle',type='骨骼肌量',before='30',after='32'))
        original=copy.deepcopy(rows)
        selected=select_display_rows(rows)
        self.assertEqual([r['key'] for r in selected],[k for k,_ in CORE_METRICS])
        self.assertEqual(rows,original)

    def test_hide_missing_both_sides_keep_one_side_and_zero(self):
        rows=[dict(key='chest',before='—',after=None),dict(key='hip',before='',after='未测'),
              dict(key='waist',before='68',after=''),dict(key='weight',before=0,after=0)]
        selected=select_display_rows(rows)
        self.assertEqual([r['key'] for r in selected],['weight','waist'])
        self.assertEqual(selected[1]['after'],'')

    @unittest.skipUnless(FONT.exists(),'font not installed')
    def test_five_seven_nine_rows_and_table_only_share_fixed_table_height(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);Image.new('RGB',(300,400),'#fac').save(root/'report.png')
            frames=[]
            for count in (5,7,9):
                c={'pair':{'before_date':'2026-01-01','after_date':'2026-02-01'},
                   'rows':[dict(key=k,type=t,before='60',after='57',delta='-3',unit='kg') for k,t in CORE_METRICS[:count]]}
                for paired in (True,False):
                    images={s:root/'report.png' for s in ('before','after')} if paired else {}
                    r=render(c,images,800,FONT,root/'out.png');frames.append(r['table_frame'][3])
                    self.assertEqual(r['row_count'],count)
                    self.assertAlmostEqual(r['header_height']+count*r['row_height'],r['table_frame'][3])
                    self.assertLessEqual(r['table_frame'][1]+r['table_frame'][3],r['height'])
                    with Image.open(root/'out.png') as im:self.assertEqual(im.size,(800,1000))
            self.assertEqual(set(frames),{round(800*.398)})
    def test_no_data_no_fabricated_product(self):
        with self.assertRaisesRegex(ValueError,'no_table'):render({'rows':[]},{},800,FONT,Path('/unused'))

    def test_old_transcribed_bundle_is_rejected_before_rendering(self):
        from scripts.body_scan_contracts.io import save
        from scripts.body_scan_contracts.bundles import seal
        from report_comparison.__main__ import run
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);tables=root/'tables';tables.mkdir()
            save(tables/'records.json',[]);save(tables/'tables.json',[{'table_origin':'transcribed'}])
            (tables/'index.html').write_text('old bundle')
            seal(tables,'body-report-five-column-v1',('records.json','tables.json','index.html'))
            with self.assertRaisesRegex(ValueError,'source_policy_upgrade_required'):
                run(tables,root/'missing-crops',root/'out',FONT)
            self.assertFalse((root/'out').exists())

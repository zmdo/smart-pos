import ast
import os
import tempfile
import unittest
from pathlib import Path
from PIL import Image
from report_comparison.render import render

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
    def test_fixed_dimensions_uniform_scale_all_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);im=Image.new('RGB',(300,400),'#fac');im.save(root/'before.png');im.save(root/'after.png')
            c={'store':'测试店','member':'会员甲','table_origin':'transcribed','pair':{'before_date':'2026-01-01','after_date':'2026-02-01'},
                'rows':[dict(type='指标'+str(i),before='60',after='57',delta='-3',unit='kg') for i in range(15)]}
            r=render(c,{'before':root/'before.png','after':root/'after.png'},800,FONT,root/'out.png')
            with Image.open(root/'out.png') as output:self.assertEqual(output.size,(800,1000))
            self.assertEqual(r['row_count'],15)
            self.assertTrue(all(x['uniform_scale'] and not x['content_clipped'] for x in r['images']))
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

import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from scripts.body_report_compare.extraction import validate_report
from scripts.body_report_compare.pipeline import run
from scripts.body_scan_contracts.io import read
from scripts.body_scan_contracts.bundles import load_reports


def fixture():
    headers=['类别','阶段数据（训练后）','初始数据（训练前）','变化量','单位']
    table=[headers,['时间','2026年2月1日','2026年1月1日','31','天'],['体重','57','60','-3','kg']]
    pages=['测试店 会员甲\n'+'\n'.join(' | '.join(r) for r in table)]
    raw={'member':'会员甲','store':'测试店','column_before':headers[2],'column_after':headers[1],
         'before_date':'2026-01-01','after_date':'2026-02-01','stated_days':31,'checked_goals':[],
         'metrics':{'weight':{'before':'60','after':'57','delta':'-3','unit':'kg','page':1,'row_label':'体重','row_text':'体重'}}}
    return raw,pages,[table]


class ReportNodeTests(unittest.TestCase):
    def test_reversed_columns_are_read_by_explicit_headers(self):
        raw,pages,tables=fixture()
        r=validate_report(raw,'测试店','会员甲',pages,tables)
        self.assertEqual(r['metrics']['weight']['computed_delta'],[-3])

    def test_unverified_cell_is_rejected(self):
        raw,pages,tables=fixture();raw['metrics']['weight']['after']='55'
        r=validate_report(raw,'测试店','会员甲',pages,tables)
        self.assertEqual(r['status'],'needs_review');self.assertIn('weight',r['rejected_metrics'])

    def test_extracts_without_any_photo_and_excludes_templates(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=root/'input'
            for name in ('测试店/会员甲/report.docx','参考模版/report.docx'):
                path=source/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b'docx')
            raw,pages,tables=fixture();client=Mock();client.ask.return_value=(raw,{})
            with patch('scripts.body_report_compare.pipeline.read_document',return_value=('31天',[],pages,tables)):
                result=run(source,root/'out',client)
            data=load_reports(root/'out')
            self.assertEqual(result['reports'],1);self.assertEqual(result['excluded_documents'],1)
            self.assertEqual(client.ask.call_count,1);self.assertNotIn('expected_changes',data[0])
            self.assertEqual(data[0]['source'],'测试店/会员甲/report.docx')

    def test_mismatched_member_folder_is_reported_not_silently_dropped(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=root/'input/测试店/另一个人';source.mkdir(parents=True)
            (source/'report.docx').write_bytes(b'docx');raw,pages,tables=fixture()
            client=Mock();client.ask.return_value=(raw,{})
            with patch('scripts.body_report_compare.pipeline.read_document',return_value=('',[],pages,tables)):
                run(root/'input',root/'out',client)
            record=read(root/'out/reports.json')[0]
            self.assertEqual(record['status'],'needs_review')
            self.assertEqual(record['reason'],'report_member_not_verified_in_member_folder')

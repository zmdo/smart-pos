import tempfile
import unittest
from pathlib import Path
from scripts.body_scan_contracts.io import save, sha
from scripts.body_scan_contracts.labels import decorate
from scripts.body_scan_contracts.bundles import seal, load_labels, load_reports, REPORT_SCHEMA, PHASE_SCHEMA


class ContractTests(unittest.TestCase):
    def fixture(self, root):
        photo=root/'photo.png';photo.write_bytes(b'approved-photo')
        row=decorate({'asset_id':'a1','group_id':'g1','store':'测试店','member':'会员','view':'front',
                      'phase':'before','label_kind':'pending','confidence':None,'source_sha256':sha(photo)})
        save(root/'labels.json',[row]);save(root/'report-link.json',{'path':None,'sha256':None})
        save(root/'inputs.json',{'photos':{'a1':str(photo)},'bindings':{str(photo):sha(photo)}})
        seal(root,PHASE_SCHEMA,('labels.json','inputs.json','report-link.json'))
        return row

    def test_complete_label_is_read_without_classifier(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);self.fixture(root)
            self.assertEqual(load_labels(root)[0][0]['label'],'训练前（待审）')

    def test_unknown_phase_is_rejected_even_with_valid_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);row=self.fixture(root);row['phase']='unknown';save(root/'labels.json',[row])
            seal(root,PHASE_SCHEMA,('labels.json','inputs.json','report-link.json'))
            with self.assertRaises(ValueError):load_labels(root)

    def test_removed_review_badge_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);row=self.fixture(root);row['requires_review']=False;save(root/'labels.json',[row])
            seal(root,PHASE_SCHEMA,('labels.json','inputs.json','report-link.json'))
            with self.assertRaises(ValueError):load_labels(root)

    def test_changed_pixels_or_labels_are_rejected(self):
        for target in ('photo.png','labels.json'):
            with tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);self.fixture(root);(root/target).write_bytes(b'changed')
                with self.assertRaises(ValueError):load_labels(root)

    def test_report_bundle_portable_without_original_documents(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);save(root/'reports.json',[]);save(root/'inventory.json',[])
            (root/'index.html').write_text('report')
            seal(root,REPORT_SCHEMA,('reports.json','inventory.json','index.html'))
            self.assertEqual(load_reports(root),[])

    def test_raw_report_directory_is_not_a_report_bundle(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'report.pdf').write_bytes(b'raw')
            with self.assertRaises(FileNotFoundError):load_reports(root)

    def test_bundle_cannot_escape_its_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);save(root/'bundle.json',{'schema_version':REPORT_SCHEMA,'files':{
                'reports.json':'a','inventory.json':'b','index.html':'c','../escape':'x'}})
            with self.assertRaises((ValueError,FileNotFoundError)):load_reports(root)

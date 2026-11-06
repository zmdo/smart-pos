import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from PIL import Image
from fastapi import FastAPI
from fastapi.testclient import TestClient
from unittest.mock import patch

from scripts.body_scan_contracts.io import save, sha
from scripts.body_scan_contracts.labels import decorate
from scripts.body_scan_contracts.bundles import seal, REPORT_SCHEMA, PHASE_SCHEMA
from scripts.body_scan_delivery.pipeline import create
from scripts.body_scan_delivery.api import router

FONT = Path('/root/autodl-fs/case-studio/fonts/NotoSansSC.ttf')


class NodeBoundaryTests(unittest.TestCase):
    def fixture(self, root):
        report=root/'report';report.mkdir()
        save(report/'reports.json',[]);save(report/'inventory.json',[])
        (report/'index.html').write_text('<html>独立报告</html>')
        seal(report,REPORT_SCHEMA,('reports.json','inventory.json','index.html'))
        labels=root/'labels';labels.mkdir();photo=root/'image.png'
        Image.new('RGB',(60,100),'green').save(photo)
        row=decorate({'asset_id':'a1','group_id':'g1','store':'测试店','member':'会员','view':'front',
            'source_sha256':sha(photo),'phase':'before','label_kind':'pending','confidence':None,'review_flags':[],
            'analysis_reason':'none','assignment_reason':'placeholder','analysis_phase':'unknown'})
        save(labels/'labels.json',[row]);save(labels/'inputs.json',{'photos':{'a1':str(photo)},'bindings':{str(photo):sha(photo)}})
        save(labels/'report-link.json',{'path':str(report),'sha256':sha(report/'bundle.json')})
        seal(labels,PHASE_SCHEMA,('labels.json','inputs.json','report-link.json'))
        return labels,report

    def test_generate_and_review_with_model_and_upstream_imports_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);labels,_=self.fixture(root)
            program='''
import sys, importlib.abc
from pathlib import Path
class Block(importlib.abc.MetaPathFinder):
 def find_spec(self,name,path=None,target=None):
  if any(name.startswith(p) for p in ('httpx','cv2','scripts.body_report_compare','scripts.body_scan_phase_classification','scripts.body_scan_phase_regions')):
   raise ImportError('renderer attempted upstream dependency: '+name)
sys.meta_path.insert(0,Block())
from scripts.body_scan_delivery.pipeline import create,correct
r=create(Path(sys.argv[1]),Path(sys.argv[2]),Path(sys.argv[3]))
r2=correct(Path(sys.argv[2]),dict(delivery_id=r['delivery_id'],base_revision=1,source_manifest_sha256=r['source_manifest_sha256'],request_id='isolated-review',changes=[dict(asset_id='a1',phase='after',confirm=True)]))
assert r2['items'][0]['label']=='训练后'
assert r2['report_comparison']['preview']=='reports/index.html'
'''
            result=subprocess.run([sys.executable,'-c',program,str(labels),str(root/'production-isolated'),str(FONT)],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)

    def test_raw_analysis_rejected_instead_of_classifying_in_renderer(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);save(root/'summary.json',[{'phase':'unknown'}])
            with self.assertRaises(FileNotFoundError):create(root,root/'production-rejected',FONT)
            self.assertFalse((root/'production-rejected').exists())

    def test_different_report_bundle_requires_reclassification(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);labels,report=self.fixture(root)
            (report/'index.html').write_text('changed report')
            seal(report,REPORT_SCHEMA,('reports.json','inventory.json','index.html'))
            with self.assertRaises(ValueError):create(labels,root/'production-mismatch',FONT)

    def test_report_files_are_served_but_audits_remain_private(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);labels,_=self.fixture(root)
            create(labels,root/'production-report',FONT)
            app=FastAPI();app.include_router(router)
            with patch.dict('os.environ',{'CASE_DELIVERIES':str(root)}),TestClient(app) as client:
                prefix='/api/productions/production-report/files/r0001/'
                self.assertEqual(client.get(prefix+'reports/index.html').status_code,200)
                self.assertEqual(client.get(prefix+'reports/reports.json').status_code,200)
                self.assertEqual(client.get(prefix+'reports/r001/audit.json').status_code,404)

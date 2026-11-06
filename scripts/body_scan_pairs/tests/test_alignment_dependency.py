"""The default split entry must actually finish the approved v4 guard."""
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from scripts.body_scan_pairs.pipeline import align


class AlignmentDependencyTests(unittest.TestCase):
    def fixture(self, root, guarded=True):
        (root/'dataset').mkdir()
        (root/'dataset/job.json').write_text(json.dumps({'assets': [{'id': 'child'}]}))
        (root/'summary.json').write_text(json.dumps([{'children': [{
            'asset_id': 'child', 'parent_asset_id': 'parent',
            'crop_parent_xyxy': [100, 0, 300, 400],
            'H_parent_to_child': [[1, 0, -100], [0, 1, 0], [0, 0, 1]]}]}]))
        (root/'aligned').mkdir()
        (root/'aligned/config.json').write_text(json.dumps({
            'best_practice_version': 'body-scan-wall-v4',
            'geometry_guard_version': 'body-scan-geometry-guard-v1' if guarded else None}))
        (root/'aligned/summary.json').write_text(json.dumps([{
            'asset_id': 'child', 'status': 'rectangular',
            'frame': {'H_source_to_aligned': [[2, 0, 0], [0, 2, 0], [0, 0, 1]]}}]))

    def test_default_uses_v4_and_composes_parent_coordinates(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); self.fixture(root)
            with patch('scripts.body_scan_pairs.pipeline.subprocess.run',
                       return_value=SimpleNamespace(returncode=0)) as run:
                align(root)
            self.assertEqual(run.call_count, 2)
            for call in run.call_args_list:
                self.assertEqual(call.kwargs['cwd'].name, 'body-scan-wall-v4')
                self.assertNotIn('PYTHONPATH', call.kwargs['env'])
            audit = json.loads((root/'alignment.json').read_text())
            self.assertEqual(audit['status'], 'complete')
            self.assertEqual(audit['best_practice_version'], 'body-scan-wall-v4')
            self.assertTrue(audit['geometry_guard_version'])
            mapping = json.loads((root/'parent-coordinate-mapping.json').read_text())[0]
            self.assertEqual(mapping['H_parent_to_aligned'], [[2, 0, -200], [0, 2, 0], [0, 0, 1]])

    def test_successful_process_without_guard_is_not_accepted(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); self.fixture(root, guarded=False)
            with patch('scripts.body_scan_pairs.pipeline.subprocess.run',
                       return_value=SimpleNamespace(returncode=0)):
                with self.assertRaisesRegex(ValueError, 'approved_geometry_guard_missing'):
                    align(root)
            self.assertEqual(json.loads((root/'alignment.json').read_text())['status'], 'failed')
            self.assertFalse((root/'parent-coordinate-mapping.json').exists())

    def test_failed_dependency_check_stops_before_alignment(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); self.fixture(root)
            with patch('scripts.body_scan_pairs.pipeline.subprocess.run',
                       return_value=SimpleNamespace(returncode=1)) as run:
                with self.assertRaisesRegex(ValueError, 'approved_pipeline_failed'):
                    align(root)
            self.assertEqual(run.call_count, 1)
            self.assertEqual(json.loads((root/'alignment.json').read_text())['status'], 'failed')

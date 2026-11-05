import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import cv2
import numpy as np

from .. import pipeline
from ..framing import UniformConfig, compose_full_source
from ..localization import Subject
from ..non_grid import identity_transform, NonGridTransform


class PipelineTests(unittest.TestCase):
    def test_non_grid_transform_preserves_pixels_and_returns_identity(self):
        source = np.random.default_rng(1).integers(0, 256, (80, 60, 3), dtype=np.uint8)
        before = source.copy()
        H, metadata = identity_transform(source)
        np.testing.assert_array_equal(H, np.eye(3))
        np.testing.assert_array_equal(source, before)
        self.assertFalse(metadata['correction_applied'])

    def test_non_grid_composes_only_uniform_scale_translation(self):
        source = np.full((256, 128, 3), 120, np.uint8)
        kp = [[0, 0]] * 17
        kp[5], kp[6], kp[11], kp[12] = [44, 65], [84, 65], [44, 145], [84, 145]
        pose = {'anchor': [64, 65], 'torso_length': 80, 'selected_pairs': [[5, 11], [6, 12]], 'keypoints_corrected': kp}
        estimator = Mock()
        estimator.locate.return_value = {'pose': pose}
        subject = Subject([30, 20, 98, 240], [], [], {})
        with patch.object(pipeline, 'grid_transform', side_effect=AssertionError('grid branch invoked')):
            image, available, used, report = pipeline.render(source, subject,
                {'background': 'wood', 'view': 'front'}, estimator, UniformConfig(128, 256), NonGridTransform(mode='identity'))
        A = np.asarray(report['frame']['H_source_to_aligned'])
        np.testing.assert_allclose(A[:2, :2], np.eye(2) * (256*.27/80))
        np.testing.assert_array_equal(A[2], [0, 0, 1])
        self.assertEqual(image.shape, (256, 128, 3))
        self.assertFalse(((used > 0) & (available == 0)).any())
        x1, y1, x2, y2 = report['frame']['content_rectangle_xyxy']
        self.assertEqual(np.count_nonzero(used), (x2-x1)*(y2-y1))

    def test_comparison_and_non_body_skip_before_reads_or_inference(self):
        cases = [{'kind': 'body_scan', 'people': 1, 'phase': 'both'},
                 {'kind': 'body_scan', 'people': 2}, {'kind': 'life', 'people': 1}]
        with patch.object(pipeline.cv2, 'imread', side_effect=AssertionError('image read')):
            for c in cases:
                localizer = Mock()
                result = pipeline.process({'id': 'a', 'class': c}, Path('/missing'), Path('/missing'), localizer, Mock(), UniformConfig())
                self.assertEqual(result['status'], 'skipped')
                localizer.localize.assert_not_called()

    def test_grid_routes_to_approved_solver(self):
        solver = Mock(side_effect=ValueError('solver reached'))
        with patch.object(pipeline, 'grid_transform', solver), self.assertRaisesRegex(ValueError, 'solver reached'):
            pipeline.render(np.zeros((80, 60, 3), np.uint8), Mock(), {'background': 'grid_board'}, Mock(), UniformConfig())
        solver.assert_called_once()

    def test_black_edge_bands_excluded_but_interior_dark_clothes_retained(self):
        source = np.full((128, 64, 3), 140, np.uint8)
        source[:10] = 0; source[-10:] = 0; source[20:90, 20:40] = 0
        output, mask, metadata = compose_full_source(source, np.eye(3), UniformConfig(64, 128))
        self.assertFalse(mask[:10].any()); self.assertFalse(mask[-10:].any())
        self.assertTrue(mask[20:90, 20:40].all())
        np.testing.assert_array_equal(output[10:-10], source[10:-10])

    def test_incomplete_group_keeps_review_ids_and_view_order(self):
        records = [{'asset_id': aid, 'store': '店', 'member': '人', 'status': status,
                    'classification': {'kind': 'body_scan', 'people': 1, 'view': view,
                                       'wall_background': True, 'body_scan_pose': True}}
                   for aid, view, status in [('a', 'side_left', 'rectangular'), ('b', 'front', 'needs_review'), ('c', 'back', 'rectangular')]]
        group = pipeline.group_records(records)[0]
        self.assertEqual(group['asset_ids'], ['c', 'a'])
        self.assertEqual(group['excluded_asset_ids'], ['b'])
        self.assertEqual(group['status'], 'partial')

    def test_bad_ids_rejected_before_output_and_old_output_protected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); job = root/'job.json'; out = root/'out'
            for assets in ([{'id': '../escape'}], [{'id': 'a'}, {'id': 'a'}]):
                job.write_text(json.dumps({'assets': assets}))
                with self.assertRaises(ValueError):
                    pipeline.run(job, out, Mock(), Mock())
                self.assertFalse(out.exists())
            job.write_text(json.dumps({'assets': []})); out.mkdir(); (out/'sentinel').write_text('keep')
            with self.assertRaises(FileExistsError):
                pipeline.run(job, out, Mock(), Mock())
            self.assertEqual((out/'sentinel').read_text(), 'keep')

    def test_empty_selection_still_writes_complete_reports(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); job = root/'job.json'; out = root/'out'
            job.write_text(json.dumps({'assets': []}))
            localizer = Mock(); pose = Mock()
            self.assertEqual(pipeline.run(job, out, localizer, pose), ([], []))
            for name in ('summary.json', 'groups.json'):
                self.assertEqual(json.loads((out/name).read_text()), [])
            localizer.localize.assert_not_called(); pose.locate.assert_not_called()


if __name__ == '__main__':
    unittest.main()

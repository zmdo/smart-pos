import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import cv2
import numpy as np

from .. import pipeline
from ..classification import apply_audit
from ..framing import UniformConfig
from ..landmarks import landmarks, AlignmentUnavailable
from ..localization import Subject
from ..non_grid import NonGridTransform, CameraCorrectionUnavailable
from scripts.non_grid_camera.geometry import rotation, render as experiment_render


LABELS = {'kind': 'body_scan', 'people': 1, 'background': 'wood', 'view': 'front',
          'wall_background': True, 'body_scan_pose': True, 'training_activity': False,
          'classification_rule': 'cls-v3-wall'}


def estimate(**overrides):
    return {'K': [[300, 0, 64], [0, 300, 128], [0, 0, 1]],
            'R': rotation(.03, -.07).tolist(), 'camera_model': 'pinhole', 'k1': 0.,
            'roll_deg': float(np.degrees(.03)), 'pitch_deg': float(np.degrees(-.07)),
            'vfov_deg': 45., 'roll_uncertainty_deg': 2., 'pitch_uncertainty_deg': 5.,
            'vfov_uncertainty_deg': 12., 'focal_relative_uncertainty': .25, **overrides}


class CameraIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.source = np.full((256, 128, 3), 135, np.uint8)
        self.subject = Subject([25, 20, 110, 245], [], [], {})

    def test_approved_middle_column_matrix_is_reused_exactly(self):
        calibrated = estimate(); model = Mock(return_value=calibrated)
        H, metadata = NonGridTransform(calibrator=model)(self.source, self.subject)
        _, _, old = experiment_render(self.source, self.subject.box, calibrated, radial=False)
        np.testing.assert_array_equal(H, old['H_source_to_output'])
        model.assert_called_once_with(self.source, 'pinhole')
        self.assertEqual(metadata['action'], 'camera_pinhole')
        self.assertEqual(metadata['applied_k1'], 0)
        self.assertIn('camera_angle_uncertain', metadata['warnings'])
        self.assertTrue(metadata['correction_applied'])
        self.assertTrue((self.source == 135).all())

    def test_extreme_camera_keeps_report_and_never_falls_back_to_identity(self):
        model = Mock(return_value=estimate(pitch_deg=-26))
        with self.assertRaises(CameraCorrectionUnavailable) as raised:
            NonGridTransform(calibrator=model)(self.source, self.subject)
        self.assertEqual(str(raised.exception), 'camera_estimate_outside_experiment_limits')
        self.assertFalse(raised.exception.geometry['correction_applied'])
        self.assertEqual(raised.exception.geometry['calibration']['pitch_deg'], -26)

    def test_radial_model_and_invalid_cached_parameters_rejected(self):
        for change in ({'camera_model': 'simple_radial'}, {'k1': .02}, {'K': np.zeros((3, 3)).tolist()},
                       {'R': [[1, 0, 0], [0, 1, 0], [0, 0, -1]]}, {'pitch_deg': float('nan')}):
            with self.assertRaises(CameraCorrectionUnavailable):
                NonGridTransform(calibrator=Mock(return_value=estimate(**change)))(self.source, self.subject)

    def test_model_error_is_reviewable(self):
        with self.assertRaisesRegex(CameraCorrectionUnavailable, 'camera_calibration_RuntimeError'):
            NonGridTransform(calibrator=Mock(side_effect=RuntimeError('model unavailable')))(self.source, self.subject)

    def test_camera_and_framing_sample_original_once_and_measure_transformed_pose(self):
        kp = np.zeros((17, 3)); kp[:, 2] = .95
        kp[[5, 6, 11, 12], :2] = [[40, 65], [85, 65], [40, 145], [85, 145]]
        pose = Mock()
        pose.locate.side_effect = lambda image, box, H, view: {'pose': landmarks(kp, H, box, view)}
        camera = NonGridTransform(calibrator=Mock(return_value=estimate()))
        with patch.object(cv2, 'warpPerspective', wraps=cv2.warpPerspective) as warp:
            image, available, used, report = pipeline.render(self.source, self.subject, LABELS, pose,
                                                           UniformConfig(128, 256), camera)
        image_calls = [call for call in warp.call_args_list if call.args[0].ndim == 3]
        self.assertEqual(len(image_calls), 1)
        self.assertIs(pose.locate.call_args.args[0], self.source)
        H = np.asarray(report['geometry']['H_source_to_corrected'])
        A = np.asarray(report['frame']['H_corrected_to_aligned'])
        np.testing.assert_allclose(image_calls[0].args[1], A @ H)
        np.testing.assert_allclose(report['pose']['anchor'], landmarks(kp, H, self.subject.box, 'front')['anchor'])
        self.assertAlmostEqual(A[0, 0]*report['pose']['torso_length']/256, .27)
        self.assertEqual(image.shape, (256, 128, 3))
        self.assertFalse(((used > 0) & (available == 0)).any())

    def test_stale_wall_tags_and_training_skip_before_any_model(self):
        for labels, status in [({'kind': 'body_scan', 'people': 1, 'background': 'wood'}, 'needs_review'),
                               ({**LABELS, 'wall_background': False}, 'skipped'),
                               ({**LABELS, 'training_activity': True}, 'skipped')]:
            localizer, camera = Mock(), Mock()
            with patch.object(cv2, 'imread', side_effect=AssertionError('image read')):
                row = pipeline.process({'id': 'a', 'class': labels}, Path('/missing'), Path('/out'),
                                       localizer, Mock(), UniformConfig(), camera)
            self.assertEqual(row['status'], status)
            localizer.localize.assert_not_called(); camera.assert_not_called()

    def test_pose_failure_preserves_successful_camera_diagnostics(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); cv2.imwrite(str(root/'source.png'), self.source)
            localizer = Mock(); localizer.localize.return_value = self.subject
            pose = Mock(); pose.locate.side_effect = AlignmentUnavailable('pose_failed')
            screening = Mock(); screening.check.return_value = {'status': 'allowed'}
            row = pipeline.process({'id': 'a', 'path': 'source.png', 'class': LABELS, 'store': '店', 'member': '人'},
                                   root, root/'out', localizer, pose, UniformConfig(),
                                   NonGridTransform(calibrator=Mock(return_value=estimate())), screening)
            self.assertEqual(row['status'], 'needs_review')
            self.assertEqual(row['reason'], 'pose_failed')
            self.assertTrue(row['geometry']['correction_applied'])
            self.assertIn('H_source_to_corrected', row['geometry'])

    def audit_fixture(self, root):
        (root/'source').write_bytes(b'photo')
        assets = [{'id': 'a', 'path': 'source', 'class': {'kind': 'body_scan'}}]
        audit = root/'audit.json'
        records = [{'asset_id': 'a', 'source_sha256': hashlib.sha256(b'photo').hexdigest(),
                    'prompt_version': 'cls-v3-wall', 'classification': {**LABELS, 'kind': 'daily_training'}}]
        audit.write_text(json.dumps(records))
        return assets, audit, records

    def test_verified_audit_replaces_legacy_label_without_mutating_job(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); assets, audit, _ = self.audit_fixture(root)
            result, metadata = apply_audit(assets, root, audit)
            self.assertEqual(result[0]['class']['kind'], 'daily_training')
            self.assertEqual(assets[0]['class']['kind'], 'body_scan')
            self.assertEqual(metadata['applied_count'], 1)

    def test_audit_source_mismatch_and_duplicate_ids_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); assets, audit, records = self.audit_fixture(root)
            (root/'source').write_bytes(b'different photo')
            with self.assertRaisesRegex(ValueError, 'source_mismatch'):
                apply_audit(assets, root, audit)
            audit.write_text(json.dumps(records*2))
            with self.assertRaisesRegex(ValueError, 'duplicate'):
                apply_audit(assets, root, audit)

    def test_audit_mismatch_rejected_before_output_creation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); inputs = root/'input'; inputs.mkdir()
            assets, audit, records = self.audit_fixture(inputs)
            (inputs/'source').write_bytes(b'changed')
            (root/'job.json').write_text(json.dumps({'assets': assets}))
            with self.assertRaisesRegex(ValueError, 'source_mismatch'):
                pipeline.run(root/'job.json', root/'out', Mock(), Mock(), classification_audit=audit)
            self.assertFalse((root/'out').exists())


if __name__ == '__main__':
    unittest.main()

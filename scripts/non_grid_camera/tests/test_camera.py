import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import numpy as np

from ..geometry import rotation, forward, inverse, render, undistort
from ..__main__ import eligible, run, save_json, assess_variants


class CameraGeometryTests(unittest.TestCase):
    K = np.array([[600., 0, 200], [0, 600, 350], [0, 0, 1.]])

    def test_synthetic_wall_recovers_both_axes_and_proportions(self):
        # Independent 3D pinhole/radial projection of a front-facing rectangle.
        xyz = np.array([[-.2, -.4, 1], [.2, -.4, 1], [.2, .4, 1], [-.2, .4, 1]])
        for roll, pitch in ((7, -9), (-8, 11)):
            R = rotation(*np.radians([roll, pitch]))
            for k in (0., .08, -.08):
                camera_points = (R @ xyz.T).T
                q = camera_points[:, :2]/camera_points[:, 2:]
                q *= (1+k*np.sum(q*q, axis=1))[:, None]
                photographed = q * [600, 600] + [200, 350]
                restored = forward(photographed, self.K, R, k)
                np.testing.assert_allclose(restored, xyz[:, :2]*600+[200, 350], atol=1e-7)

    def test_roundtrip_inverse_map_preserves_camera_geometry(self):
        points = np.random.default_rng(4).uniform([40, 40], [360, 660], (100, 2))
        R = rotation(*np.radians([4., -8.]))
        for k in (-.07, 0., .07):
            corrected = forward(points, self.K, R, k)
            original, valid = inverse(corrected, self.K, R, k)
            self.assertTrue(valid.all())
            np.testing.assert_allclose(original, points, atol=1e-7)

    def test_pinhole_is_the_inverse_rotation_homography(self):
        R = rotation(*np.radians([5, -10]))
        points = np.array([[10, 50], [200, 330], [300, 650]])
        H = self.K @ R.T @ np.linalg.inv(self.K)
        q = np.c_[points, np.ones(3)] @ H.T
        np.testing.assert_allclose(forward(points, self.K, R), q[:, :2]/q[:, 2:])

    def test_identity_render_keeps_all_real_pixels(self):
        source = np.random.default_rng(8).integers(30, 256, (120, 80, 3), dtype=np.uint8)
        calibration = {'K': [[100, 0, 40], [0, 100, 60], [0, 0, 1]], 'R': np.eye(3).tolist(), 'k1': 0}
        output, mask, report = render(source, [20, 10, 60, 110], calibration)
        np.testing.assert_array_equal(output[2:122, 2:82], source)
        self.assertEqual(np.count_nonzero(mask), 120*80)
        self.assertTrue((output[mask == 0] == [227, 234, 238]).all())

    def test_folded_radial_model_rejected(self):
        with self.assertRaisesRegex(ValueError, 'non_monotonic'):
            undistort(np.array([[1., 1.]]), -.7)

    def test_radial_mapping_is_not_mislabeled_as_homography(self):
        source = np.full((120, 80, 3), 120, np.uint8)
        calibration = {'K': [[120, 0, 40], [0, 120, 60], [0, 0, 1]], 'R': rotation(.02, -.03).tolist(), 'k1': .03}
        _, mask, report = render(source, [20, 10, 60, 110], calibration, radial=True)
        self.assertNotIn('H_source_to_output', report)
        self.assertTrue(mask.any())

    def test_wall_training_and_comparisons_excluded(self):
        c = {'kind': 'body_scan', 'people': 1, 'phase': 'unknown', 'background': 'wood',
             'wall_background': True, 'body_scan_pose': True, 'training_activity': False}
        self.assertIsNone(eligible({'classification': c}))
        for changes in ({'kind': 'daily_training'}, {'training_activity': True},
                        {'wall_background': False}, {'phase': 'both'}, {'people': 2},
                        {'background': 'grid_board'}):
            self.assertIsNotNone(eligible({'classification': {**c, **changes}}))

    def test_training_photo_skips_image_reads_and_model_inference(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); audit = root/'audit.json'; baseline = root/'baseline'; baseline.mkdir()
            audit.write_text(json.dumps([{'asset_id': 'a0169', 'classification': {'kind': 'daily_training'}}]))
            (baseline/'summary.json').write_text('[]')
            model = Mock(side_effect=AssertionError('inference'))
            with patch('scripts.non_grid_camera.__main__.Calibrator', return_value=model), \
                 patch('scripts.non_grid_camera.__main__.cv2.imread', side_effect=AssertionError('image read')):
                result = run(audit, baseline, root/'out', root, root)
            self.assertEqual(result[0]['status'], 'skipped')
            model.assert_not_called()

    def test_chinese_report_is_utf8_even_after_native_library_changes_locale(self):
        import locale
        previous = locale.setlocale(locale.LC_CTYPE)
        try:
            locale.setlocale(locale.LC_CTYPE, 'C')
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp)/'report.json'
                save_json(path, {'member': '潘艺文'})
                self.assertEqual(json.loads(path.read_text(encoding='utf-8'))['member'], '潘艺文')
        finally:
            locale.setlocale(locale.LC_CTYPE, previous)

    def test_disagreeing_calibration_models_are_not_silently_promoted(self):
        row = {'variants': {'pinhole': {'calibration': {'roll_deg': 0, 'pitch_deg': 1, 'vfov_deg': 45}},
                            'radial': {'calibration': {'roll_deg': 0, 'pitch_deg': -16, 'vfov_deg': 60}}}}
        assess_variants(row)
        self.assertFalse(row['automatic_adoption'])
        for variant in row['variants'].values():
            self.assertIn('camera_models_disagree', variant['warnings'])


if __name__ == '__main__':
    unittest.main()

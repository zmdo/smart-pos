"""Independent standard-frame geometry and saved-experiment contract tests."""
import hashlib
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
import grid_standard_frame as frame


class StandardFrameTests(unittest.TestCase):
    def test_exact_center_when_space_is_available(self):
        rect, A, info = frame.select_frame([0, 0, 1000, 1600], [400, 400, 600, 1200],
                                           np.eye(3), frame.FrameConfig())
        np.testing.assert_allclose([(rect[0]+rect[2])/2, (rect[1]+rect[3])/2], [500, 800])
        self.assertAlmostEqual((rect[2]-rect[0])/(rect[3]-rect[1]), 3/5)
        self.assertAlmostEqual(info['actual_box_height_fraction'], .9)
        np.testing.assert_allclose(info['center_offset_fraction'], [0, 0], atol=1e-12)
        self.assertEqual(A[0, 0], A[1, 1])

    def test_minimum_horizontal_shift_at_image_boundary(self):
        rect, _, info = frame.select_frame([0, 0, 600, 1000], [10, 150, 310, 850],
                                           np.eye(3), frame.FrameConfig())
        self.assertEqual(rect[0], 0)
        self.assertGreater(rect[2], 310)
        self.assertLessEqual(rect[3], 1000)
        self.assertIn('center_shift_to_fit_available_image', info['warnings'])
        self.assertAlmostEqual(info['subject_box_retained_fraction'], 1.)

    def test_partial_body_allowed_without_creating_missing_head_pixels(self):
        rect, _, info = frame.select_frame([20, 100, 580, 900], [160, 0, 440, 1000],
                                           np.eye(3), frame.FrameConfig())
        self.assertEqual(rect[1], 100)
        self.assertLess(info['subject_box_retained_fraction'], 1.)
        self.assertIn('partial_head_band_crop_or_source_truncation', info['warnings'])
        self.assertEqual(info['output_size'], [768, 1280])

    def test_uniform_scale_preserves_rectified_angles_and_cell_shape(self):
        H = np.array([[1., .04, 20], [.02, 1., 10], [.00004, -.00003, 1.]])
        _, A, info = frame.select_frame([0, 0, 1200, 1800], [350, 300, 750, 1400], H,
                                        frame.FrameConfig(761, 1280))
        square = np.array([[500, 700], [550, 700], [500, 750]], float)
        mapped = frame.project(square, A)
        dx, dy = mapped[1]-mapped[0], mapped[2]-mapped[0]
        self.assertAlmostEqual(float(dx@dy), 0., places=9)
        self.assertAlmostEqual(float(np.linalg.norm(dx)), float(np.linalg.norm(dy)), places=9)
        source = np.array([[400, 600], [500, 900]], float)
        np.testing.assert_allclose(frame.project(source, np.array(info['H_source_to_standard'])),
                                   frame.project(frame.project(source, H), A))

    def saved_fixture(self, path):
        path.mkdir()
        image = np.random.default_rng(9).integers(30, 230, (480, 300, 3), dtype=np.uint8)
        cv2.imwrite(str(path/'original.png'), image)
        cv2.imwrite(str(path/'corrected.png'), image)
        cv2.imwrite(str(path/'valid_mask.png'), np.full((480, 300), 255, np.uint8))
        return {'asset_id': 'a001', 'status': 'corrected', 'size': [300, 480],
                'classification': {'people': 1, 'kind': 'body_scan', 'background': 'grid_board'},
                'H_source_to_output': np.eye(3).tolist(), 'subject_box': [100, 50, 200, 450],
                'crop': {'status': 'cropped', 'bounds_xyxy': [20, 20, 280, 460]}}

    def test_exact_dimensions_and_previous_files_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            row = self.saved_fixture(root/'saved')
            before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (root/'saved').iterdir()}
            for width, height in [(180, 300), (151, 256)]:
                out = root/f'out-{width}'
                report = frame.process(root/'saved', row, out, frame.FrameConfig(width, height))
                self.assertEqual(report['status'], 'standardized')
                self.assertEqual(cv2.imread(str(out/'standardized.png')).shape[:2], (height, width))
                self.assertEqual(report['valid_fraction'], 1.)
                self.assertEqual(report['new_model_requests'], 0)
            after = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (root/'saved').iterdir()}
            self.assertEqual(before, after)

    def test_internal_invalid_pixels_reject_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            row = self.saved_fixture(root/'saved')
            valid = cv2.imread(str(root/'saved/valid_mask.png'), 0)
            valid[220:225, 145:150] = 0
            cv2.imwrite(str(root/'saved/valid_mask.png'), valid)
            report = frame.process(root/'saved', row, root/'out', frame.FrameConfig(180, 300))
            self.assertEqual(report['status'], 'needs_review')
            self.assertEqual(report['reason'], 'standard_frame_contains_invalid_pixels')
            self.assertFalse((root/'out/standardized.png').exists())

    def test_comparison_skips_before_image_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            row = {'asset_id': 'a001', 'classification': {'people': 2, 'phase': 'both'}}
            with patch.object(cv2, 'imread', side_effect=AssertionError('must not read images')):
                r = frame.process('/missing', row, Path(tmp)/'out', frame.FrameConfig())
            self.assertEqual(r['status'], 'skipped')
            self.assertEqual(r['reason'], 'comparison_or_multiple_people')

    def test_uncertain_previous_crop_is_not_silently_standardized(self):
        row = {'asset_id': 'a001', 'classification': {'people': 1, 'kind': 'body_scan', 'background': 'grid_board'},
               'status': 'corrected', 'crop': {'status': 'needs_review'}}
        with tempfile.TemporaryDirectory() as tmp:
            r = frame.process('/missing', row, Path(tmp)/'out', frame.FrameConfig())
            self.assertEqual(r['reason'], 'requires_accepted_v23_grid_crop')

    def test_output_directory_cannot_be_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(FileExistsError):
                frame.process('/missing', {}, Path(tmp), frame.FrameConfig())

    def test_invalid_config_and_subject_geometry(self):
        for kwargs in ({'width': 0}, {'subject_fill': 1.1}, {'width': 1280, 'height': 768}):
            with self.assertRaises(frame.FrameUnavailable):
                frame.FrameConfig(**kwargs)
        with self.assertRaises(frame.FrameUnavailable):
            frame.select_frame([0, 0, 100, 100], [200, 200, 300, 300], np.eye(3), frame.FrameConfig())


if __name__ == '__main__':
    unittest.main()

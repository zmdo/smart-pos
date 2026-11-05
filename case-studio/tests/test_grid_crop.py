"""Post-warp framing regressions. Run in the server's Python environment."""
import sys
import unittest
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from grid_crop import CropUnavailable, choose_rectangle, content_mask, crop_rectified, grid_bounds


class GridCropTests(unittest.TestCase):
    def fixture(self):
        image = np.random.default_rng(7).integers(40, 230, (400, 300, 3), dtype=np.uint8)
        subject = np.zeros((400, 300), bool)
        subject[50:390, 120:180] = True
        vertical = np.array([[x, 45, x, 320] for x in range(35, 270, 20)], float)
        horizontal = np.array([[35, y, 255, y] for y in range(45, 330, 20)], float)
        return image, subject, vertical, horizontal

    def test_grid_frame_allows_partial_body_and_preserves_pixels(self):
        image, subject, v, h = self.fixture()
        cropped, info = crop_rectified(image, np.full((400, 300), 255, np.uint8),
                                      image, subject, [120, 50, 180, 390], np.eye(3), v, h)
        x1, y1, x2, y2 = info['bounds_xyxy']
        np.testing.assert_array_equal(cropped, image[y1:y2, x1:x2])
        self.assertFalse(info['resampled'])
        self.assertLess(info['subject_mask_retained_fraction'], .85)
        self.assertGreater(info['subject_mask_retained_fraction'], .7)
        self.assertEqual(info['head_band_mask_retained_fraction'], 1.)
        self.assertEqual(info['valid_fraction'], 1.)
        self.assertLess(y2, 340)
        np.testing.assert_array_equal(info['H_source_to_crop'], [[1, 0, -x1], [0, 1, -y1], [0, 0, 1]])

    def test_trapezoid_never_leaves_blank_corners(self):
        safe = np.zeros((400, 300), np.uint8)
        cv2.fillConvexPoly(safe, np.array([[30, 10], [270, 40], [235, 390], [65, 380]]), 1)
        _, subject, _, _ = self.fixture()
        rect, info = choose_rectangle(safe > 0, [15, 10, 285, 395], subject, [120, 50, 180, 390])
        x1, y1, x2, y2 = rect
        self.assertTrue(safe[y1:y2, x1:x2].all())
        self.assertGreater((x2-x1)*(y2-y1), 50000)
        self.assertEqual(info['head_band_mask_retained_fraction'], 1.)

    def test_internal_hole_is_not_mistaken_for_valid_rectangle(self):
        _, subject, _, _ = self.fixture()
        safe = np.ones((400, 300), bool)
        safe[10:25, 140:155] = False
        rect, _ = choose_rectangle(safe, [20, 10, 280, 380], subject, [120, 50, 180, 390])
        x1, y1, x2, y2 = rect
        self.assertTrue(safe[y1:y2, x1:x2].all())

    def test_letterbox_removed_without_removing_black_clothes(self):
        image, _, _, _ = self.fixture()
        image[:30] = 0
        image[-25:] = 3
        image[100:300, 120:180] = 0
        mask, bounds = content_mask(image)
        self.assertEqual(bounds, [0, 30, 300, 375])
        self.assertEqual(mask[:30].sum(), 0)
        self.assertTrue(mask[100:300, 120:180].all())

    def test_black_image_not_misidentified_as_letterbox(self):
        _, bounds = content_mask(np.zeros((100, 100, 3), np.uint8))
        self.assertEqual(bounds, [0, 0, 100, 100])

    def test_side_letterboxes(self):
        image, _, _, _ = self.fixture()
        image[:, :20] = 0
        image[:, -30:] = 0
        _, bounds = content_mask(image)
        self.assertEqual(bounds, [20, 0, 270, 400])

    def test_isolated_grid_direction_cannot_expand_frame(self):
        image, _, v, h = self.fixture()
        v = np.r_[v, [[295, 0, 295, 399]] * 10]
        bounds = grid_bounds(v, h, np.eye(3), image.shape)
        self.assertLess(bounds[2], 260)
        self.assertGreater(bounds[1], 40)

    def test_head_above_first_grid_line_is_preserved(self):
        _, subject, _, _ = self.fixture()
        subject[35:50, 120:180] = True
        rect, info = choose_rectangle(np.ones((400, 300), bool), [30, 180, 270, 330],
                                      subject, [120, 35, 180, 390])
        self.assertLess(rect[1], 35)
        self.assertEqual(info['head_band_mask_retained_fraction'], 1.)
        self.assertLess(rect[3], 391)

    def test_fit_inliers_do_not_cut_off_visible_grid_at_bottom(self):
        image, _, v, h = self.fixture()
        truncated_v = v.copy()
        truncated_v[:, 3] = 230
        truncated_h = h[h[:, 1] <= 230]
        # Adjacent poster fragments do not change the grid's horizontal extent.
        extra_v = np.r_[v, [[290, 0, 290, 399]] * 8]
        expanded = grid_bounds(truncated_v, truncated_h, np.eye(3), image.shape, (extra_v, h))
        self.assertGreater(expanded[3], 300)
        self.assertLess(expanded[2], 260)

    def test_framing_recovers_grid_fragments_excluded_from_fitting(self):
        _, subject, v, h = self.fixture()
        image = np.full((400, 300, 3), 220, np.uint8)
        for x in range(35, 270, 20):
            cv2.line(image, (x, 45), (x, 365), (30, 30, 30), 2)
        for y in range(45, 370, 20):
            cv2.line(image, (35, y), (255, y), (30, 30, 30), 2)
        v[:, 3] = 230
        h = h[h[:, 1] <= 230]
        cropped, report = crop_rectified(image, np.full((400, 300), 255, np.uint8),
                                         image, subject, [120, 50, 180, 390], np.eye(3), v, h,
                                         extent_lines=(v, h))
        self.assertGreater(report['bounds_xyxy'][3], 350)
        x1, y1, x2, y2 = report['bounds_xyxy']
        np.testing.assert_array_equal(cropped, image[y1:y2, x1:x2])

    def test_invalid_grid_region_is_explicit_failure(self):
        _, subject, v, h = self.fixture()
        with self.assertRaises(CropUnavailable):
            choose_rectangle(np.zeros((400, 300), bool), [30, 45, 270, 330],
                             subject, [120, 50, 180, 390])
        with self.assertRaises(CropUnavailable):
            grid_bounds(v[:2], h, np.eye(3), (400, 300))


if __name__ == '__main__':
    unittest.main()

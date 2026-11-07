"""Geometry/content-preservation checks; execute on the remote server."""
import unittest

import numpy as np
from PIL import Image

from scripts.report_photo_crop.geometry import make_frame, parse_ratio


class CropTests(unittest.TestCase):
    def test_screenshot_crops_ui_and_preserves_all_selected_content(self):
        pixels = np.zeros((800, 600, 3), dtype=np.uint8)
        pixels[200:600, 50:550] = [120, 150, 180]
        im = Image.fromarray(pixels)
        selection = {'is_report': True, 'medium': 'screenshot',
                     'content_box': [80, 250, 920, 750], 'issues': []}
        frame, crop, evidence = make_frame(im, selection)
        self.assertEqual(frame.width*4, frame.height*3)
        self.assertEqual(evidence['scale_x'], evidence['scale_y'])
        x1, y1, x2, y2 = evidence['crop_xyxy']
        np.testing.assert_array_equal(np.asarray(crop), pixels[y1:y2, x1:x2])
        self.assertGreater(y1, 0)
        self.assertLess(y2, 800)
        self.assertFalse(evidence['dewarping'])
        self.assertFalse(evidence['background_mask_applied'])
        scale = evidence['scale_x']
        dx, dy = evidence['placement_xy']
        self.assertGreaterEqual(dx, 0)
        self.assertGreaterEqual(dy, 0)
        self.assertLessEqual(dx+crop.width*scale, frame.width)
        self.assertLessEqual(dy+crop.height*scale, frame.height)
        self.assertEqual(scale, 1)
        np.testing.assert_array_equal(np.asarray(frame)[dy:dy+crop.height, dx:dx+crop.width], np.asarray(crop))

    def test_paper_mask_keeps_content_pixels_and_removes_outside_clutter(self):
        rng = np.random.default_rng(3)
        pixels = rng.integers(0, 255, (1000, 800, 3), dtype=np.uint8)
        im = Image.fromarray(pixels)
        selection = {'is_report': True, 'medium': 'paper_photo', 'content_box': [100, 100, 900, 900],
                     'paper_box': [0, 0, 1000, 1000],
                     'paper_polygon': [[150, 0], [850, 0], [1000, 1000], [0, 1000]]}
        frame, crop, evidence = make_frame(im, selection)
        # Inside the paper all original pixel values stay identical, despite masking.
        np.testing.assert_array_equal(np.asarray(crop)[100:900, 160:640], pixels[100:900, 160:640])
        self.assertEqual(tuple(np.asarray(crop)[0, 0]), (255, 255, 255))
        self.assertEqual(evidence['scale_x'], evidence['scale_y'])
        self.assertEqual(frame.width*4, frame.height*3)
        self.assertTrue(evidence['background_mask_applied'])

    def test_conflicting_paper_boundary_preserves_original_instead(self):
        im = Image.new('RGB', (800, 1000), (80, 90, 100))
        selection = {'is_report': True, 'medium': 'paper_photo', 'content_box': [0, 0, 1000, 1000],
                     'paper_box': [0, 0, 1000, 1000],
                     'paper_polygon': [[300, 0], [700, 0], [700, 1000], [300, 1000]]}
        _, crop, evidence = make_frame(im, selection)
        np.testing.assert_array_equal(np.asarray(crop), np.asarray(im))
        self.assertFalse(evidence['background_mask_applied'])
        self.assertTrue(evidence['review_reasons'])

    def test_fixed_ratio_keeps_native_resolution_and_cap_is_explicit(self):
        selection = {'is_report': True, 'medium': 'screenshot', 'content_box': [0, 0, 1000, 1000]}
        source = Image.new('RGB', (2000, 1600), (120, 40, 80))
        full, _, g = make_frame(source, selection)
        self.assertEqual(full.size, (2001, 2668))
        self.assertEqual(g['scale_x'], 1)
        small, _, s = make_frame(source, selection, max_side=720)
        self.assertEqual(small.size, (540, 720))
        self.assertLess(s['scale_x'], 1)
        self.assertEqual(s['scale_x'], s['scale_y'])
        self.assertEqual(parse_ratio('6:8'), (3, 4))
        with self.assertRaises(ValueError):parse_ratio('0:4')

    def test_unknown_or_invalid_regions_are_not_silently_cropped(self):
        im = Image.new('RGB', (600, 800))
        with self.assertRaisesRegex(ValueError, 'unknown_report_medium'):
            make_frame(im, {'is_report': True, 'medium': 'other'})
        with self.assertRaisesRegex(ValueError, 'invalid_normalized_box'):
            make_frame(im, {'is_report': True, 'medium': 'screenshot', 'content_box': [0, -1, 1000, 1000]})


if __name__ == '__main__':
    unittest.main()

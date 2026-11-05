"""All usable original pixels are retained without changing portrait geometry."""
import json
import sys
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from grid_crop import content_mask
from shoulder_alignment import AlignmentUnavailable
from grid_shoulder_frame_uniform import UniformConfig
import grid_shoulder_frame_full_source as pipeline


class FullSourceTests(unittest.TestCase):
    def setUp(self):
        self.config = UniformConfig(64, 128)
        self.image = np.full((128, 64, 3), [90, 140, 210], np.uint8)
        self.H = np.array([[1.05, .08, -9.3], [.03, 1.08, -4.7], [.0004, .0002, 1.]])

    def test_identity_uses_entire_original_not_inset_grid_rectangle(self):
        self.image[40:80, 20:45] = [30, 60, 90]
        image, used, _ = pipeline.compose_full_source(self.image, np.eye(3), self.config)
        np.testing.assert_array_equal(image, self.image)
        self.assertTrue((used == 255).all())
        old = np.zeros((128, 64), np.uint8); old[20:110, 10:50] = 255
        gained = pipeline.coverage_gain(old, used)
        self.assertEqual(np.count_nonzero(gained), 128*64-90*40)

    def test_perspective_footprint_retains_every_available_pixel(self):
        image, used, missing = pipeline.compose_full_source(self.image, self.H, self.config)
        expected = cv2.warpPerspective(np.full((128, 64), 255, np.uint8), self.H, (64, 128), flags=cv2.INTER_NEAREST)
        np.testing.assert_array_equal(used, expected)
        self.assertTrue((image[used > 0] == [90, 140, 210]).all())
        self.assertTrue((image[used == 0] == self.config.background_rgb[::-1]).all())
        self.assertEqual(missing['missing_outside_original_pixels'], np.count_nonzero(used == 0))

    def test_black_bands_are_excluded_without_interpolation_black_halo(self):
        self.image[:16] = 0; self.image[-16:] = 0
        image, used, missing = pipeline.compose_full_source(self.image, self.H, self.config)
        mask, _ = content_mask(self.image)
        expected = cv2.warpPerspective(mask, self.H, (64, 128), flags=cv2.INTER_NEAREST)
        np.testing.assert_array_equal(used, expected)
        self.assertTrue((image[used > 0] == [90, 140, 210]).all())
        self.assertGreater(missing['missing_original_black_band_pixels'], 0)
        self.assertEqual(missing['missing_original_black_band_pixels']+missing['missing_outside_original_pixels'],
                         np.count_nonzero(used == 0))

    def test_dark_clothes_inside_image_remain_real_content(self):
        self.image[40:100, 20:45] = 0
        image, used, _ = pipeline.compose_full_source(self.image, np.eye(3), self.config)
        self.assertTrue((used == 255).all())
        np.testing.assert_array_equal(image, self.image)

    def test_replicated_boundary_samples_never_fill_missing_regions(self):
        H = np.array([[1, 0, 20.5], [0, 1, 15.5], [0, 0, 1.]])
        image, used, _ = pipeline.compose_full_source(self.image, H, self.config)
        self.assertTrue((used[:, :20] == 0).all())
        self.assertTrue((used[:15] == 0).all())
        self.assertTrue((image[used == 0] == self.config.background_rgb[::-1]).all())

    def test_interior_source_pixels_match_previous_cubic_sampling_exactly(self):
        yy, xx = np.indices(self.image.shape[:2])
        self.image[:, :, 0] = xx*3; self.image[:, :, 1] = yy; self.image[:, :, 2] = 200
        result, _, _ = pipeline.compose_full_source(self.image, self.H, self.config)
        old = cv2.warpPerspective(self.image, self.H, (64, 128), flags=cv2.INTER_CUBIC)
        interior = np.zeros((128, 64), np.uint8); interior[4:-4, 4:-4] = 255
        interior = cv2.warpPerspective(interior, self.H, (64, 128), flags=cv2.INTER_NEAREST) > 0
        np.testing.assert_array_equal(result[interior], old[interior])

    def test_rejects_loss_of_previously_visible_source_content(self):
        old = np.full((128, 64), 255, np.uint8); new = old.copy(); new[50, 30] = 0
        with self.assertRaisesRegex(AlignmentUnavailable, 'real_content_would_be_lost'):
            pipeline.coverage_gain(old, new)

    def test_previous_mask_must_be_binary_and_match_output_size(self):
        for old in (np.zeros((2, 2), np.uint8), np.ones((128, 64), np.uint8)):
            with self.assertRaisesRegex(AlignmentUnavailable, 'invalid_previous_content_mask'):
                pipeline.coverage_gain(old, np.full((128, 64), 255, np.uint8))

    def test_off_canvas_source_is_reported_instead_of_fabricated(self):
        H = np.array([[1, 0, 1000], [0, 1, 1000], [0, 0, 1.]])
        with self.assertRaisesRegex(AlignmentUnavailable, 'source_outside_frame'):
            pipeline.compose_full_source(self.image, H, self.config)

    def fixture(self, root, rows, groups):
        previous = root/'previous'; previous.mkdir(); base = root/'base'; base.mkdir()
        (previous/'config.json').write_text(json.dumps(asdict(self.config)))
        (previous/'summary.json').write_text(json.dumps(rows))
        (previous/'groups.json').write_text(json.dumps(groups))
        (base/'summary.json').write_text(json.dumps([{'asset_id': r['asset_id']} for r in rows]))
        return previous, base

    def test_comparisons_and_failed_inputs_do_not_read_images(self):
        rows = [{'asset_id': 'a', 'status': 'skipped', 'reason': 'comparison_or_multiple_people'},
                {'asset_id': 'b', 'status': 'needs_review', 'reason': 'pose_failed'}]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); previous, base = self.fixture(root, rows, [])
            with patch.object(pipeline.cv2, 'imread', side_effect=AssertionError('no images expected')):
                result, groups = pipeline.run(previous, base, root/'out')
            self.assertEqual([r['status'] for r in result], ['skipped', 'needs_review'])
            self.assertEqual(result[1]['reason'], 'pose_failed'); self.assertEqual(groups, [])

    def test_failed_member_is_excluded_without_changing_group_target(self):
        rows = [{'asset_id': aid, 'status': 'uniform', 'pose': {}} for aid in ('a', 'b')]
        groups = [{'group_id': 'g001', 'member': '人', 'store': '店', 'requested_asset_ids': ['a', 'b'],
                   'output_ids': ['a', 'b'], 'torso_fraction': .27, 'shoulder_target_xy': [31.5, 28.94]}]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); previous, base = self.fixture(root, rows, groups)
            with patch.object(pipeline, 'render', side_effect=[{}, AlignmentUnavailable('failed')]), \
                    patch.object(pipeline, 'group_previews'), patch.object(pipeline, 'previews'):
                _, result = pipeline.run(previous, base, root/'out')
            self.assertEqual(result[0]['status'], 'partial')
            self.assertEqual(result[0]['excluded_asset_ids'], ['b'])
            self.assertEqual(result[0]['torso_fraction'], .27)

    def test_duplicate_ids_rejected_before_output_created(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); previous, base = self.fixture(root, [{'asset_id': 'a'}, {'asset_id': 'a'}], [])
            with self.assertRaisesRegex(AlignmentUnavailable, 'duplicate_asset_ids'):
                pipeline.run(previous, base, root/'out')
            self.assertFalse((root/'out').exists())

    def test_prior_experiment_cannot_be_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for protected in ('previous', 'base'):
                with self.assertRaisesRegex(AlignmentUnavailable, 'separate'):
                    pipeline.run(root/'previous', root/'base', root/protected/'nested')

    def test_already_recovered_results_cannot_be_reused_as_v3_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); previous, base = self.fixture(root, [{'asset_id': 'a', 'status': 'full_source'}], [])
            with self.assertRaisesRegex(AlignmentUnavailable, 'requires_uniform_v3_report'):
                pipeline.run(previous, base, root/'out')
            self.assertFalse((root/'out').exists())


if __name__ == '__main__':
    unittest.main()

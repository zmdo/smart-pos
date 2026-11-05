"""Exact rectangle optimality against exhaustive search, and pixel preservation."""
import json
import sys
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path
from unittest.mock import patch

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from shoulder_alignment import AlignmentUnavailable
from grid_shoulder_frame_uniform import UniformConfig
import grid_shoulder_frame_max_rectangle as pipeline


def exhaustive(mask, required=None):
    """Slow independent oracle enumerating every possible rectangle."""
    h, w = mask.shape; best = None; score = None
    for y1 in range(h):
        for y2 in range(y1+1, h+1):
            for x1 in range(w):
                for x2 in range(x1+1, w+1):
                    if required is not None:
                        rx1, ry1, rx2, ry2 = required
                        if x1 > rx1 or y1 > ry1 or x2 < rx2 or y2 < ry2:
                            continue
                    if not mask[y1:y2, x1:x2].all():
                        continue
                    key = ((y2-y1)*(x2-x1), y2-y1, y2, -x1)
                    if score is None or key > score:
                        best, score = [x1, y1, x2, y2], key
    return (best, score[0]) if best is not None else None


class MaximumRectangleTests(unittest.TestCase):
    def test_full_rectangle_is_not_unnecessarily_trimmed(self):
        self.assertEqual(pipeline.largest_valid_rectangle(np.ones((12, 8))), ([0, 0, 8, 12], 96))

    def test_all_512_small_masks_match_exhaustive_global_optimum(self):
        for bits in range(512):
            mask = np.array([(bits >> i) & 1 for i in range(9)], bool).reshape(3, 3)
            expected = exhaustive(mask)
            if expected is None:
                with self.assertRaisesRegex(AlignmentUnavailable, 'no_valid_rectangle'):
                    pipeline.largest_valid_rectangle(mask)
            else:
                self.assertEqual(pipeline.largest_valid_rectangle(mask), expected, bits)

    def test_required_rectangles_and_holes_match_randomized_exhaustive_oracle(self):
        rng = np.random.default_rng(20261105)
        for _ in range(100):
            mask = rng.random((5, 6)) < .8
            y1, y2 = sorted(rng.choice(6, 2, replace=False)); x1, x2 = sorted(rng.choice(7, 2, replace=False))
            required = [int(x1), int(y1), int(x2), int(y2)]
            expected = exhaustive(mask, required)
            if expected is None:
                with self.assertRaises(AlignmentUnavailable):
                    pipeline.largest_valid_rectangle(mask, required)
            else:
                self.assertEqual(pipeline.largest_valid_rectangle(mask, required), expected)

    def test_slanted_footprint_does_not_use_its_unavailable_bounding_box(self):
        mask = np.zeros((8, 10), np.uint8)
        for y in range(8):
            mask[y, y//2:6+y//2] = 255
        rect, size = pipeline.largest_valid_rectangle(mask)
        self.assertEqual((rect, size), exhaustive(mask))
        x1, y1, x2, y2 = rect
        self.assertTrue(mask[y1:y2, x1:x2].all()); self.assertLess(size, mask.size)

    def test_subject_constraint_cannot_be_misreported_as_unconstrained_maximum(self):
        mask = np.zeros((10, 12), np.uint8); mask[:, :6] = 255; mask[2:8, 8:12] = 255
        rect, report = pipeline.select_rectangle(mask, [9, 3, 11, 7])
        self.assertEqual(rect, [8, 2, 12, 8]); self.assertEqual(report['selected_rectangle_area'], 24)
        self.assertEqual(report['unconstrained_maximum_area'], 60)
        self.assertFalse(report['is_unconstrained_global_maximum'])

    def test_equal_area_solution_prioritizes_height_then_lower_content(self):
        mask = np.zeros((8, 8), np.uint8); mask[:2, :4] = 1; mask[4:, 6:] = 1
        self.assertEqual(pipeline.largest_valid_rectangle(mask), ([6, 4, 8, 8], 8))

    def test_invalid_mask_and_required_bounds_are_rejected(self):
        for mask in (np.zeros((0, 3)), np.zeros((3, 3, 1))):
            with self.assertRaisesRegex(AlignmentUnavailable, 'invalid_available_mask'):
                pipeline.largest_valid_rectangle(mask)
        for required in ([0, 0, 0, 1], [-1, 0, 2, 2], [0, 0, 4, 2], [0, 0, 1.5, 2]):
            with self.assertRaisesRegex(AlignmentUnavailable, 'invalid_required_rectangle'):
                pipeline.largest_valid_rectangle(np.ones((3, 3)), required)

    def test_copy_keeps_pixels_and_geometry_without_resampling(self):
        image = np.arange(12*8*3, dtype=np.uint8).reshape(12, 8, 3)
        mask = np.ones((12, 8), np.uint8)*255
        output, used = pipeline.rectangular_image(image, mask, [1, 2, 7, 11], [238, 234, 227])
        np.testing.assert_array_equal(output[2:11, 1:7], image[2:11, 1:7])
        self.assertTrue((output[used == 0] == [227, 234, 238]).all())
        self.assertEqual(np.count_nonzero(used), 6*9); self.assertEqual(output.shape, image.shape)

    def test_internal_hole_cannot_be_covered_with_fake_photo_pixels(self):
        mask = np.full((12, 8), 255, np.uint8); mask[5, 3] = 0
        with self.assertRaisesRegex(AlignmentUnavailable, 'unavailable_pixels'):
            pipeline.rectangular_image(np.zeros((12, 8, 3), np.uint8), mask, [1, 2, 7, 11], [238, 234, 227])

    def fixture(self, root, rows, groups):
        previous = root/'previous'; previous.mkdir()
        (previous/'config.json').write_text(json.dumps(asdict(UniformConfig())))
        (previous/'summary.json').write_text(json.dumps(rows)); (previous/'groups.json').write_text(json.dumps(groups))
        return previous

    def test_comparisons_and_previously_failed_images_are_skipped_without_image_reads(self):
        rows = [{'asset_id': 'a', 'status': 'skipped', 'reason': 'comparison_or_multiple_people'},
                {'asset_id': 'b', 'status': 'needs_review', 'reason': 'pose_failed'}]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); previous = self.fixture(root, rows, [])
            with patch.object(pipeline.cv2, 'imread', side_effect=AssertionError('no images expected')):
                records, groups = pipeline.run(previous, root/'out')
            self.assertEqual([r['status'] for r in records], ['skipped', 'needs_review'])
            self.assertEqual(records[1]['reason'], 'pose_failed'); self.assertEqual(groups, [])

    def test_failed_member_remains_explicitly_excluded(self):
        rows = [{'asset_id': aid, 'status': 'full_source', 'pose': {}} for aid in ('a', 'b')]
        groups = [{'group_id': 'g001', 'store': '店', 'member': '人', 'requested_asset_ids': ['a', 'b']}]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); previous = self.fixture(root, rows, groups)
            with patch.object(pipeline, 'render', side_effect=[{}, AlignmentUnavailable('failed')]), \
                    patch.object(pipeline, 'group_previews'), patch.object(pipeline, 'previews'):
                _, result = pipeline.run(previous, root/'out')
            self.assertEqual(result[0]['status'], 'partial'); self.assertEqual(result[0]['excluded_asset_ids'], ['b'])

    def test_wrong_input_version_is_rejected_before_output_created(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); previous = self.fixture(root, [{'asset_id': 'a', 'status': 'rectangular'}], [])
            with self.assertRaisesRegex(AlignmentUnavailable, 'requires_full_source_v4_report'):
                pipeline.run(previous, root/'out')
            self.assertFalse((root/'out').exists())

    def test_duplicate_ids_rejected_before_output_created(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); previous = self.fixture(root, [{'asset_id': 'a'}, {'asset_id': 'a'}], [])
            with self.assertRaisesRegex(AlignmentUnavailable, 'duplicate_asset_ids'):
                pipeline.run(previous, root/'out')
            self.assertFalse((root/'out').exists())

    def test_old_experiment_cannot_be_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaisesRegex(AlignmentUnavailable, 'separate'):
                pipeline.run(root, root/'nested')


if __name__ == '__main__':
    unittest.main()

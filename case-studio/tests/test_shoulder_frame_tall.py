"""Taller frames retain source content while preserving group alignment."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from grid_crop import project
from shoulder_alignment import AlignmentUnavailable
import grid_shoulder_frame_tall as pipeline


def previous_group():
    return {'output_size': [768, 1280], 'shoulder_target_xy': [383.5, 299.5],
            'torso_target_pixels': 300}


def items():
    return [{'asset_id': 'a', 'pose': {'anchor': [499.5, 399.5], 'torso_length': 300},
             'bounds': [0, 0, 1000, 2400], 'previous_bounds': [116, 100, 884, 1380]},
            {'asset_id': 'b', 'pose': {'anchor': [999.5, 799.5], 'torso_length': 600},
             'bounds': [0, 0, 2000, 4800], 'previous_bounds': [232, 200, 1768, 2760]}]


class TallShoulderTests(unittest.TestCase):
    def test_floor_extension_stops_at_invalid_rows_and_black_bars(self):
        safe = np.ones((100, 80), bool)
        safe[:5] = False; safe[95:] = False; safe[80, 45] = False
        self.assertEqual(pipeline.extend_vertical_bounds(safe, [20, 10, 60, 60], [40, 30]),
                         [20, 5, 60, 80])

    def test_invalid_corner_outside_corridor_does_not_discard_valid_floor(self):
        safe = np.ones((100, 80), bool); safe[:, :10] = False
        self.assertEqual(pipeline.extend_vertical_bounds(safe, [20, 10, 60, 60], [40, 30]),
                         [20, 0, 60, 100])

    def test_invalid_shoulder_row_is_not_bridged(self):
        safe = np.ones((100, 80), bool); safe[30, 45] = False
        with self.assertRaisesRegex(AlignmentUnavailable, 'shoulder_corridor_not_valid'):
            pipeline.extend_vertical_bounds(safe, [20, 10, 60, 60], [40, 30])

    def test_same_group_anchor_and_torso_despite_different_source_resolutions(self):
        group = pipeline.plan_taller_group(items(), previous_group(), pipeline.TallConfig())
        for item in items():
            plan = group['plans'][item['asset_id']]; A = np.array(plan['H_corrected_to_aligned'])
            np.testing.assert_allclose(project([item['pose']['anchor']], A)[0], group['shoulder_target_xy'])
            self.assertAlmostEqual(plan['uniform_scale']*item['pose']['torso_length'], group['torso_target_pixels'])
            self.assertEqual(A[0, 0], A[1, 1]); self.assertEqual(A[0, 1], 0); self.assertEqual(A[1, 0], 0)
        self.assertAlmostEqual(group['plans']['a']['uniform_scale'], 2*group['plans']['b']['uniform_scale'])

    def test_extra_height_extends_legs_without_cutting_previous_top(self):
        group = pipeline.plan_taller_group(items(), previous_group(), pipeline.TallConfig())
        for item in items():
            plan = group['plans'][item['asset_id']]
            rect, old = plan['bounds_xyxy'], item['previous_bounds']
            self.assertLessEqual(rect[1], old[1]+1e-4)
            self.assertGreater(rect[3], old[3])
            self.assertAlmostEqual(plan['extra_below_corrected_px'], 512*item['pose']['torso_length']/300, places=4)

    def test_singleton_preserves_horizontal_composition(self):
        old = previous_group(); old['shoulder_target_xy'][0] = 269.25
        item = items()[0]
        group = pipeline.plan_taller_group([item], old, pipeline.TallConfig())
        self.assertTrue(group['singleton'])
        self.assertAlmostEqual(group['shoulder_target_xy'][0], 269.25)

    def test_width_change_preserves_relative_anchor_and_source_framing(self):
        group = pipeline.plan_taller_group(items(), previous_group(), pipeline.TallConfig(960, 2240))
        self.assertAlmostEqual(group['shoulder_target_xy'][0]+.5, 480)
        self.assertAlmostEqual(group['torso_target_pixels'], 375, places=4)
        self.assertAlmostEqual(group['plans']['a']['bounds_xyxy'][3], 1892, places=4)

    def test_shorter_aspect_is_rejected(self):
        with self.assertRaisesRegex(AlignmentUnavailable, 'must_not_be_shorter'):
            pipeline.plan_taller_group(items(), previous_group(), pipeline.TallConfig(768, 1024))

    def test_tall_config_rejects_extreme_aspect(self):
        with self.assertRaisesRegex(AlignmentUnavailable, 'portrait_aspect'):
            pipeline.TallConfig(768, 3000)

    def test_empty_previously_failed_group_needs_no_geometry(self):
        with self.assertRaisesRegex(AlignmentUnavailable, 'no_reusable_aligned_images'):
            pipeline.plan_taller_group([], {}, pipeline.TallConfig())

    def test_excessive_zoom_needs_review(self):
        item = items()[0]; item['bounds'][0] = 499
        with self.assertRaisesRegex(AlignmentUnavailable, 'excessive_zoom'):
            pipeline.plan_taller_group([item], previous_group(), pipeline.TallConfig())

    def test_unavailable_old_upper_region_is_not_silently_cut(self):
        item = items()[0]; item['bounds'][1] = 200
        with self.assertRaisesRegex(AlignmentUnavailable, 'cannot_keep_previous_upper_content'):
            pipeline.plan_taller_group([item], previous_group(), pipeline.TallConfig())

    def test_comparison_skips_and_failed_groups_do_not_load_images_or_models(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); old = root/'old'; base = root/'base'; old.mkdir(); base.mkdir()
            rows = [{'asset_id': 'a', 'status': 'skipped', 'reason': 'comparison_or_multiple_people'},
                    {'asset_id': 'b', 'status': 'needs_review', 'reason': 'pose_failed'}]
            groups = [{'group_id': 'g001', 'store': '店', 'member': '人',
                       'requested_asset_ids': ['b'], 'output_ids': []}]
            (old/'summary.json').write_text(json.dumps(rows))
            (old/'groups.json').write_text(json.dumps(groups))
            (base/'summary.json').write_text('[]')
            with patch.object(pipeline.cv2, 'imread', side_effect=AssertionError('must not load images')):
                records, output = pipeline.run(old, base, root/'out', pipeline.TallConfig())
            self.assertEqual(records[0]['status'], 'skipped')
            self.assertEqual(records[1]['reason'], 'pose_failed')
            self.assertFalse(output[0]['complete'])
            self.assertEqual(output[0]['excluded_asset_ids'], ['b'])
            self.assertEqual(output[0]['reason'], 'no_reusable_aligned_images')
            self.assertFalse((root/'out'/'a'/'aligned.png').exists())

    def test_duplicate_ids_rejected_before_output_directory_created(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); old = root/'old'; base = root/'base'; old.mkdir(); base.mkdir()
            (old/'summary.json').write_text(json.dumps([{'asset_id': 'a'}, {'asset_id': 'a'}]))
            (old/'groups.json').write_text('[]'); (base/'summary.json').write_text('[]')
            with self.assertRaisesRegex(AlignmentUnavailable, 'duplicate_asset_ids'):
                pipeline.run(old, base, root/'out', pipeline.TallConfig())
            self.assertFalse((root/'out').exists())

    def test_old_experiment_cannot_be_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaisesRegex(AlignmentUnavailable, 'separate'):
                pipeline.run(root, root/'base', root/'nested', pipeline.TallConfig())


if __name__ == '__main__':
    unittest.main()

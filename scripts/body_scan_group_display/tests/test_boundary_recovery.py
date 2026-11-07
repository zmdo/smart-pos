"""A small estimated-box error may be remeasured, never silently tolerated."""
import copy
import unittest
from unittest.mock import Mock, patch

import numpy as np

from scripts.body_scan_group_display.planning import PlanUnavailable, plan_person
from scripts.body_scan_group_display.recovery import plan_with_boundary_review


def fixture():
    rows = []
    for index, (top, bottom, head) in enumerate([
        (-412.16, 1379.84, -385.28), (-412.16, 1356.84, -323.71),
        (-412.16, 1338.84, -359.63), (-412.16, 1379.84, -358.40),
        (-383.16, 1287.84, -299.61), (-391.16, 1299.84, -340.43),
    ]):
        rows.append({'asset_id': f'p{index}', 'normalized_bounds': [-384, top, 384, bottom],
                     'required_core': [-163, -8, 163, 524],
                     'visible_bounds_normalized': [-220, head, 220, bottom],
                     'visibility': {'head': 'complete', 'lower_extent': 'feet_cut',
                                    'visible_bbox': [.17, .015, .83, 1]},
                     'approved_content_rectangle': [0, 0, 768, 1792],
                     'approved_image': '/not-read.png', 'approved_image_sha256': 'verified',
                     'H_aligned_to_normalized': [[1, 0, -383.5], [0, 1, -411.66], [0, 0, 1]]})
    return rows


def segmented(top=33, bottom=1792, score=.976):
    mask = np.zeros((1792, 768), bool)
    mask[top:bottom, 135:630] = True
    return mask, {'selected_candidate': 0, 'candidates': [
        {'candidate': 0, 'score': score, 'prompt_coverage': 1., 'error': None}]}


class BoundaryRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.rows = fixture()
        self.segmenter = Mock(return_value=segmented())
        image = patch('scripts.body_scan_group_display.recovery.effective_image',
                      return_value=np.zeros((1792, 768, 3), np.uint8))
        digest = patch('scripts.body_scan_group_display.recovery.digest', return_value='verified')
        image.start(); digest.start()
        self.addCleanup(image.stop); self.addCleanup(digest.stop)

    def run_plan(self):
        return plan_with_boundary_review(self.rows, segmenter=self.segmenter)

    def test_six_photo_regression_preserves_shared_geometry(self):
        before = copy.deepcopy(self.rows)
        with self.assertRaises(PlanUnavailable):
            plan_person(self.rows)
        plan = self.run_plan()
        self.assertEqual(plan['output_size'], [768, 1792])
        np.testing.assert_allclose(plan['crop_rectangle'], [-384, -383.16, 384, 1287.84])
        self.assertAlmostEqual(plan['vertical_stretch'], 1.0724117295032916)
        self.assertEqual(plan['boundary_recheck']['asset_ids'], ['p0'])
        self.assertEqual(self.segmenter.call_count, 1)
        self.assertFalse(any(r['head'] for r in plan['originally_complete_parts_cropped']))
        for old, new in zip(before, self.rows):
            for key in ('visibility', 'normalized_bounds', 'required_core', 'H_aligned_to_normalized'):
                self.assertEqual(old[key], new[key])
        self.assertEqual(before[1:], self.rows[1:])

    def test_normal_plan_unchanged_and_no_segmentation(self):
        self.rows[0]['visible_bounds_normalized'][1] = -376
        before = copy.deepcopy(self.rows)
        self.assertEqual(plan_person(self.rows), self.run_plan())
        self.assertEqual(before, self.rows)
        self.segmenter.assert_not_called()

    def test_large_head_conflict_keeps_review(self):
        self.rows[0]['visible_bounds_normalized'][1] = -400
        with self.assertRaises(PlanUnavailable):
            self.run_plan()
        self.segmenter.assert_not_called()

    def test_torso_conflict_never_uses_mask_to_bypass(self):
        self.rows[0]['required_core'][0] = -385
        with self.assertRaises(PlanUnavailable):
            self.run_plan()
        self.segmenter.assert_not_called()

    def test_real_head_cut_insufficient_margin_or_missing_mask_stays_rejected(self):
        for result in (segmented(top=28), segmented(top=30), segmented(top=50),
                       segmented(score=.89), (None, {'error': 'unavailable'})):
            with self.subTest(result=result[1]):
                self.rows = fixture()
                original = copy.deepcopy(self.rows[0]['visible_bounds_normalized'])
                self.segmenter.return_value = result
                with self.assertRaises(PlanUnavailable):
                    self.run_plan()
                self.assertEqual(original, self.rows[0]['visible_bounds_normalized'])
                self.assertEqual(self.rows[0]['common_frame_boundary_review']['status'], 'rejected')

    def test_isolated_top_pixel_is_not_ignored(self):
        mask, trace = segmented()
        mask[20, 200] = True
        self.segmenter.return_value = mask, trace
        with self.assertRaises(PlanUnavailable):
            self.run_plan()

    def test_failed_second_recheck_cannot_commit_first(self):
        self.rows[1]['visible_bounds_normalized'][1] = -385
        self.segmenter.side_effect = [segmented(), segmented(top=20)]
        before = [r['visible_bounds_normalized'][:] for r in self.rows]
        with self.assertRaises(PlanUnavailable):
            self.run_plan()
        self.assertEqual(before, [r['visible_bounds_normalized'] for r in self.rows])

    def test_complete_feet_also_require_positive_margin(self):
        self.rows = self.rows[:1]
        row = self.rows[0]
        row['visibility']['lower_extent'] = 'feet_complete'
        row['normalized_bounds'] = [-384, -412.16, 384, 1287.84]
        row['visible_bounds_normalized'] = [-220, -300, 220, 1290]
        self.segmenter.return_value = segmented(top=120, bottom=1697)
        plan = self.run_plan()
        self.assertFalse(plan['originally_complete_parts_cropped'][0]['feet'])
        self.assertEqual(row['common_frame_boundary_review']['edges'], ['feet'])

    def test_changed_pixels_cannot_reuse_evidence(self):
        with patch('scripts.body_scan_group_display.recovery.digest', return_value='changed'):
            with self.assertRaises(PlanUnavailable):
                self.run_plan()
        self.segmenter.assert_not_called()


if __name__ == '__main__':
    unittest.main()

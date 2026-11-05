"""Geometry and provenance regressions; run in the remote processing environment."""
import tempfile
import unittest
import json
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np

from scripts.body_scan_group_display.inputs import digest
from scripts.body_scan_group_display.pipeline import render, reuse_audit, run
from scripts.body_scan_group_display.verify import verify
from scripts.body_scan_group_display.planning import Config, PlanUnavailable, contains, intersection, plan_group
from scripts.body_scan_group_display.visibility import profile_name, validate
from scripts.body_scan_group_display.audit import boundary_guards
from scripts.body_scan_group_display.boundary import BoundarySegmenter


def item(bounds=(-384, -412, 384, 1380), head='complete', lower='feet_cut'):
    return {'asset_id': 'test', 'normalized_bounds': list(bounds), 'required_core': [-150, -8, 150, 490],
            'visible_bounds_normalized': [-220, -350, 220, 1330],
            'visibility': {'head': head, 'lower_extent': lower}}


class GroupGeometryTests(unittest.TestCase):
    def test_common_rectangle_is_shoulder_relative_intersection(self):
        self.assertEqual(intersection([[-100, -80, 200, 500], [-200, -50, 100, 600]]).tolist(),
                         [-100, -50, 100, 500])

    def test_mild_vertical_only_adjustment(self):
        plan = plan_group([item()], 'full_body')
        self.assertAlmostEqual(plan['vertical_stretch'], 1920/1792)
        self.assertEqual(plan['crop_steps'], [])
        self.assertAlmostEqual(plan['H_normalized_to_uniform'][0][0], plan['H_normalized_to_uniform'][1][1])

    def test_wide_frame_is_trimmed_before_stretch_limit(self):
        plan = plan_group([item((-490, -400, 490, 1300))], 'full_body')
        self.assertAlmostEqual(plan['vertical_stretch'], 1.1)
        self.assertLess(plan['crop_rectangle'][2]-plan['crop_rectangle'][0], 1000)
        self.assertTrue(contains(plan['crop_rectangle'], plan['required_rectangle']))

    def test_tall_frame_does_not_fatten_subject(self):
        r = item((-384, -500, 384, 1500)); r['visible_bounds_normalized'][1] = -300
        plan = plan_group([r], 'feet_cropped')
        self.assertAlmostEqual(plan['vertical_stretch'], 1)
        self.assertAlmostEqual(plan['crop_rectangle'][3]-plan['crop_rectangle'][1], 1792)

    def test_group_crop_protects_confirmed_head_and_feet(self):
        a = item(lower='feet_complete')
        b = item((-384, -200, 384, 1380), lower='feet_complete')
        with self.assertRaisesRegex(PlanUnavailable, 'common_frame_would_cut'):
            plan_group([a, b], 'full_body')

    def test_does_not_force_aspect_by_cutting_confirmed_feet(self):
        r = item((-200, -400, 200, 1300), lower='feet_complete')
        r['visible_bounds_normalized'] = [-180, -350, 180, 1290]
        with self.assertRaisesRegex(PlanUnavailable, 'target_aspect_would_cut_required_body'):
            plan_group([r], 'full_body', Config(max_crop_loss=.6))

    def test_excessive_additional_crop_stops(self):
        with self.assertRaisesRegex(PlanUnavailable, 'excessive_group_crop'):
            plan_group([item()], 'upper_body')

    def test_crop_steps_are_small_and_terminate(self):
        plan = plan_group([item((-490, -400, 490, 1300))], 'full_body')
        previous = np.asarray(plan['common_rectangle'])
        for step in map(np.asarray, plan['crop_steps']):
            self.assertTrue(contains(previous, step))
            self.assertTrue(((step[2:]-step[:2])/(previous[2:]-previous[:2]) >= .98-1e-9).all())
            previous = step
        np.testing.assert_allclose(previous, plan['crop_rectangle'])

    def test_crop_iteration_cap_is_enforced(self):
        with self.assertRaisesRegex(PlanUnavailable, 'crop_iteration_limit'):
            plan_group([item((-490, -400, 490, 1300))], 'full_body', Config(max_steps=1))

    def test_zero_extra_stretch_can_be_requested(self):
        plan = plan_group([item()], 'full_body', Config(max_stretch=1))
        self.assertAlmostEqual(plan['vertical_stretch'], 1)

    def test_same_plan_is_independent_of_group_order(self):
        a, b = item(), item((-370, -400, 350, 1300))
        one = plan_group([a, b], 'feet_cropped'); two = plan_group([b, a], 'feet_cropped')
        self.assertEqual(one['crop_rectangle'], two['crop_rectangle'])
        self.assertEqual(one['H_normalized_to_display'], two['H_normalized_to_display'])

    def test_missing_head_and_shoe_is_not_a_torso_only_photo(self):
        self.assertEqual(profile_name({'head': 'cut', 'lower_extent': 'feet_cut'}), 'head_feet_cropped')
        self.assertEqual(profile_name({'head': 'cut', 'lower_extent': 'calves_cut'}), 'head_legs_cropped')
        self.assertEqual(profile_name({'head': 'cut', 'lower_extent': 'thighs_cut'}), 'torso')

    def test_invalid_model_output_is_not_full_body(self):
        good = {'head': 'complete', 'lower_extent': 'feet_complete', 'confidence': .95,
                'shoulders_visible': True, 'hips_visible': True, 'visible_bbox': [.1, 0, .9, 1]}
        self.assertEqual(profile_name(validate(good)), 'full_body')
        for change in ({'head': 'uncertain'}, {'lower_extent': 'unknown'}, {'confidence': float('nan')},
                       {'hips_visible': False}, {'visible_bbox': [0, 1, 1, 0]}):
            with self.assertRaises(ValueError):
                validate({**good, **change})

    def test_invalid_limits_and_empty_intersection_stop(self):
        for change in ({'max_stretch': .99}, {'max_stretch': 1.2}, {'max_crop_loss': .7}, {'crop_step': 0}):
            with self.assertRaises(ValueError):
                Config(**change)
        with self.assertRaises(ValueError):
            intersection([[0, 0, 10, 10], [11, 0, 15, 10]])


class SourceRenderingTests(unittest.TestCase):
    def setup_fixture(self, root):
        source = np.zeros((640, 256, 3), np.uint8)
        source[:, :, 0] = np.arange(256)[None, :]
        source[:, :, 1] = (np.arange(640)[:, None] % 256)
        original = root/'source.png'; cv2.imwrite(str(original), source)
        approved = root/'input'/'test'; approved.mkdir(parents=True)
        cv2.imwrite(str(approved/'aligned.png'), source)
        cv2.imwrite(str(approved/'content_mask.png'), np.full((640, 256), 255, np.uint8))
        N = np.array([[1., 0., -127.5], [0., 1., -99.5], [0., 0., 1.]])
        row = item((-128, -100, 128, 540), head='cut')
        row.update({'source': str(original), 'source_sha256': digest(original), 'input_directory': str(root/'input'),
                    'approved_image': str(approved/'aligned.png'), 'H_source_to_normalized': N.tolist(),
                    'H_aligned_to_normalized': N.tolist(), 'required_core': [-40, -8, 40, 240],
                    'upstream_report': {'frame': {'source_content_bounds_xyxy': [0, 0, 256, 640]}}})
        profile = {'test': {'height': 1920, 'label': 'test', 'shoulder_y': .16}}
        plan = plan_group([row], 'test', Config(width=256), profile)
        return row, plan, source

    def test_render_uses_source_once_and_preserves_baseline(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); row, plan, source = self.setup_fixture(root)
            output = render(row, plan, root/'out')
            np.testing.assert_array_equal(cv2.imread(str(root/'out/display.png')), source)
            np.testing.assert_array_equal(output['H_source_to_display'], np.eye(3))
            self.assertEqual(digest(root/'out/baseline.png'), digest(row['approved_image']))

    def test_changed_source_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); row, plan, source = self.setup_fixture(root)
            source[0, 0] = 255; cv2.imwrite(row['source'], source)
            with self.assertRaisesRegex(ValueError, 'original_source_changed'):
                render(row, plan, root/'out')

    def test_missing_pixels_are_never_filled_into_display(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); row, plan, _ = self.setup_fixture(root)
            mask = np.full((640, 256), 255, np.uint8); mask[100:110, 100:110] = 0
            cv2.imwrite(str(root/'input/test/content_mask.png'), mask)
            with self.assertRaisesRegex(ValueError, 'outside_approved_photo'):
                render(row, plan, root/'out')

    def test_visibility_audit_cannot_be_used_for_another_source_run(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); (root/'sources.json').write_text('[]')
            with patch('scripts.body_scan_group_display.pipeline.load_inputs', return_value=([], [], [{'changed': True}])):
                with self.assertRaisesRegex(ValueError, 'input_sources_changed'):
                    reuse_audit([], root)

    def test_all_upstream_excluded_produces_valid_empty_report(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); audit = root/'audit'; audit.mkdir()
            (audit/'items.json').write_text('[]')
            excluded = [{'asset_id': 'skipped', 'status': 'upstream_excluded'}]
            with patch('scripts.body_scan_group_display.pipeline.reuse_audit', return_value=([], excluded, [])):
                run([], root/'out', audit=audit)
            result = verify(root/'out')
            self.assertTrue(result['passed'])
            self.assertEqual(result['displayed_asset_ids'], [])
            self.assertEqual(json.loads((root/'out/upstream-excluded.json').read_text()), excluded)


class BoundaryReviewTests(unittest.TestCase):
    def guarded(self, contact=True, failure=False):
        from unittest.mock import Mock
        value = {'head': 'complete', 'lower_extent': 'feet_complete', 'visible_bbox': [.1, .03, .9, 1],
                 'confidence': .95, 'shoulders_visible': True, 'hips_visible': True}
        row = {'asset_id': 'test', 'status': 'classified', 'visibility': value.copy()}
        mask = np.zeros((100, 100), bool); mask[10:(100 if contact else 90), 25:75] = True
        sam = Mock(return_value=(mask, {'strategy': 'positive_shoulder_hip_points'}))
        evidence = Mock()
        if failure:
            evidence.inspect_edges.side_effect = ValueError('uncertain')
        else:
            evidence.inspect_edges.return_value = (validate(value), {'result': value, 'cached': True})
        with patch('scripts.body_scan_group_display.audit.BoundarySegmenter', return_value=sam), \
                patch('scripts.body_scan_group_display.audit.effective_image', return_value=np.zeros((100, 100, 3), np.uint8)), \
                patch('scripts.body_scan_group_display.audit.visible_bounds', return_value=[0, 0, 1, 1]):
            boundary_guards([row], evidence, workers=1)
        return row, evidence

    def test_prompted_contact_is_distinct_from_missing_body_parts(self):
        row, evidence = self.guarded()
        evidence.inspect_edges.assert_called_once()
        self.assertEqual(row['visibility']['lower_extent'], 'feet_touching_border')
        self.assertEqual(row['profile'], 'feet_cropped')
        self.assertEqual(row['boundary_guard']['edge_evidence']['result']['lower_extent'], 'feet_complete')
        self.assertEqual(row['boundary_guard']['strategy'], 'sam_contact_then_vlm_edge_review')

    def test_no_boundary_contact_needs_no_additional_call(self):
        row, evidence = self.guarded(contact=False)
        evidence.inspect_edges.assert_not_called()
        self.assertEqual(row['status'], 'classified')

    def test_uncertain_edge_review_stops_the_image(self):
        row, _ = self.guarded(failure=True)
        self.assertEqual(row['status'], 'needs_review')
        self.assertIn('visibility_edge_review_unavailable', row['reason'])


class BoundaryMaskSelectionTests(unittest.TestCase):
    def select(self, omit_prompt=False):
        from unittest.mock import Mock
        masks = np.zeros((2, 100, 100), bool)
        masks[0, 10:90, 10:90] = True
        masks[1, 10:90, 30:70] = True
        masks[0, 10:40, 10:20] = False
        masks[1, 10:30, 30:40] = False
        if omit_prompt:
            masks[1, 30, 40] = False
        segmenter = BoundarySegmenter()
        segmenter.model = Mock()
        segmenter.model.predict.return_value = (masks, np.array([.85, .94]), None)
        points = np.zeros((17, 2)); points[5] = [40, 30]; points[11] = [60, 65]
        row = {'upstream_report': {'pose': {'selected_pairs': [[5, 11]]}},
               'keypoints_normalized': points.tolist(), 'H_aligned_to_normalized': np.eye(3).tolist(),
               'approved_content_rectangle': [0, 0, 100, 100]}
        return segmenter(np.zeros((100, 100, 3), np.uint8), [20, 5, 80, 95], row)

    def test_prefers_confident_subject_to_largest_area(self):
        mask, trace = self.select()
        self.assertEqual(trace['selected_candidate'], 1)
        self.assertEqual(int(mask.sum()), 3000)

    def test_rejects_mask_missing_required_shoulder_hip_point(self):
        _, trace = self.select(omit_prompt=True)
        self.assertEqual(trace['selected_candidate'], 0)


if __name__ == '__main__':
    unittest.main()

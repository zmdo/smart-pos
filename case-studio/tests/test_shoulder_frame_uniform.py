"""Global person scale, source fidelity, padding and independent-run contracts."""
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
import grid_shoulder_frame_uniform as pipeline


class UniformShoulderTests(unittest.TestCase):
    def test_different_people_and_source_scales_share_one_target(self):
        config = pipeline.UniformConfig()
        for length, anchor in [(200, [300, 400]), (800, [900, 100]), (513, [600, 900])]:
            plan = pipeline.uniform_plan({'anchor': anchor, 'torso_length': length}, config)
            A = np.array(plan['H_corrected_to_aligned'])
            output = project([anchor, [anchor[0], anchor[1]+length]], A)
            np.testing.assert_allclose(output[0], [383.5, 411.66], atol=1e-9)
            self.assertAlmostEqual(np.linalg.norm(output[1]-output[0])/1792, .27)

    def test_original_body_tilt_and_aspect_are_preserved(self):
        pose = {'anchor': [300, 400], 'torso_length': 300}
        A = np.array(pipeline.uniform_plan(pose, pipeline.UniformConfig())['H_corrected_to_aligned'])
        points = np.array([[250, 390], [350, 410], [270, 690]])
        transformed = project(points, A)
        np.testing.assert_allclose(transformed[1]-transformed[0], (points[1]-points[0])*A[0, 0])
        self.assertEqual(A[0, 0], A[1, 1]); self.assertEqual(A[0, 1], 0); self.assertEqual(A[1, 0], 0)

    def test_head_and_subject_box_do_not_control_person_size(self):
        pose = {'anchor': [300, 400], 'torso_length': 300}
        before = pipeline.uniform_plan(pose, pipeline.UniformConfig())
        pose.update(head=[999, -999], subject_box=[0, 0, 10000, 10000], shoulder_width=1)
        self.assertEqual(before, pipeline.uniform_plan(pose, pipeline.UniformConfig()))

    def test_output_resolution_changes_do_not_change_relative_person_size(self):
        pose = {'anchor': [300, 400], 'torso_length': 300}
        first = pipeline.uniform_plan(pose, pipeline.UniformConfig())
        second = pipeline.uniform_plan(pose, pipeline.UniformConfig(960, 2240))
        self.assertAlmostEqual(second['uniform_scale']/first['uniform_scale'], 1.25)
        np.testing.assert_allclose(first['bounds_xyxy'], second['bounds_xyxy'])

    def test_short_source_changes_padding_not_person_scale(self):
        pose = {'anchor': [300, 400], 'torso_length': 300}
        plan = pipeline.uniform_plan(pose, pipeline.UniformConfig())
        A = np.array(plan['H_corrected_to_aligned'])
        small = pipeline.content_rectangle([100, 250, 500, 800], A, 768, 1792)
        large = pipeline.content_rectangle([0, 0, 1000, 1800], A, 768, 1792)
        self.assertLess((small[2]-small[0])*(small[3]-small[1]), (large[2]-large[0])*(large[3]-large[1]))
        self.assertAlmostEqual(plan['uniform_scale'], 483.84/300)

    def test_fractional_scale_keeps_all_copied_pixel_centers_in_source_window(self):
        A = np.array([[.73, 0, -13.17], [0, .73, 28.23], [0, 0, 1]])
        window = [30, 40, 300, 600]
        x1, y1, x2, y2 = pipeline.content_rectangle(window, A, 768, 1792)
        points = project([[x1, y1], [x2-1, y2-1]], np.linalg.inv(A))
        self.assertTrue((points[0] >= window[:2]).all())
        self.assertTrue((points[1] <= np.array(window[2:])-1).all())

    def test_rectangular_padding_preserves_real_pixels_and_marks_missing_area(self):
        config = pipeline.UniformConfig(64, 128)
        image = np.arange(128*64*3, dtype=np.uint8).reshape(128, 64, 3)
        image = np.maximum(image, 30)
        valid = np.full((128, 64), 255, np.uint8)
        output, used = pipeline.compose(image, valid, np.eye(3), [8, 20, 56, 110], config)
        np.testing.assert_array_equal(output[20:110, 8:56], image[20:110, 8:56])
        self.assertTrue((output[used == 0] == config.background_rgb[::-1]).all())
        self.assertEqual(np.count_nonzero(used), 48*90)
        self.assertEqual(set(np.unique(used)), {0, 255})

    def test_invalid_source_pixel_is_not_pasted_as_real_content(self):
        image = np.full((128, 64, 3), 90, np.uint8); valid = np.full((128, 64), 255, np.uint8)
        valid[50, 30] = 0
        with self.assertRaisesRegex(AlignmentUnavailable, 'invalid_source_pixels'):
            pipeline.compose(image, valid, np.eye(3), [8, 20, 56, 110], pipeline.UniformConfig(64, 128))

    def test_off_canvas_source_is_rejected(self):
        with self.assertRaisesRegex(AlignmentUnavailable, 'outside_frame'):
            pipeline.content_rectangle([1000, 1000, 1200, 1500], np.eye(3), 768, 900)

    def test_invalid_saved_pose_is_rejected(self):
        for length in (0, -1, float('nan'), float('inf')):
            with self.assertRaisesRegex(AlignmentUnavailable, 'invalid_saved_pose'):
                pipeline.uniform_plan({'anchor': [10, 20], 'torso_length': length}, pipeline.UniformConfig())

    def test_invalid_settings_are_rejected(self):
        for kwargs in ({'torso_fraction': float('nan')}, {'torso_fraction': .9},
                       {'shoulder_y': .7}, {'background_rgb': (256, 0, 0)}):
            with self.assertRaises(AlignmentUnavailable):
                pipeline.UniformConfig(**kwargs)

    def test_skips_and_previous_failures_do_not_read_images(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); poses = root/'poses'; base = root/'base'; poses.mkdir(); base.mkdir()
            rows = [{'asset_id': 'a', 'status': 'skipped', 'reason': 'comparison_or_multiple_people'},
                    {'asset_id': 'b', 'status': 'needs_review', 'reason': 'pose_failed'}]
            (poses/'summary.json').write_text(json.dumps(rows))
            (poses/'groups.json').write_text(json.dumps([{'group_id': 'g001', 'store': '店', 'member': '人', 'requested_asset_ids': ['b']}]))
            (base/'summary.json').write_text('[]')
            with patch.object(pipeline.cv2, 'imread', side_effect=AssertionError('must not read images')):
                records, groups = pipeline.run(poses, base, root/'previous', root/'out', pipeline.UniformConfig())
            self.assertEqual(records[0]['status'], 'skipped'); self.assertEqual(records[1]['reason'], 'pose_failed')
            self.assertEqual(groups[0]['excluded_asset_ids'], ['b']); self.assertFalse(groups[0]['complete'])

    def test_partial_group_does_not_change_remaining_image_scale(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); poses = root/'poses'; base = root/'base'; poses.mkdir(); base.mkdir()
            I = np.eye(3).tolist()
            rows = [{'asset_id': a, 'status': 'aligned', 'pose_localization': {'pose': {}},
                     'frame': {'H_source_to_aligned': I, 'H_corrected_to_aligned': I}} for a in ('a', 'b')]
            (poses/'summary.json').write_text(json.dumps(rows))
            (poses/'groups.json').write_text(json.dumps([{'group_id': 'g001', 'store': '店', 'member': '人', 'requested_asset_ids': ['a', 'b']}]))
            (base/'summary.json').write_text(json.dumps([{'asset_id': a, 'H_source_to_output': I} for a in ('a', 'b')]))
            with patch.object(pipeline, 'render', side_effect=[{}, AlignmentUnavailable('failed')]), \
                    patch.object(pipeline, 'group_previews'), patch.object(pipeline, 'previews'):
                records, groups = pipeline.run(poses, base, root/'previous', root/'out', pipeline.UniformConfig())
            self.assertEqual(groups[0]['status'], 'partial'); self.assertFalse(groups[0]['singleton'])
            self.assertEqual(groups[0]['excluded_asset_ids'], ['b'])
            self.assertAlmostEqual(groups[0]['torso_target_pixels'], 483.84)

    def test_duplicate_ids_rejected_before_creating_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); poses = root/'poses'; base = root/'base'; poses.mkdir(); base.mkdir()
            (poses/'summary.json').write_text(json.dumps([{'asset_id': 'a'}, {'asset_id': 'a'}]))
            (poses/'groups.json').write_text('[]'); (base/'summary.json').write_text('[]')
            with self.assertRaisesRegex(AlignmentUnavailable, 'duplicate_asset_ids'):
                pipeline.run(poses, base, root/'previous', root/'out', pipeline.UniformConfig())
            self.assertFalse((root/'out').exists())

    def test_prior_experiment_cannot_be_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for protected in ('poses', 'base', 'previous'):
                with self.assertRaisesRegex(AlignmentUnavailable, 'separate'):
                    pipeline.run(root/'poses', root/'base', root/'previous', root/protected/'nested', pipeline.UniformConfig())


if __name__ == '__main__':
    unittest.main()

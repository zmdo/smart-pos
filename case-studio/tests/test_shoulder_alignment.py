"""Group scale/anchor, pose reliability, and independent pipeline contracts."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from grid_crop import project
from shoulder_alignment import AlignmentUnavailable, GroupConfig, group_plan, landmarks, member_key
from shoulder_pose import ShoulderPose
from subject_localization import expanded_roi
import grid_shoulder_frame as pipeline


def pose_points():
    p = np.zeros((17, 3), float)
    p[5] = [240, 300, .99]; p[6] = [360, 300, .98]
    p[11] = [260, 600, .99]; p[12] = [340, 600, .98]
    return p


class ShoulderAlignmentTests(unittest.TestCase):
    def test_store_and_name_grouping_does_not_merge_different_stores(self):
        self.assertEqual(member_key({'store': ' 店一 ', 'member': ' 张三 '}), ('店一', '张三'))
        self.assertNotEqual(member_key({'store': '店一', 'member': '张三'}),
                            member_key({'store': '店二', 'member': '张三'}))
        with self.assertRaises(AlignmentUnavailable):
            member_key({'member': '张三'})

    def test_no_head_landmarks_or_hair_height_used_as_scale_reference(self):
        p = pose_points()
        a = landmarks(p, np.eye(3), [180, 100, 420, 950], 'front')
        p[:5] = [9999, 9999, 0]  # absent face and arbitrary hair/head extent
        b = landmarks(p, np.eye(3), [180, -100, 420, 950], 'front')
        self.assertEqual(a['anchor'], b['anchor'])
        self.assertEqual(a['torso_length'], b['torso_length'])

    def test_profile_shoulder_width_does_not_control_scale(self):
        p = pose_points()
        front = landmarks(p, np.eye(3), [180, 100, 420, 950], 'front')
        p[6, 0] = p[5, 0]+5; p[6, 2] = .2
        side = landmarks(p, np.eye(3), [180, 100, 420, 950], 'side_left')
        self.assertEqual(side['selected_pairs'], [[5, 11]])
        self.assertAlmostEqual(side['torso_length'], front['torso_length'])

    def test_low_confidence_hidden_shoulders_are_rejected(self):
        p = pose_points(); p[5:7, 2] = .2
        with self.assertRaises(AlignmentUnavailable):
            landmarks(p, np.eye(3), [180, 100, 420, 950], 'front')

    def test_group_normalizes_scale_and_anchor_without_rotation(self):
        items = [{'asset_id': 'a', 'bounds': [0, 0, 800, 1500], 'pose': {'anchor': [400, 400], 'torso_length': 350}},
                 {'asset_id': 'b', 'bounds': [0, 0, 1600, 3000], 'pose': {'anchor': [800, 800], 'torso_length': 700}}]
        result = group_plan(items, GroupConfig())
        for item in items:
            p = result['plans'][item['asset_id']]; A = np.array(p['H_corrected_to_aligned'])
            np.testing.assert_allclose(project([item['pose']['anchor']], A)[0], result['shoulder_target_xy'])
            self.assertAlmostEqual(p['uniform_scale']*item['pose']['torso_length'], result['torso_target_pixels'])
            self.assertEqual(A[0, 1], 0); self.assertEqual(A[1, 0], 0)
            self.assertEqual(A[0, 0], A[1, 1])
        self.assertAlmostEqual(result['plans']['a']['uniform_scale'], 2*result['plans']['b']['uniform_scale'])

    def test_real_high_low_shoulders_are_not_artificially_leveled(self):
        item = {'asset_id': 'a', 'bounds': [0, 0, 800, 1500], 'pose': {'anchor': [400, 400], 'torso_length': 350}}
        plan = group_plan([item], GroupConfig())['plans']['a']
        transformed = project([[300, 390], [500, 410]], np.array(plan['H_corrected_to_aligned']))
        self.assertAlmostEqual(transformed[1, 1]-transformed[0, 1], 20*plan['uniform_scale'])

    def test_group_adjusts_common_height_instead_of_clamping_individuals(self):
        items = [{'asset_id': 'a', 'bounds': [0, 0, 800, 1500], 'pose': {'anchor': [400, 100], 'torso_length': 350}},
                 {'asset_id': 'b', 'bounds': [0, 0, 800, 1500], 'pose': {'anchor': [400, 400], 'torso_length': 350}}]
        result = group_plan(items, GroupConfig())
        self.assertLess(result['shoulder_target_xy'][1], 1280*.22)
        for item in items:
            rect = result['plans'][item['asset_id']]['bounds_xyxy']
            self.assertGreaterEqual(rect[0], 0); self.assertGreaterEqual(rect[1], 0)
            self.assertLessEqual(rect[2], 800); self.assertLessEqual(rect[3], 1500)

    def test_extreme_zoom_requires_review(self):
        item = {'asset_id': 'a', 'bounds': [0, 0, 800, 1500], 'pose': {'anchor': [4, 400], 'torso_length': 350}}
        with self.assertRaisesRegex(AlignmentUnavailable, 'excessive_group_zoom'):
            group_plan([item], GroupConfig())

    def test_single_image_keeps_previous_standard_frame_rule(self):
        row = {'asset_id': 'a', 'crop': {'bounds_xyxy': [0, 0, 800, 1500]},
               'subject_box': [180, 100, 600, 1450], 'H_source_to_output': np.eye(3).tolist()}
        pose = {'anchor': [400, 400], 'torso_length': 350}
        result = pipeline.single_plan(row, pose, GroupConfig())
        rect, A, _ = pipeline.select_frame(row['crop']['bounds_xyxy'], row['subject_box'], np.eye(3), pipeline.FrameConfig())
        self.assertEqual(result['plans']['a']['bounds_xyxy'], rect)
        np.testing.assert_allclose(result['plans']['a']['H_corrected_to_aligned'], A)
        self.assertEqual(result['mode'], 'single_standard_frame')

    def test_pose_contexts_roi_mapping_and_cache(self):
        image = np.full((1000, 600, 3), 100, np.uint8); box = [180, 100, 420, 950]
        roi = expanded_roi(box, image.shape, .20); calls = []
        def detect(im, size):
            index = len(calls); calls.append(size)
            p = pose_points(); b = np.array(box, float)
            if index % 2:
                p[:, :2] -= roi[:2]; b -= [*roi[:2], *roi[:2]]
            return [{'box': b.tolist(), 'confidence': .9, 'keypoints': p.tolist()}]
        with tempfile.TemporaryDirectory() as tmp:
            detector = ShoulderPose(cache_dir=tmp, detector=detect)
            first = detector.locate(image, box, np.eye(3), 'front')
            self.assertEqual(first['new_inferences'], 2)
            self.assertEqual(first['pose']['anchor'], [300., 300.])
            cached = detector.locate(image, box, np.eye(3), 'front')
            self.assertTrue(cached['cached']); self.assertEqual(cached['new_inferences'], 0)
            self.assertEqual(len(calls), 2)
            # Changed source pixels invalidate a cache hit.
            image[0, 0] = 101
            self.assertFalse(detector.locate(image, box, np.eye(3), 'front')['cached'])
            self.assertEqual(len(calls), 4)

    def test_disagreeing_high_confidence_contexts_do_not_silently_pass(self):
        image = np.zeros((1000, 600, 3), np.uint8); box = [180, 100, 420, 950]
        roi = expanded_roi(box, image.shape, .20); calls = []
        def detect(im, size):
            index = len(calls); calls.append(size)
            p = pose_points(); p[[5, 6, 11, 12], 1] += [0, 100, -100, 200][index]
            b = np.array(box, float)
            if index in (1, 2):
                p[:, :2] -= roi[:2]; b -= [*roi[:2], *roi[:2]]
            return [{'box': b.tolist(), 'confidence': .99, 'keypoints': p.tolist()}]
        with self.assertRaisesRegex(AlignmentUnavailable, 'not_reliable_across_contexts'):
            ShoulderPose(detector=detect).locate(image, box, np.eye(3), 'front')
        self.assertEqual(len(calls), 4)

    def test_comparison_skips_before_loading_pose_model_or_images(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); baseline = root/'baseline'; baseline.mkdir()
            c = {'phase': 'both', 'people': 2, 'kind': 'body_scan', 'background': 'grid_board'}
            (baseline/'summary.json').write_text(json.dumps([{'asset_id': 'a', 'classification': c}]))
            job = root/'job.json'; job.write_text(json.dumps({'assets': [{'id': 'a', 'class': c}]}))
            with patch.object(pipeline, 'ShoulderPose', side_effect=AssertionError('must not load model')):
                with patch.object(cv2, 'imread', side_effect=AssertionError('must not read image')):
                    rows, groups = pipeline.run(baseline, job, root/'out', GroupConfig(), None, None)
            self.assertEqual(rows[0]['status'], 'skipped'); self.assertEqual(groups, [])

    def test_old_experiment_cannot_be_used_as_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaisesRegex(AlignmentUnavailable, 'separate'):
                pipeline.run(root, root/'job.json', root/'nested', GroupConfig(), None, None)

    def test_unreliable_group_image_is_explicitly_excluded(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); baseline = root/'baseline'; baseline.mkdir()
            c = {'people': 1, 'kind': 'body_scan', 'background': 'grid_board', 'view': 'front'}
            assets, old = [], []
            for aid in ('a', 'b'):
                assets.append({'id': aid, 'class': c, 'store': '店一', 'member': '张三', 'path': aid+'.jpg'})
                old.append({'asset_id': aid, 'classification': c, 'status': 'corrected',
                            'crop': {'status': 'cropped', 'bounds_xyxy': [0, 0, 800, 1500]},
                            'subject_box': [180, 100, 600, 1450], 'H_source_to_output': np.eye(3).tolist(),
                            'source': str(root/'input'/(aid+'.jpg'))})
            (baseline/'summary.json').write_text(json.dumps(old))
            job = root/'job.json'; job.write_text(json.dumps({'assets': assets}))
            pose = {'anchor': [400, 400], 'torso_length': 350}
            with patch.object(pipeline, 'ShoulderPose') as detector, patch.object(cv2, 'imread', return_value=np.zeros((1500, 800, 3), np.uint8)), \
                    patch.object(pipeline, 'render', return_value={}), patch.object(pipeline, 'group_previews'):
                detector.return_value.locate.side_effect = [{'pose': pose}, AlignmentUnavailable('low_confidence')]
                rows, groups = pipeline.run(baseline, job, root/'out', GroupConfig(), None, None)
            self.assertEqual([r['status'] for r in rows], ['aligned', 'needs_review'])
            self.assertEqual(groups[0]['excluded_asset_ids'], ['b'])
            self.assertFalse(groups[0]['complete'])
            self.assertFalse(groups[0]['singleton'])
            self.assertEqual(groups[0]['status'], 'partial')


if __name__ == '__main__':
    unittest.main()

import copy
import unittest
from unittest.mock import patch

import numpy as np

from scripts.body_scan.framing import UniformConfig, uniform_plan
from scripts.body_scan_person_scale.evidence import validate
from scripts.body_scan_person_scale.coverage import check as check_coverage, measure_bounds
from scripts.body_scan_person_scale.measurements import measure
from scripts.body_scan_person_scale.pipeline import render_plan
from scripts.body_scan_person_scale.solve import plan, reference_template


def semantic():
    return dict(id='I1', background_group='B1', near_wall=True, arms_raised=False,
                neutral_reference=True, torso_usable=True, thigh_usable=True, shin_usable=True,
                confidence=.95, reason='relaxed neutral stance')


def pose_row():
    kp = np.zeros((17, 3)); kp[:, 2] = .99
    for a, b, y in ((5, 6, 100), (7, 8, 150), (11, 12, 200), (13, 14, 300), (15, 16, 400)):
        kp[a, :2] = [100, y]; kp[b, :2] = [150, y]
    return {'classification': {'view': 'front'}, 'geometry': {'H_source_to_corrected': np.eye(3).tolist()},
            'pose': {'keypoints_source': kp.tolist(), 'selected_pairs': [[5, 11], [6, 12]],
                     'anchor': [125, 100], 'hip_anchor': [125, 200]}}


def context(aid, neutral=True, base=1., lengths=None):
    return {'row': {'asset_id': aid, 'frame': {'uniform_scale': base}},
            'measurement': {'neutral': neutral, 'raised_arms': not neutral,
                            'lengths': lengths or {'torso': 100., 'thigh': 100., 'shin': 100.}}}


class ScaleTests(unittest.TestCase):
    def test_exact_semantic_partition(self):
        self.assertEqual(set(validate({'images': [semantic()]}, {'I1': 'asset'})), {'asset'})
        with self.assertRaisesRegex(ValueError, 'missing_images'):
            validate({'images': [semantic()]}, {'I1': 'a', 'I2': 'b'})
        with self.assertRaisesRegex(ValueError, 'semantic_id'):
            validate({'images': [semantic(), semantic()]}, {'I1': 'a'})

    def test_bad_semantic_values_rejected(self):
        for key, value in [('confidence', float('nan')), ('near_wall', 'true'), ('background_group', '')]:
            row = semantic(); row[key] = value
            with self.assertRaises(ValueError):
                validate({'images': [row]}, {'I1': 'a'})

    def test_head_and_silhouette_do_not_determine_scale(self):
        row = pose_row(); before = measure(row, semantic())
        row['subject_box'] = [-100, -500, 500, 500]
        row['pose']['keypoints_source'][0] = [10000, -10000, 1.]
        self.assertEqual(before['lengths'], measure(row, semantic())['lengths'])

    def test_missing_ankles_not_used(self):
        row = pose_row(); row['pose']['keypoints_source'][16][2] = .2
        result = measure(row, semantic())
        self.assertNotIn('shin', result['lengths'])
        self.assertTrue(result['neutral'])

    def test_raised_grid_and_wall_use_same_rules(self):
        row = pose_row(); evidence = semantic(); evidence['arms_raised'] = True
        outputs = []
        for route in ('grid', 'non_grid'):
            row['route'] = route; outputs.append(measure(row, evidence))
        self.assertEqual(outputs[0], outputs[1])
        self.assertFalse(outputs[0]['neutral'])
        self.assertNotIn('torso', outputs[0]['lengths'])

    def test_bent_segment_excluded(self):
        row = pose_row(); row['pose']['keypoints_source'][13][0] += 100
        self.assertNotIn('thigh', measure(row, semantic())['lengths'])

    def test_two_neutral_references_required(self):
        with self.assertRaisesRegex(ValueError, 'fewer_than_two'):
            reference_template([context('a'), context('b', False)])

    def test_raised_baseline_cannot_bias_reference(self):
        refs, targets, report = reference_template([context('a'), context('b'), context('c', False, 10)])
        self.assertEqual(targets, {'a': 1., 'b': 1.})
        self.assertEqual(report['target_segment_pixels']['torso'], 100.)

    @patch('scripts.body_scan_person_scale.solve.relative', return_value=(1., {'method': 'measured_same_board_pitch'}))
    def test_covered_legs_do_not_discard_two_reliable_grid_references(self, relative):
        cases = [context('a', lengths={'torso': 100.}), context('b', lengths={'torso': 100.}),
                 context('c', False, .9)]
        cases[2]['measurement']['lengths'] = {}
        result, reference = plan(cases)
        self.assertEqual(reference['reference_ids'], ['a', 'b'])
        self.assertEqual(result['c']['status'], 'calibrated')
        self.assertEqual(result['c']['scale'], 1.)

    @patch('scripts.body_scan_person_scale.solve.relative', return_value=(1., {'method': 'fixture'}))
    def test_two_background_refs_correct_side_without_usable_ankles(self, relative):
        cases = [context('a'), context('b'), context('c', False, .9, {'thigh': 100.})]
        result, _ = plan(cases)
        self.assertEqual(result['c']['status'], 'calibrated')
        self.assertAlmostEqual(result['c']['scale'], 1.)

    @patch('scripts.body_scan_person_scale.solve.relative', return_value=(1., {'method': 'fixture'}))
    def test_large_independent_conflict_retains_original(self, relative):
        cases = [context('a'), context('b'), context('c', False, 1., {'thigh': 140.})]
        result, _ = plan(cases)
        self.assertEqual(result['c']['status'], 'retained_for_review')
        self.assertEqual(result['c']['relative_scale'], 1.)

    @patch('scripts.body_scan_person_scale.solve.relative', side_effect=ValueError('no_background'))
    def test_single_segment_is_not_enough(self, relative):
        result, _ = plan([context('a'), context('b'), context('c', False, 1., {'thigh': 90.})])
        self.assertEqual(result['c']['status'], 'retained_for_review')

    @patch('scripts.body_scan_person_scale.solve.relative', return_value=(1., {'method': 'fixture'}))
    def test_small_neutral_variation_keeps_original(self, relative):
        result, _ = plan([context('a'), context('b'), context('c', False, 1.01)])
        # Raised pose still needs a neutral framing anchor even within deadband.
        self.assertEqual(result['c']['status'], 'calibrated')
        self.assertEqual(result['a']['status'], 'retained')

    @patch('scripts.body_scan_person_scale.solve.relative', return_value=(1., {'method': 'fixture'}))
    def test_neutral_pair_does_not_exchange_small_scale_errors(self, relative):
        cases = [context('a', base=1., lengths={'torso': 100.}),
                 context('b', base=1.03, lengths={'torso': 100.})]
        result, _ = plan(cases)
        self.assertEqual(result['a']['status'], 'retained')
        self.assertEqual(result['b']['status'], 'retained')

    def test_virtual_anchor_does_not_change_body_angle_or_aspect(self):
        row = pose_row(); config = UniformConfig()
        for raised in (False, True):
            audit = dict(scale=1.4, raised_arms=raised, neutral_torso_pixels=150., method='fixture')
            sp = render_plan(row, audit, config)
            pose = copy.deepcopy(row['pose'])
            pose['torso_length'] = config.height*config.torso_fraction/sp['uniform_scale']
            pose['anchor'][1] = pose['hip_anchor'][1]-(sp['target_hip_y']-(config.height*config.shoulder_y-.5))/sp['uniform_scale']
            A = np.asarray(uniform_plan(pose, config)['H_corrected_to_aligned'])
            np.testing.assert_allclose(A[:2, :2], np.eye(2)*1.4)
            if not raised:
                self.assertAlmostEqual(pose['anchor'][1], row['pose']['anchor'][1])

    def test_new_head_crop_is_rejected(self):
        frame = {'content_rectangle_xyxy': [0, 0, 200, 400], 'H_source_to_aligned': np.eye(3).tolist()}
        previous = {'visibility': {'visible_bbox': [.1, .02, .9, .95], 'head': 'complete', 'lower_extent': 'feet_complete'},
                    'output': {'H_aligned_to_display': np.eye(3).tolist()}, 'group_plan': {'output_size': [200, 400]}}
        new = copy.deepcopy(frame); new['H_source_to_aligned'][1][2] = -12
        self.assertEqual(check_coverage(previous, frame, new)['reason'], 'would_crop_previously_complete_head')
        self.assertIsNone(check_coverage(previous, frame, frame)['reason'])

    def test_new_foot_crop_is_rejected(self):
        frame = {'content_rectangle_xyxy': [0, 0, 200, 400], 'H_source_to_aligned': np.eye(3).tolist()}
        previous = {'visibility': {'visible_bbox': [.1, .05, .9, .99], 'head': 'complete', 'lower_extent': 'feet_complete'},
                    'output': {'H_aligned_to_display': np.eye(3).tolist()}, 'group_plan': {'output_size': [200, 400]}}
        new = copy.deepcopy(frame); new['H_source_to_aligned'][1][2] = 12
        self.assertEqual(check_coverage(previous, frame, new)['reason'], 'would_crop_previously_complete_feet')
        previous['visibility']['lower_extent'] = 'feet_cut'
        self.assertEqual(check_coverage(previous, frame, new)['reason'], 'would_reduce_previously_visible_lower_body')

    def test_touching_feet_and_already_missing_calves_keep_visible_extent(self):
        frame = {'content_rectangle_xyxy': [0, 0, 200, 400], 'H_source_to_aligned': np.eye(3).tolist()}
        previous = {'visibility': {'visible_bbox': [.1, .05, .9, 1.], 'head': 'complete', 'lower_extent': 'feet_touching_border'},
                    'output': {'H_aligned_to_display': np.eye(3).tolist()}, 'group_plan': {'output_size': [200, 400]}}
        new = copy.deepcopy(frame); new['H_source_to_aligned'][1][2] = 12
        for lower in ('feet_touching_border', 'feet_cut', 'calves_cut', 'knees_cut'):
            previous['visibility']['lower_extent'] = lower
            self.assertEqual(check_coverage(previous, frame, new, [20, 20, 180, 399])['reason'],
                             'would_reduce_previously_visible_lower_body')

    def test_old_final_crop_limits_required_span(self):
        frame = {'content_rectangle_xyxy': [0, 0, 200, 400], 'H_source_to_aligned': np.eye(3).tolist()}
        previous = {'visibility': {'visible_bbox': [.1, .05, .9, 1.], 'head': 'complete', 'lower_extent': 'feet_cut'},
                    'output': {'H_aligned_to_display': np.eye(3).tolist()}, 'group_plan': {'output_size': [200, 370]}}
        new = copy.deepcopy(frame); new['H_source_to_aligned'][1][2] = 12
        self.assertIsNone(check_coverage(previous, frame, new, [20, 20, 180, 399])['reason'])

    def test_previously_cut_head_cannot_be_cut_further(self):
        frame = {'content_rectangle_xyxy': [0, 0, 200, 400], 'H_source_to_aligned': np.eye(3).tolist()}
        previous = {'visibility': {'visible_bbox': [.1, 0, .9, 1.], 'head': 'cut', 'lower_extent': 'feet_cut'},
                    'output': {'H_aligned_to_display': np.eye(3).tolist()}, 'group_plan': {'output_size': [200, 400]}}
        new = copy.deepcopy(frame); new['H_source_to_aligned'][1][2] = -12
        self.assertEqual(check_coverage(previous, frame, new, [20, 0, 180, 399])['reason'],
                         'would_reduce_previously_visible_upper_body')

    def test_boundary_uses_measured_contour_not_rough_vlm_box(self):
        frame = {'content_rectangle_xyxy': [0, 0, 200, 400], 'H_source_to_aligned': np.eye(3).tolist()}
        previous = {'visibility': {'visible_bbox': [.1, .01, .9, .99], 'head': 'complete', 'lower_extent': 'feet_cut'},
                    'output': {'H_aligned_to_display': np.eye(3).tolist()}, 'group_plan': {'output_size': [200, 400]}}
        new = copy.deepcopy(frame); new['H_source_to_aligned'][1][2] = -12
        mask = np.zeros((400, 200), bool); mask[30:390, 30:170] = True; mask[0, 50] = True
        bounds = measure_bounds(mask, frame['content_rectangle_xyxy'])
        self.assertEqual(bounds[1], 30.)
        self.assertIsNone(check_coverage(previous, frame, new, bounds)['reason'])

    def test_near_zero_new_headroom_is_not_accepted(self):
        frame = {'content_rectangle_xyxy': [0, 0, 200, 400], 'H_source_to_aligned': np.eye(3).tolist()}
        previous = {'visibility': {'visible_bbox': [.1, .1, .9, 1.], 'head': 'complete', 'lower_extent': 'feet_cut'},
                    'output': {'H_aligned_to_display': np.eye(3).tolist()}, 'group_plan': {'output_size': [200, 400]}}
        new = copy.deepcopy(frame); new['H_source_to_aligned'][1][2] = -14
        self.assertEqual(check_coverage(previous, frame, new, [20, 16, 180, 399])['reason'],
                         'would_crop_previously_complete_head')


if __name__ == '__main__':
    unittest.main()

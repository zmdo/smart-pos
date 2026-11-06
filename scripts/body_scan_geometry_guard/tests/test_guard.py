import copy
import json
import math
import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

from scripts.body_scan.framing import UniformConfig
from scripts.body_scan.refinement import compose, save_render
from scripts.body_scan_geometry_guard.policy import decide
from scripts.body_scan_geometry_guard.pipeline import run, digest


def rotation(degrees):
    a = math.radians(degrees)
    return np.array([[math.cos(a), -math.sin(a), 0], [math.sin(a), math.cos(a), 0], [0, 0, 1.]])


def row(angle=6., uncertainty=5., H=None):
    return {'status': 'rectangular', 'route': 'non_grid', 'size': [800, 1200],
            'geometry': {'correction_applied': True,
                         'calibration': {'roll_deg': angle, 'roll_uncertainty_deg': uncertainty,
                                         'pitch_deg': 0., 'pitch_uncertainty_deg': 0.},
                         'H_source_to_corrected': (rotation(angle) if H is None else H).tolist()}}


def wall_evidence(target, angle=0.):
    # Generate physical horizontal and vertical lines independently of the checker.
    segments = [[100, 200, 700, 200], [100, 900, 700, 900],
                [100, 200, 100, 900], [700, 200, 700, 900]]
    lines = []
    R = rotation(angle)
    for i, s in enumerate(segments):
        p = np.c_[np.asarray(s).reshape(2, 2), np.ones(2)] @ R.T
        lines.append({'id': i+1, 'direction': 'horizontal' if i < 2 else 'vertical',
                      'segment': p[:, :2].ravel().tolist()})
    target['refinement'] = {
        'scene': {'near_planar_wall': True, 'confidence': .9,
                  'wall_polygon': [[0, 0], [1, 0], [1, 1], [0, 1]]},
        'line_candidates': lines,
        'selection': {'confidence': .9, 'horizontal_ids': [1, 2], 'vertical_ids': [3, 4]}}
    return target


class PolicyTests(unittest.TestCase):
    def test_uncertain_large_transform_without_references_rolls_back(self):
        self.assertEqual(decide(row())['reason'], 'uncertain_camera_without_wall_support')

    def test_uncertain_tiny_transform_keeps_output(self):
        self.assertEqual(decide(row(.4, 8.))['action'], 'retain')

    def test_large_angle_well_above_uncertainty_keeps_output(self):
        r = row(0, 1); r['geometry']['calibration'].update(pitch_deg=-18, pitch_uncertainty_deg=5)
        self.assertEqual(decide(r)['action'], 'retain')

    def test_large_uncertain_pitch_is_also_screened(self):
        r = row(0, 1); r['geometry']['calibration'].update(pitch_deg=-15, pitch_uncertainty_deg=8)
        self.assertEqual(decide(r)['uncertain_significant_axes'], ['pitch'])
        self.assertEqual(decide(r)['action'], 'rollback')

    def test_real_two_direction_improvement_supports_uncertain_correction(self):
        r = wall_evidence(row(6, 5, rotation(-6)), 6)
        self.assertEqual(decide(r)['reason'], 'uncertain_camera_supported_by_wall')
        self.assertEqual(decide(r)['action'], 'retain')

    def test_wall_regression_overrides_even_confident_camera(self):
        r = wall_evidence(row(6, .1))
        result = decide(r)
        self.assertEqual(result['reason'], 'verified_wall_regression')
        self.assertEqual(result['regressed_families'], ['horizontal', 'vertical'])

    def test_wrong_vertical_id_does_not_erase_real_horizontal_evidence(self):
        r = wall_evidence(row()); r['refinement']['selection']['vertical_ids'] = [1]
        result = decide(r)
        self.assertEqual(result['regressed_families'], ['horizontal'])
        self.assertIn('invalid_vertical_selection', result['rejected_evidence'])

    def test_no_hallucinated_id_or_low_confidence_can_create_regression(self):
        for value in [float('nan'), .3]:
            r = wall_evidence(row(6, .1)); r['refinement']['selection']['confidence'] = value
            self.assertEqual(decide(r)['action'], 'retain')
        r = wall_evidence(row(6, .1)); r['refinement']['selection'].update(horizontal_ids=[99], vertical_ids=[])
        self.assertEqual(decide(r)['action'], 'retain')

    def test_one_perspective_slanted_horizontal_is_not_forced_level(self):
        r = wall_evidence(row(0, .1, rotation(-2)), 8)
        r['refinement']['selection']['vertical_ids'] = []
        self.assertEqual(decide(r)['action'], 'retain')

    def test_duplicate_short_edges_cannot_inflate_coverage(self):
        r = wall_evidence(row(6, .1))
        r['refinement']['selection']['vertical_ids'] = []
        for c in r['refinement']['line_candidates'][:2]:
            c['segment'] = [100, 200, 150, 200]
        self.assertEqual(decide(r)['action'], 'retain')

    def test_grid_and_excluded_rows_never_change(self):
        for r in [{'status': 'rectangular', 'route': 'grid'}, {'status': 'needs_review'}]:
            self.assertEqual(decide(r)['reason'], 'outside_non_grid_scope')

    def test_body_posture_never_enters_decision(self):
        r = wall_evidence(row()); before = decide(r)
        r['pose'] = {'anchor': [0, 0], 'hip_anchor': [999, 100], 'keypoints_source': 'not_used'}
        self.assertEqual(decide(r), before)


class IntegrationTests(unittest.TestCase):
    def test_only_rejected_geometry_rerenders_and_all_baselines_remain_immutable(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); baseline = root/'baseline'; baseline.mkdir()
            cfg = UniformConfig(width=128, height=320)
            (baseline/'config.json').write_text(json.dumps({'version': 'body-scan-wall-v3', **cfg.__dict__}))
            image = np.full((320, 128, 3), 180, np.uint8)
            cv2.rectangle(image, (30, 20), (100, 300), (130, 160, 170), -1)
            source = root/'source.png'; cv2.imwrite(str(source), image)
            kp = np.zeros((17, 3)); kp[:, :2] = [64, 100]; kp[:, 2] = .99
            kp[[5, 6, 11, 12], :2] = [[45, 65], [85, 65], [45, 150], [85, 150]]
            records = []
            for aid, route in [('suspect', 'non_grid'), ('normal', 'grid')]:
                r = row(); r.update(asset_id=aid, store='测试店', member='测试会员', size=[128, 320],
                                    route=route, source=str(source), source_sha256=digest(source),
                                    subject_box=[25, 15, 105, 310], classification={'view': 'front'},
                                    pose={'keypoints_source': kp.tolist()})
                result = compose(image, r, rotation(6), cfg)
                (baseline/aid).mkdir(); cv2.imwrite(str(baseline/aid/'original.png'), image)
                save_render(baseline, r, result); records.append(r)
            (baseline/'summary.json').write_text(json.dumps(records))
            before = {str(p): digest(p) for p in baseline.rglob('*') if p.is_file()}
            out = root/'new'; verification = run([baseline], out)
            self.assertEqual(verification['changed_asset_ids'], ['suspect'])
            self.assertEqual(verification['byte_identical_grid_asset_ids'], ['normal'])
            self.assertEqual(before, {str(p): digest(p) for p in baseline.rglob('*') if p.is_file()})
            updated = json.loads((out/'suspect'/'report.json').read_text())
            np.testing.assert_allclose(updated['geometry']['H_source_to_corrected'], np.eye(3))
            np.testing.assert_allclose(updated['pose']['keypoints_corrected'], kp[:, :2])
            with self.assertRaisesRegex(ValueError, 'already_exists'):
                run([baseline], out)
            with self.assertRaisesRegex(ValueError, 'unguarded'):
                run([out], root/'twice')
            source.write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError, 'source_changed'):
                run([baseline], root/'bad')
            self.assertFalse((root/'bad').exists())


if __name__ == '__main__':
    unittest.main()

"""Geometry regressions; run with the server's Python (no local GPU required)."""
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import grid_rectify_single as grid


class GridRectificationTests(unittest.TestCase):
    def test_both_tilt_signs_and_projective_convergence(self):
        vertical = np.array([[x, 120, x, 1480] for x in range(140, 1100, 40)], float)
        horizontal = np.array([[140, y, 1060, y] for y in range(120, 1520, 40)], float)
        for sign in (-1, 1):
            with self.subTest(sign=sign):
                camera = np.array([[1., sign * .035, 8], [sign * .025, 1., 16],
                                   [sign * .000025, -sign * .00004, 1.]])
                v = grid.transform(vertical.reshape(-1, 2), camera).reshape(-1, 4)
                h = grid.transform(horizontal.reshape(-1, 2), camera).reshape(-1, 4)
                # Door/poster edges that do not belong to the grid's vanishing directions.
                bad_v = np.array([[30+i*17, 50, 95+i*17, 850] for i in range(7)])
                bad_h = np.array([[40, 60+i*18, 940, 165+i*18] for i in range(7)])
                H, _, _, _ = grid.solve_grid(np.r_[v, bad_v], np.r_[h, bad_h], (1600, 1200, 3))
                corrected_v = grid.transform(v.reshape(-1, 2), H).reshape(-1, 4)
                corrected_h = grid.transform(h.reshape(-1, 2), H).reshape(-1, 4)
                self.assertLess(np.max(np.abs(grid.angles(corrected_v, 'v'))), .05)
                self.assertLess(np.max(np.abs(grid.angles(corrected_h, 'h'))), .05)
                corners = np.array([[500., 600.], [540., 600.], [500., 640.]])
                restored = grid.transform(grid.transform(corners, camera), H)
                cell_x = np.linalg.norm(restored[1] - restored[0])
                cell_y = np.linalg.norm(restored[2] - restored[0])
                self.assertAlmostEqual(cell_x / cell_y, 1., delta=.01)

    def test_comparisons_skip_before_reading_or_inference(self):
        for phase, people in [('both', 1), ('unknown', 2)]:
            c = {'phase': phase, 'people': people, 'kind': 'body_scan', 'background': 'grid_board'}
            with tempfile.TemporaryDirectory() as folder:
                def fail_detector(_):
                    self.fail('Comparison images must not enter inference')
                report = grid.process('/does/not/exist.jpg', c, Path(folder) / 'output', fail_detector)
                self.assertEqual(report['reason'], 'comparison_or_multiple_people')
                self.assertEqual(list((Path(folder) / 'output').iterdir()), [Path(folder) / 'output/report.json'])

    def test_unknown_and_non_grid_do_not_enter_pipeline(self):
        self.assertEqual(grid.eligibility({}), 'single_person_not_confirmed')
        self.assertEqual(grid.eligibility({'people': 1, 'kind': 'body_scan', 'background': 'wood'}),
                         'not_grid_body_scan')

    def test_full_canvas_contains_all_original_corners(self):
        H = np.array([[1., .035, 0.], [-.025, 1., 0.], [.00001, -.00002, 1.]])
        H, (w, h), _ = grid.bounded_canvas(H, (1600, 1200, 3), [430, 180, 770, 1480])
        corners = grid.transform([[0, 0], [1199, 0], [1199, 1599], [0, 1599]], H)
        self.assertTrue((corners >= 0).all())
        self.assertTrue((corners[:, 0] < w).all() and (corners[:, 1] < h).all())

    def test_extreme_transform_rejected(self):
        for H in (np.diag([1.7, 1., 1.]), np.array([[1., 0., 0.], [0., 1., 0.], [-.002, 0., 1.]])):
            with self.assertRaises(grid.UncertainGrid):
                grid.bounded_canvas(H, (1600, 1200, 3), [430, 180, 770, 1480])

    def test_horizontal_regression_cannot_pass_with_good_verticals(self):
        before = {'vertical': {'median_deg': 1.5, 'p90_deg': 2.5},
                  'horizontal': {'median_deg': .2, 'p90_deg': .7}}
        after = {'vertical': {'median_deg': 0., 'p90_deg': .3},
                 'horizontal': {'median_deg': 2.9, 'p90_deg': 3.8}}
        with self.assertRaisesRegex(grid.UncertainGrid, 'horizontal'):
            grid.validate_angles(before, after)

    def test_existing_output_cannot_be_overwritten(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(FileExistsError):
                grid.process('/unused.jpg', {}, folder)


if __name__ == '__main__':
    unittest.main()

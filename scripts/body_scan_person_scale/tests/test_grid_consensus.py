import copy
import unittest
from unittest.mock import patch

from scripts.body_scan_person_scale.solve import plan
from scripts.body_scan_person_scale.grid_consensus import reconcile, finalize, refine_coverage, verify_cohorts, VERSION


def fixture():
    values = [
        (1.4408356519, 34.84441479, True, {'torso': 335.80512765, 'thigh': 280.06274709, 'shin': 275.22068303}),
        (1.2152514226, 35.07622285, False, {'torso': 398.13983429, 'thigh': 323.05449830, 'shin': 323.98775566}),
        (.9999015621, 44.20667560, False, {}),
        (1.3406285548, 35.12968948, True, {'torso': 360.90533674, 'thigh': 343.35564188, 'shin': 336.63715974}),
        (.9220472080, 42.00714079, False, {}),
        (.9439977420, 42.75367682, False, {}),
    ]
    return [{'row': {'asset_id': f'p{i}', 'route': 'grid', 'frame': {'uniform_scale': base}},
             'measurement': {'neutral': neutral, 'raised_arms': False, 'lengths': lengths},
             'semantic': {'background_group': 'board', 'near_wall': True, 'confidence': .95},
             'background': {'grid_pitch': pitch, 'grid_measurement': {
                 'vertical': {'spacing_error_fraction': .03}, 'horizontal': {'spacing_error_fraction': .04}}}}
            for i, (base, pitch, neutral, lengths) in enumerate(values)]


class GridConsensusTests(unittest.TestCase):
    def test_worsening_six_photo_case_uses_one_board_scale(self):
        cases = fixture(); before = copy.deepcopy(cases)
        plans, reference = plan(cases)
        self.assertEqual(cases, before)
        record = reference['grid_scale_recovery']
        self.assertGreater(record['proposed_pitch_spread'], record['baseline_pitch_spread']+.03)
        self.assertEqual(len(record['asset_ids']), 6)
        target = record['target_grid_pitch']
        self.assertAlmostEqual(target, 43.414, places=2)
        for c in cases:
            p = plans[c['row']['asset_id']]
            self.assertEqual(p['method'], VERSION)
            self.assertTrue(p['requires_review'])
            self.assertAlmostEqual(c['background']['grid_pitch']*p['scale'], target)
        self.assertLess(plans['p0']['relative_scale'], 1)
        self.assertGreater(plans['p0']['prior_decision']['relative_scale'], 1)
        self.assertGreater(plans['p0']['prior_decision']['body_background_disagreement'], .21)

    def test_consistent_group_keeps_original_scales(self):
        cases = fixture()
        for c in cases:
            c['row']['frame']['uniform_scale'] = 1.
            c['measurement']['lengths'] = {'torso': 100., 'thigh': 100., 'shin': 100.}
            c['background']['grid_pitch'] = 20.
        plans, reference = plan(cases)
        self.assertNotIn('grid_scale_recovery', reference)
        self.assertTrue(all(p['scale'] == 1 and p['status'] == 'retained' for p in plans.values()))

    def test_different_boards_are_not_given_a_shared_pitch(self):
        cases = fixture(); cases[-1]['semantic']['background_group'] = 'other'
        plans, reference = plan(cases)
        self.assertNotIn('grid_scale_recovery', reference)
        self.assertEqual(plans['p0']['status'], 'retained_for_review')

    def test_unreliable_grid_or_wall_distance_stops_recovery(self):
        for kind in ('measurement', 'distance', 'confidence', 'non_grid'):
            with self.subTest(kind=kind):
                cases = fixture()
                if kind == 'measurement':
                    cases[2]['background']['grid_measurement']['horizontal']['spacing_error_fraction'] = .1
                elif kind == 'distance':cases[2]['semantic']['near_wall'] = False
                elif kind == 'confidence':cases[2]['semantic']['confidence'] = .8
                else:cases[2]['row']['route'] = 'non_grid'
                _, reference = plan(cases)
                self.assertNotIn('grid_scale_recovery', reference)

    @patch('scripts.body_scan_person_scale.solve.relative', return_value=(1.25, {'method': 'fixture'}))
    def test_independent_conflict_is_not_a_self_comparison(self, relative):
        def one_reference(ref, target):
            if ref['row']['asset_id'] != 'p0':
                raise ValueError('no_second_background_reference')
            return 1.25, {'method': 'fixture'}
        relative.side_effect = one_reference
        cases = fixture()[:3]
        for c in cases:
            c['row']['route'] = 'non_grid'
            c['row']['frame']['uniform_scale'] = 1.
            c['measurement']['lengths'] = {'torso': 100., 'thigh': 100., 'shin': 100.}
        cases[1]['measurement']['neutral'] = True
        cases[2]['measurement']['lengths'] = {'torso': 95., 'thigh': 95., 'shin': 95.}
        plans, _ = plan(cases)
        self.assertEqual(plans['p2']['body_selected_scale_disagreement'], 0)
        self.assertGreater(plans['p2']['body_background_disagreement'], .3)
        self.assertEqual(plans['p2']['status'], 'retained_for_review')
        self.assertEqual(plans['p2']['scale'], 1.)

    def test_missing_background_does_not_invent_zero_disagreement(self):
        cases = fixture()
        for c in cases:c['background']['grid_pitch'] = None
        plans, _ = plan(cases)
        self.assertIsNone(plans['p0']['body_background_disagreement'])

    def test_existing_unmodified_group_is_not_recalibrated(self):
        cases = fixture(); plans, _ = plan(cases)
        for p in plans.values():
            p.update(scale=p['base_scale'], relative_scale=1., status='retained_for_review')
        self.assertIsNone(reconcile(cases, plans))

    def test_failed_coverage_rolls_back_whole_group(self):
        plans, _ = plan(fixture())
        pending = {aid: object() for aid in plans if aid != 'p4'}
        finalize(plans, pending)
        self.assertEqual(pending, {})
        for p in plans.values():
            self.assertEqual(p['status'], 'retained_for_review')
            self.assertEqual(p['scale'], p['base_scale'])
            self.assertFalse(p['grid_common_scale']['applied'])

    def test_successful_group_is_verified_against_actual_frame(self):
        plans, _ = plan(fixture()); pending = {aid: object() for aid in plans}
        finalize(plans, pending)
        rows = [{'asset_id': aid, 'person_scale': p, 'frame': {'uniform_scale': p['scale']}}
                for aid, p in plans.items()]
        self.assertLess(verify_cohorts(rows)[0]['actual_pitch_spread'], 1e-10)
        rows[0]['frame']['uniform_scale'] *= 1.1
        with self.assertRaisesRegex(ValueError, 'common_grid_scale_mismatch'):
            verify_cohorts(rows)

    def test_partial_success_is_never_claimed_as_coherent(self):
        plans, _ = plan(fixture()); finalize(plans, {aid: object() for aid in plans})
        rows = [{'asset_id': aid, 'person_scale': p, 'frame': {'uniform_scale': p['scale']}}
                for aid, p in plans.items()]
        rows[-1]['person_scale']['grid_common_scale']['applied'] = False
        with self.assertRaisesRegex(ValueError, 'partial_common_grid'):
            verify_cohorts(rows)

    def test_coverage_retry_changes_whole_group_together(self):
        cases = fixture(); plans, _ = plan(cases)
        initial = plans['p0']['grid_common_scale']['target_grid_pitch']
        for p in plans.values():p['boundary_measurement'] = {'bounds_aligned': [0, 0, 10, 20]}
        pending = {}; seen = []
        def evaluate(context, audit):
            seen.append(audit['grid_common_scale']['coverage_zoom'])
            if audit['grid_common_scale']['coverage_zoom'] < 1.02:
                raise ValueError('new_padding_above_four_percentage_points')
            return object()
        refine_coverage(cases, plans, pending, evaluate)
        self.assertEqual(set(pending), set(plans))
        self.assertEqual(set(seen), {1.01, .99, 1.02})
        for p in plans.values():
            self.assertAlmostEqual(p['grid_common_scale']['target_grid_pitch'], initial*1.02)

    def test_unsatisfiable_coverage_is_bounded_and_retains_originals(self):
        cases = fixture(); plans, _ = plan(cases); pending = {}; seen = []
        for p in plans.values():p['boundary_measurement'] = {'bounds_aligned': [0, 0, 10, 20]}
        def evaluate(context, audit):
            seen.append(audit['grid_common_scale']['coverage_zoom'])
            raise ValueError('would_crop_previously_complete_head')
        refine_coverage(cases, plans, pending, evaluate)
        finalize(plans, pending)
        self.assertEqual(len(seen), 60)
        self.assertGreaterEqual(min(seen), .95); self.assertLessEqual(max(seen), 1.05)
        self.assertTrue(all(p['scale'] == p['base_scale'] and p['status'] == 'retained_for_review'
                            for p in plans.values()))


if __name__ == '__main__':
    unittest.main()

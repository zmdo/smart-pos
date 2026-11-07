import copy
import unittest
from unittest.mock import patch

from scripts.body_scan_person_scale.solve import plan
from scripts.body_scan_person_scale.proposal_guard import apply, VERSION

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


class ProposalGuardTests(unittest.TestCase):
    def test_conflicting_front_growth_cancelled_without_changing_other_five(self):
        cases = fixture()
        with patch('scripts.body_scan_person_scale.solve.guard_proposals', return_value={}):
            legacy, _ = plan(cases)
        guarded, report = plan(cases)
        self.assertEqual(report['proposal_guard']['rejected_asset_ids'], ['p0'])
        self.assertEqual(guarded['p0']['status'], 'retained_for_review')
        self.assertEqual(guarded['p0']['scale'], guarded['p0']['base_scale'])
        self.assertGreater(guarded['p0']['proposed_scale'], guarded['p0']['base_scale'])
        self.assertTrue(guarded['p0']['requires_review'])
        for aid in guarded:
            self.assertNotIn('grid_common_scale', guarded[aid])
            if aid != 'p0':
                self.assertEqual(guarded[aid]['scale'], legacy[aid]['scale'])
                self.assertEqual(guarded[aid]['status'], legacy[aid]['status'])

    def proposals(self, cases):
        with patch('scripts.body_scan_person_scale.solve.guard_proposals', return_value={}):
            return plan(cases)[0]

    def test_background_alone_cannot_cancel_or_assign_scale(self):
        cases = fixture(); plans = self.proposals(cases)
        cases[0]['measurement']['lengths'].pop('torso')
        before = copy.deepcopy(plans)
        self.assertEqual(apply(cases, plans)['rejected_asset_ids'], [])
        self.assertEqual(plans['p0'], before['p0'])
        for aid in plans:
            self.assertEqual(plans[aid]['scale'], before[aid]['scale'])
            self.assertEqual(plans[aid]['status'], before[aid]['status'])

    def test_torso_disagreement_alone_cannot_cancel_scale(self):
        cases = fixture(); plans = self.proposals(cases)
        for c in cases:c['background']['grid_pitch'] = None
        before = copy.deepcopy(plans)
        self.assertEqual(apply(cases, plans)['rejected_asset_ids'], [])
        self.assertEqual(plans, before)

    def test_unrelated_unreliable_or_distant_background_not_a_peer(self):
        for kind in ('different', 'noisy', 'distant', 'low_confidence', 'non_grid'):
            with self.subTest(kind=kind):
                cases = fixture(); plans = self.proposals(cases)
                for c in cases[1:]:
                    if kind == 'different':c['semantic']['background_group'] = 'other'
                    elif kind == 'noisy':c['background']['grid_measurement']['horizontal']['spacing_error_fraction'] = .2
                    elif kind == 'distant':c['semantic']['near_wall'] = False
                    elif kind == 'low_confidence':c['semantic']['confidence'] = .8
                    else:c['row']['route'] = 'non_grid'
                self.assertEqual(apply(cases, plans)['rejected_asset_ids'], [])

    def test_peers_that_are_changing_are_not_stable_evidence(self):
        cases = fixture(); plans = self.proposals(cases)
        for p in plans.values():p['status'] = 'calibrated'
        self.assertEqual(apply(cases, plans)['rejected_asset_ids'], [])

    def test_disagreeing_peer_interval_abstains(self):
        cases = fixture(); plans = self.proposals(cases)
        cases[2]['background']['grid_pitch'] *= 2
        self.assertEqual(apply(cases, plans)['rejected_asset_ids'], [])

    def test_body_consistent_growth_is_not_cancelled_by_grid_alone(self):
        cases = fixture(); plans = self.proposals(cases)
        cases[0]['measurement']['lengths']['torso'] = plans['p0']['neutral_torso_pixels']/plans['p0']['scale']
        self.assertEqual(apply(cases, plans)['rejected_asset_ids'], [])

    def test_audit_contains_two_independent_measurements_and_no_new_target(self):
        plans, _ = plan(fixture()); guard = plans['p0']['proposal_guard']
        self.assertEqual(guard['version'], VERSION)
        self.assertGreater(guard['torso_error_after'], guard['torso_error_before']+.05)
        self.assertGreater(guard['background_distance_after'], guard['background_distance_before']+.02)
        self.assertNotIn('target_grid_pitch', guard)

    def test_normal_group_unchanged(self):
        cases = fixture()
        for c in cases:
            c['row']['frame']['uniform_scale'] = 1.
            c['measurement']['lengths'] = {'torso': 100., 'thigh': 100., 'shin': 100.}
            c['background']['grid_pitch'] = 20.
        plans, report = plan(cases)
        self.assertEqual(report['proposal_guard']['rejected_asset_ids'], [])
        self.assertTrue(all(p['scale'] == 1 for p in plans.values()))

    def test_absent_background_is_unknown_not_zero_disagreement(self):
        cases = fixture()
        for c in cases:c['background']['grid_pitch'] = None
        plans, _ = plan(cases)
        self.assertIsNone(plans['p0']['body_background_disagreement'])


if __name__ == '__main__':
    unittest.main()

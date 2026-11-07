import copy
import unittest

import numpy as np

from scripts.body_scan_group_display.planning import Config, PlanUnavailable, plan_person
from scripts.body_scan_group_display.stability import preserve


def fixture():
    items = [{'asset_id': aid, 'status': 'displayed', 'source_sha256': aid,
              'normalized_bounds': [-384, -412, 384, 1380],
              'required_core': [-150, -8, 150, 490],
              'visible_bounds_normalized': [-220, -350, 220, 1330],
              'visibility': {'head': 'complete', 'lower_extent': 'feet_cut'},
              'H_source_to_normalized': np.eye(3).tolist(),
              'upstream_report': {'geometry': {'fixture': 1}, 'pose': {'fixture': 1}}}
             for aid in ('a', 'b')]
    plan = plan_person(items)
    for r in items:r['group_plan'] = copy.deepcopy(plan)
    previous = {r['asset_id']: copy.deepcopy(r) for r in items}
    items[0]['upstream_report']['person_scale'] = {'proposal_guard': {'status': 'rejected_worsening_proposal'}}
    return items, plan, previous


class PresentationStabilityTests(unittest.TestCase):
    def test_safe_reference_keeps_size_crop_stretch_shoulders_and_transform(self):
        items, plan, previous = fixture()
        proposed = copy.deepcopy(plan); proposed['output_size'][1] = 1689
        kept = preserve(items, proposed, previous, Config())
        for key in ('output_size', 'crop_rectangle', 'vertical_stretch', 'shoulder_target',
                    'H_normalized_to_display', 'H_normalized_to_uniform'):
            self.assertEqual(kept[key], plan[key])

    def test_already_partial_body_cannot_lose_more_in_final_frame(self):
        items, plan, previous = fixture()
        items[0]['H_source_to_normalized'] = np.diag([1.1, 1.1, 1.]).tolist()
        with self.assertRaisesRegex(PlanUnavailable, 'reduce_visible_body'):
            preserve(items, plan, previous, Config())

    def test_reference_source_geometry_and_pose_must_match(self):
        for key in ('source', 'geometry', 'pose'):
            with self.subTest(key=key):
                items, plan, previous = fixture()
                if key == 'source':items[0]['source_sha256'] = 'different'
                else:items[0]['upstream_report'][key] = {'fixture': 2}
                with self.assertRaisesRegex(PlanUnavailable, 'source_changed'):
                    preserve(items, plan, previous, Config())

    def test_reference_cannot_extend_beyond_real_photo(self):
        items, plan, previous = fixture(); items[0]['normalized_bounds'][3] = 1250
        with self.assertRaisesRegex(PlanUnavailable, 'frame_no_longer_safe'):
            preserve(items, plan, previous, Config())

    def test_newly_confirmed_complete_head_stays_protected(self):
        items, plan, previous = fixture(); items[0]['visible_bounds_normalized'][1] = -413
        with self.assertRaisesRegex(PlanUnavailable, 'cut_complete_body'):
            preserve(items, plan, previous, Config())

    def test_missing_and_mismatched_reference_fail_closed(self):
        items, plan, previous = fixture()
        with self.assertRaisesRegex(PlanUnavailable, 'requires_reference'):
            preserve(items, plan, None, Config())
        previous.pop('b')
        with self.assertRaisesRegex(PlanUnavailable, 'members_changed'):
            preserve(items, plan, previous, Config())

    def test_groups_without_scale_veto_keep_existing_planner(self):
        items, plan, previous = fixture(); items[0]['upstream_report'].pop('person_scale')
        self.assertIs(preserve(items, plan, None, Config()), plan)

    def test_user_changed_width_is_not_silently_ignored(self):
        items, plan, previous = fixture()
        with self.assertRaisesRegex(PlanUnavailable, 'configuration_changed'):
            preserve(items, plan, previous, Config(width=1024))


if __name__ == '__main__':
    unittest.main()

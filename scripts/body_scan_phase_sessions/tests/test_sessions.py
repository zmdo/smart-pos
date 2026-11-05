import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from scripts.body_scan_phase.inputs import digest, load
from scripts.body_scan_phase.tests.test_phase import fixture
from scripts.body_scan_phase_sessions.evidence import (SessionEvidence, direction, validate_observations, validate_sessions)
from scripts.body_scan_phase_sessions.pipeline import run, process_group
from scripts.body_scan_phase_sessions.resolution import make_units, resolve


def observed(after='A', strength='clear', field='leaner'):
    return {'same_view': True, 'same_pose': True, 'visibility_comparable': True, 'confidence': .55,
            'markers': {'A': '', 'B': ''}, 'reason': '可比照片上的可见变化',
            'observations': {k: {'image': after if k == field else 'unknown',
                                'clarity': strength if k == field else 'none', 'confounded': False, 'reason': '具体可见依据'}
                             for k in ('leaner', 'better_posture', 'more_muscular')}}


def cluster(members, strong=('outfit', 'scene')):
    return {'members': members, 'repeated_setup_ambiguous': False, 'reason': '同一套衣着与相机位置特征',
            'cues': {k: {'strength': 'clear' if k in strong else 'none', 'reason': '具体独立依据'}
                     for k in ('outfit', 'scene', 'accessories')}}


def item(aid, view='front', phase='unknown'):
    return {'asset_id': aid, 'view': view, 'phase': phase, 'phase_source': 'unresolved' if phase == 'unknown' else 'explicit_marker',
            'reason': 'no_same_view_counterpart', 'status': 'needs_review' if phase == 'unknown' else 'labeled'}


def pair(pid, ids, after='B', strength='clear', view='front'):
    return {'pair_id': pid, 'asset_ids': ids, 'view_family': view,
            'decision': {'after': after, 'strength': strength, 'confidence': .55, 'reason': 'visible', 'markers': {}}}


class FakeEvidence:
    def __init__(self, split=3, strength='subtle'):
        self.split = split; self.strength = strength; self.seen = []

    def sessions(self, items, images):
        before = sorted(r['asset_id'] for r in items if int(r['asset_id'][1:]) < self.split)
        after = sorted(r['asset_id'] for r in items if int(r['asset_id'][1:]) >= self.split)
        return [{**cluster(m), 'reliable': True} for m in (before, after) if m], {}

    def compare(self, images):
        self.seen.append([int(im[0, 0, 0]) for im in images])
        after = 'B' if images[0][0, 0, 0] < images[2][0, 0, 0] else 'A'
        return {'after': after, 'strength': self.strength, 'markers': {}, 'reason': 'visible', 'confidence': .55}, {}


class ObservationTests(unittest.TestCase):
    def test_all_improvement_fields_mean_after_not_before(self):
        for key in ('leaner', 'better_posture', 'more_muscular'):
            self.assertEqual(direction(validate_observations(observed(field=key)))['after'], 'A')

    def test_low_reported_confidence_does_not_veto_clear_consistent_evidence(self):
        model = SessionEvidence()
        with patch.object(model, 'ask', side_effect=[(observed(), {}), (observed('B'), {})]):
            decision, _ = model.compare([np.zeros((2, 2, 3))]*4)
        self.assertEqual(decision['after'], 'A'); self.assertEqual(decision['strength'], 'clear')
        self.assertEqual(decision['confidence'], .55)

    def test_swapped_order_bias_is_rejected(self):
        model = SessionEvidence()
        with patch.object(model, 'ask', return_value=(observed(), {})):
            decision, _ = model.compare([np.zeros((2, 2, 3))]*4)
        self.assertEqual(decision['reason'], 'swapped_direction_conflict')
        self.assertIsNone(decision['after'])

    def test_subtle_evidence_also_gets_swapped_review(self):
        model = SessionEvidence()
        with patch.object(model, 'ask', side_effect=[(observed(strength='subtle'), {}), (observed('B', 'subtle'), {})]) as call:
            decision, _ = model.compare([np.zeros((2, 2, 3))]*4)
        self.assertEqual(call.call_count, 2); self.assertEqual(decision['strength'], 'subtle')

    def test_same_overall_direction_requires_a_repeated_specific_observation(self):
        model = SessionEvidence()
        with patch.object(model, 'ask', side_effect=[(observed(field='leaner'), {}), (observed('B',field='more_muscular'), {})]):
            decision, _ = model.compare([np.zeros((2,2,3))]*4)
        self.assertIsNone(decision['after'])
        self.assertEqual(decision['reason'], 'no_same_observation_survives_swap')

    def test_confounded_or_incomparable_cannot_support_a_phase(self):
        data = observed(); data['observations']['leaner']['confounded'] = True
        self.assertIsNone(direction(data)['after'])
        for flag in ('same_view', 'same_pose', 'visibility_comparable'):
            data = observed(); data[flag] = False
            self.assertEqual(direction(data)['reason'], 'not_comparable')

    def test_contradictory_clear_signals_are_not_majority_voted(self):
        data = observed()
        data['observations']['more_muscular'].update(image='B', clarity='clear')
        self.assertEqual(direction(data)['reason'], 'observation_directions_conflict')

    def test_invalid_semantic_response_retains_audit(self):
        model = SessionEvidence()
        with patch.object(model, 'ask', return_value=({'wrong': True}, {'request_count': 1})):
            decision, audit = model.compare([np.zeros((2, 2, 3))]*4)
        self.assertIsNone(decision['after']); self.assertEqual(audit['primary']['result'], {'wrong': True})
        for bad in (True, float('nan'), 2):
            value = observed(); value['confidence'] = bad
            with self.assertRaises(ValueError):
                validate_observations(value)

    def test_literal_marker_requires_matching_reading_after_swap(self):
        a, b = observed('unknown', 'none'), observed('unknown', 'none')
        a['markers']['A'] = '训练前'; b['markers']['B'] = '训练前'
        with patch.object(SessionEvidence, 'ask', side_effect=[(a, {}), (b, {})]):
            decision, _ = SessionEvidence().compare([np.zeros((2, 2, 3))]*4)
        self.assertEqual(decision['markers'], {'A': 'before'})


class SessionTests(unittest.TestCase):
    def test_partition_cannot_drop_duplicate_or_invent_assets(self):
        for members in (['I1'], ['I1', 'I1'], ['I1', 'I3']):
            with self.assertRaises(ValueError):
                validate_sessions({'sessions': [cluster(members)]}, {'I1':'a', 'I2':'b'})

    def test_singletons_do_not_need_speculative_cues(self):
        value = validate_sessions({'sessions': [{'members':['I1'], 'reason':'无法并批'}]}, {'I1':'a'})
        self.assertTrue(value[0]['repeated_setup_ambiguous'])

    def infer(self, primary, reversed_response, items=None):
        items = items or [item('a', 'front'), item('b', 'back')]
        with patch.object(SessionEvidence, 'ask', side_effect=[(primary, {}), (reversed_response, {})]):
            return SessionEvidence().sessions(items, [np.zeros((2, 2, 3))]*len(items))[0]

    def test_only_independent_cues_and_stable_membership_enable_propagation(self):
        raw = {'sessions':[cluster(['I1','I2'])]}
        self.assertTrue(self.infer(raw, raw)[0]['reliable'])
        raw = {'sessions':[cluster(['I1','I2'], strong=('outfit',))]}
        self.assertFalse(self.infer(raw, raw)[0]['reliable'])

    def test_repeated_setup_and_duplicate_view_are_not_reliable_sessions(self):
        raw = {'sessions':[cluster(['I1','I2'])]}
        raw['sessions'][0]['repeated_setup_ambiguous'] = True
        self.assertFalse(self.infer(raw, raw)[0]['reliable'])
        raw['sessions'][0]['repeated_setup_ambiguous'] = False
        self.assertFalse(self.infer(raw, raw, [item('a'), item('b')])[0]['reliable'])

    def test_reverse_grouping_disagreement_and_phase_conflict_block_merge(self):
        raw = {'sessions':[cluster(['I1','I2'])]}
        reverse = {'sessions':[{'members':['I1'],'reason':'single'}, {'members':['I2'],'reason':'single'}]}
        self.assertFalse(self.infer(raw, reverse)[0]['reliable'])
        rows = [item('a','front','before'), item('b','back','after')]
        self.assertFalse(self.infer(raw, raw, rows)[0]['reliable'])


class ResolutionTests(unittest.TestCase):
    def setup_group(self):
        rows = [item('af','front'),item('ab','back'),item('as','side_right'),item('bf','front'),item('bb','back')]
        candidates = [{**cluster(['af','ab','as']), 'reliable': True}, {**cluster(['bf','bb']), 'reliable': True}]
        return rows, make_units(rows, candidates, 'g001')

    def test_two_complementary_subtle_views_label_sessions_and_uncompared_view(self):
        rows, units = self.setup_group()
        comparisons = [pair('p1',['af','bf'],strength='subtle'), pair('p2',['ab','bb'],strength='subtle',view='back')]
        edges = resolve(rows, units, comparisons)
        self.assertEqual(edges[0]['status'], 'accepted_multi_view')
        self.assertEqual([r['phase'] for r in rows], ['before','before','before','after','after'])
        self.assertEqual(rows[2]['phase_source'], 'session_visual_propagation')

    def test_one_subtle_view_remains_tentative_and_multiple_same_view_not_multiview(self):
        rows, units = self.setup_group()
        pairs = [pair('p1',['af','bf'],strength='subtle'),pair('p2',['ab','bb'],strength='subtle')]
        self.assertEqual(resolve(rows,units,pairs)[0]['status'], 'tentative')
        self.assertTrue(all(r['phase']=='unknown' for r in rows))

    def test_single_clear_view_can_label_with_reviewed_session_membership(self):
        rows, units = self.setup_group()
        resolve(rows,units,[pair('p1',['af','bf']),pair('p2',['ab','bb'],strength='subtle',view='back')])
        self.assertEqual(rows[2]['phase'], 'before')
        self.assertEqual(rows[0]['phase_source'],'paired_clear_observation')
        self.assertEqual(rows[1]['phase_source'],'session_visual_propagation')

    def test_cross_view_conflict_blocks_inference_instead_of_voting(self):
        rows, units = self.setup_group()
        pairs=[pair('p1',['af','bf']),pair('p2',['ab','bb'],after='A',view='back')]
        self.assertEqual(resolve(rows,units,pairs)[0]['status'],'cross_view_conflict')
        self.assertTrue(all(r['phase']=='unknown' for r in rows))

    def test_conflicting_observations_in_one_view_cannot_be_silently_ignored(self):
        rows,units=self.setup_group()
        veto=pair('p2',['ab','bb'],view='back')
        veto['decision'].update(after=None,strength='none',reason='observation_directions_conflict')
        edges=resolve(rows,units,[pair('p1',['af','bf']),veto])
        self.assertTrue(all(r['phase']=='unknown' for r in rows))
        self.assertIn('connected_assignment_conflict',[e['status'] for e in edges])

    def test_unreliable_session_never_propagates_to_other_views(self):
        rows, _ = self.setup_group(); units = make_units(rows,[], 'g001')
        resolve(rows,units,[pair('p1',['af','bf'])])
        self.assertEqual(rows[0]['phase'], 'before'); self.assertEqual(rows[1]['phase'], 'unknown')

    def test_known_phase_is_preserved_and_conflicting_edge_not_propagated(self):
        rows, units = self.setup_group(); rows[0]['phase']='before'
        resolve(rows,units,[pair('p1',['af','bf'],after='A')])
        self.assertEqual(rows[0]['phase'],'before'); self.assertEqual(rows[3]['phase'],'unknown')
        self.assertEqual(rows[3]['reason'],'session_assignment_conflict')

    def test_reliable_marker_propagates_only_within_reviewed_session(self):
        rows, units = self.setup_group(); rows[0]['phase']='before'
        resolve(rows,units,[])
        self.assertEqual(rows[2]['phase'],'before'); self.assertEqual(rows[3]['phase'],'unknown')

    def test_middle_capture_conflict_does_not_force_three_batches_into_two_labels(self):
        rows=[item('a'),item('b'),item('c')]; units=make_units(rows,[],'g001')
        edges=resolve(rows,units,[pair('p1',['a','b']),pair('p2',['b','c'])])
        self.assertTrue(all(r['phase']=='unknown' for r in rows))
        self.assertTrue(all(e['status']=='connected_assignment_conflict' for e in edges))


class PipelineTests(unittest.TestCase):
    def test_end_to_end_multiview_uses_original_uniform_and_keeps_sources(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); display=fixture(root,('front','back','side_right','front','back','side_right'))
            before={str(p):digest(p) for p in root.rglob('*') if p.is_file()}
            fake=FakeEvidence(); out=root/'result'
            counts=run(display,out,fake,workers=1)
            self.assertEqual(counts['phases'],{'before':3,'after':3})
            self.assertEqual(counts['reviewed_multi_image_sessions'],2)
            self.assertTrue(all(255 not in images for images in fake.seen))
            self.assertTrue(all(digest(path)==h for path,h in before.items()))
            with self.assertRaises(FileExistsError):run(display,out,fake)
            (root/'batch/input/a000.png').write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError,'input_fingerprint_changed'):load(display)

    def test_side_candidates_with_different_upstream_labels_are_visually_checked(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); display=fixture(root,('side_left','side_right'))
            fake=FakeEvidence(split=1,strength='clear'); run(display,root/'result',fake,workers=1)
            self.assertEqual(len(fake.seen),1)

    def test_transport_failure_keeps_all_rows_reviewable(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); display=fixture(root)
            with patch.object(SessionEvidence,'ask',side_effect=ValueError('reference_http_503')):
                counts=run(display,root/'result',SessionEvidence(),workers=1)
            self.assertEqual(counts['phases'],{'unknown':2})
            self.assertGreater(counts['model']['failed_stages'],0)

    def test_no_cross_member_or_cross_view_pairing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); display=fixture(root,('front','back','side_right'))
            fake=FakeEvidence(); run(display,root/'result',fake,workers=1)
            self.assertFalse(fake.seen)

    def test_camera_time_conflict_disables_session_merge(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); display=fixture(root,('front','back'))
            rows,_,_=load(display)
            times=[{'datetime_original':'2026-10-01T10:00:00'}, {'datetime_original':'2026-10-10T10:00:00'}]
            with patch('scripts.body_scan_phase_sessions.pipeline.capture_metadata',side_effect=times):
                _,group=process_group('g001',rows,FakeEvidence())
            self.assertEqual(group['session_candidates'][0]['reliability_reason'],'camera_times_disagree')
            self.assertTrue(all(u['membership']=='single_image' for u in group['units']))


if __name__ == '__main__':
    unittest.main()

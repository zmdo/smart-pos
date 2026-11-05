import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np

from scripts.body_scan_phase.evidence import PhaseEvidence, validate
from scripts.body_scan_phase.inputs import digest, load, split_assignment
from scripts.body_scan_phase.pipeline import run, resolve, suggestions
from scripts.body_scan_phase.policy import panel_phase, text_phase
from scripts.body_scan_pairs.pipeline import prepare
from scripts.body_scan_pairs.tests import test_pairs as pair_fixtures
from scripts.body_scan_pairs.tests.test_pairs import FakeEvidence, FakeSubjects


def raw(before='A'):
    return {'comparable': True, 'same_view': True, 'same_pose': True, 'markers': {'A': '', 'B': ''},
            'signals': {key: {'before': before if key == 'shape' else 'unknown',
                             'confidence': .9 if key == 'shape' else .3, 'reason': '可见腰腹差异' if key == 'shape' else '不可判断'}
                        for key in ('shape', 'posture', 'muscle')},
            'before': before, 'confidence': .9, 'reason': '相同站姿下腰腹轮廓差异明显'}


class FakePhase:
    def __init__(self):
        self.calls = []

    def compare(self, images, view, threshold):
        self.calls.append((images, view))
        return validate(raw(), threshold), {'primary': {'result': raw(), 'request_count': 0, 'cached': True}}


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding='utf-8')


def fixture(root, views=('front', 'front'), names=None):
    display = root/'display'; job = root/'batch/job.json'; rows = []; assets = []
    (job.parent/'input').mkdir(parents=True)
    save(display/'config.json', {'version': 'body-scan-group-display-v2'})
    for i, view in enumerate(views):
        aid = f'a{i:03d}'; source = job.parent/'input'/((names[i] if names else aid)+'.png')
        cv2.imwrite(str(source), np.full((150, 100, 3), 30+i*30, np.uint8))
        uniform = display/'images'/aid/'uniform.png'; uniform.parent.mkdir(parents=True)
        cv2.imwrite(str(uniform), np.full((250, 100, 3), 60+i*30, np.uint8))
        # A stretched display derivative exists but must never be read for inference.
        cv2.imwrite(str(uniform.with_name('display.png')), np.full((250, 100, 3), 255, np.uint8))
        rows.append({'asset_id': aid, 'store': 'test', 'member': 'same', 'status': 'displayed',
                     'source': str(source), 'source_sha256': digest(source), 'input_directory': str(root/'standard'),
                     'upstream_report': {'classification': {'kind': 'body_scan', 'view': view, 'phase': 'unknown'}},
                     'output': {'uniform_sha256': digest(uniform)}})
        assets.append({'id': aid, 'path': source.name, 'store': 'test', 'member': 'same',
                       'class': {'kind': 'body_scan', 'view': view, 'phase': 'unknown'}})
    save(display/'summary.json', rows); save(job, {'assets': assets})
    save(root/'standard/config.json', {'job': str(job)})
    return display


class PhaseTests(unittest.TestCase):
    def test_left_right_overrides_conflicting_marker_but_retains_evidence(self):
        phase, evidence = panel_phase('left_right', 1, {'label_text': '训练后'})
        self.assertEqual(phase, 'before')
        self.assertTrue(evidence['marker_conflict'])
        self.assertEqual(evidence['observed_phase'], 'after')
        self.assertFalse(evidence['verified_chronology'])
        self.assertEqual(panel_phase('left_right', 2, {})[0], 'after')

    def test_vertical_panels_have_no_position_rule(self):
        self.assertEqual(panel_phase('top_bottom', 1, {})[0], 'unknown')
        self.assertEqual(panel_phase('top_bottom', 1, {'label_text': '训练后'})[0], 'after')

    def test_markers_require_unambiguous_literal_text(self):
        for text in ('NIKE PRO', 'before and after', '训练前后对比', None):
            self.assertEqual(text_phase(text), 'unknown')
        self.assertEqual(text_phase('训练前-正面'), 'before')

    def test_shape_posture_and_muscle_can_each_supply_evidence(self):
        for key in ('shape', 'posture', 'muscle'):
            data = raw()
            data['signals'][key], data['signals']['shape'] = data['signals']['shape'], data['signals'][key]
            self.assertEqual(validate(data)['before'], 'A')

    def test_conflicting_physical_signals_are_unknown(self):
        data = raw(); data['signals']['muscle'].update(before='B', confidence=.95)
        self.assertEqual(validate(data)['reason'], 'appearance_signals_conflict')

    def test_different_pose_or_view_and_low_confidence_are_unknown(self):
        for key in ('same_pose', 'same_view', 'comparable'):
            data = raw(); data[key] = False
            self.assertEqual(validate(data)['before'], 'unknown')
        data = raw(); data['confidence'] = .79
        self.assertEqual(validate(data)['before'], 'unknown')

    def test_invalid_model_data_rejected(self):
        for value in (True, float('nan'), 1.1, '0.95'):
            data = raw(); data['confidence'] = value
            with self.assertRaises(ValueError):
                validate(data)
        data = raw(); del data['signals']['muscle']
        with self.assertRaises(ValueError):
            validate(data)

    def test_explicit_visible_markers_take_precedence(self):
        data = raw(); data['markers'] = {'A': '训练后', 'B': '训练前'}
        self.assertEqual(validate(data)['before'], 'B')
        self.assertEqual(validate(data)['source'], 'vlm_explicit_markers')

    def test_swapped_order_must_agree_and_rejected_result_is_not_retried(self):
        model = PhaseEvidence(); images = [np.full((2, 2, 3), i, np.uint8) for i in range(4)]
        with patch.object(model, 'ask', side_effect=[(raw(), {}), (raw('B'), {})]) as ask:
            self.assertEqual(model.compare(images, 'front')[0]['before'], 'A')
            np.testing.assert_array_equal(ask.call_args_list[1].args[0][0], images[2])
        with patch.object(model, 'ask', side_effect=[(raw(), {}), (raw(), {})]):
            self.assertEqual(model.compare(images, 'front')[0]['reason'], 'swapped_review_disagrees')
        with patch.object(model, 'ask', return_value=(raw('unknown'), {})) as ask:
            self.assertEqual(model.compare(images, 'front')[0]['before'], 'unknown')
            self.assertEqual(ask.call_count, 1)

    def test_pairwise_conflicts_preserve_unknown(self):
        items = [{'asset_id': aid, 'phase': 'unknown'} for aid in ('a', 'b', 'c')]
        pairs = [{'pair_id': 'ab', 'asset_ids': ['a', 'b'], 'decision': validate(raw())},
                 {'pair_id': 'bc', 'asset_ids': ['b', 'c'], 'decision': validate(raw())}]
        resolve(items, pairs)
        self.assertEqual(items[1]['phase'], 'unknown')
        self.assertEqual(items[1]['reason'], 'pairwise_assignments_conflict')

    def test_failed_or_malformed_response_is_auditable(self):
        model = PhaseEvidence(); images = [np.zeros((2, 2, 3), np.uint8)]*4
        with patch.object(model, 'ask', return_value=({'bad': 'response'}, {'request_count': 1})):
            decision, audit = model.compare(images, 'front')
            self.assertEqual(decision['before'], 'unknown')
            self.assertEqual(audit['primary']['result'], {'bad': 'response'})
            self.assertEqual(audit['failed_stage'], 'primary')
        with patch.object(model, 'ask', side_effect=ValueError('reference_http_503')):
            self.assertEqual(model.compare(images, 'front')[1]['error'], 'reference_http_503')

    def test_swapped_confidence_failure_is_not_reported_as_opposite_order(self):
        model = PhaseEvidence(); swapped = raw('B'); swapped['confidence'] = .75
        with patch.object(model, 'ask', side_effect=[(raw(), {}), (swapped, {})]):
            decision, _ = model.compare([np.zeros((2, 2, 3), np.uint8)]*4, 'front')
            self.assertEqual(decision['reason'], 'swapped_review_insufficient')

    def test_reliable_marker_is_not_overwritten(self):
        items = [{'asset_id': 'a', 'phase': 'after'}, {'asset_id': 'b', 'phase': 'unknown'}]
        pairs = [{'pair_id': 'ab', 'asset_ids': ['a', 'b'], 'decision': validate(raw())}]
        resolve(items, pairs)
        self.assertEqual(items[0]['phase'], 'after')
        self.assertEqual(items[1]['phase'], 'unknown')

    def test_low_confidence_suggestion_does_not_become_an_accepted_label(self):
        items = [{'asset_id': 'a', 'phase': 'unknown'}, {'asset_id': 'b', 'phase': 'unknown'}]
        result = raw(); result['confidence'] = .55
        pairs = [{'pair_id': 'ab', 'asset_ids': ['a', 'b'], 'decision': validate(result),
                  'evidence': {'primary': {'result': result}}}]
        resolve(items, pairs); suggestions(items, pairs)
        self.assertEqual([r['phase'] for r in items], ['unknown', 'unknown'])
        self.assertEqual([r['suggestion']['phase'] for r in items], ['before', 'after'])
        pairs[0]['evidence']['swapped'] = {'result': raw()}
        fresh = [{'asset_id': 'a', 'phase': 'unknown'}, {'asset_id': 'b', 'phase': 'unknown'}]
        suggestions(fresh, pairs)
        self.assertFalse(any('suggestion' in r for r in fresh))
        pairs[0]['evidence'].pop('swapped')
        pairs[0]['resolution'] = 'conflicts_with_reliable_marker'
        suggestions(fresh, pairs)
        self.assertFalse(any('suggestion' in r for r in fresh))

    def test_end_to_end_source_binding_originals_and_uniform_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); display = fixture(root); model = FakePhase()
            before = {str(p): digest(p) for p in root.rglob('*') if p.is_file()}
            counts = run(display, root/'result', model)
            self.assertEqual(counts['phases'], {'before': 1, 'after': 1})
            self.assertEqual([int(im[0, 0, 0]) for im in model.calls[0][0]], [30, 60, 60, 90])
            for path, sha in before.items():
                self.assertEqual(digest(path), sha)
            with self.assertRaises(FileExistsError):
                run(display, root/'result', model)
            source = root/'batch/input/a000.png'; source.write_bytes(b'tampered')
            with self.assertRaisesRegex(ValueError, 'input_fingerprint_changed'):
                load(display)

    def test_different_members_or_views_do_not_pair(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); display = fixture(root, ('side_left', 'side_right', 'front'))
            model = FakePhase(); counts = run(display, root/'result', model)
            self.assertEqual(counts['phases'], {'unknown': 3}); self.assertEqual(len(model.calls), 0)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); display = fixture(root); rows = json.loads((display/'summary.json').read_text())
            job = root/'batch/job.json'; assets = json.loads(job.read_text())
            rows[1]['member'] = 'another'; assets['assets'][1]['member'] = 'another'
            save(display/'summary.json', rows); save(job, assets)
            model = FakePhase(); run(display, root/'result', model)
            self.assertEqual(len(model.calls), 0)

    def test_filename_markers_bypass_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); display = fixture(root, names=('训练后', '训练前')); model = FakePhase()
            counts = run(display, root/'result', model)
            self.assertEqual(counts['sources'], {'explicit_marker': 2}); self.assertEqual(len(model.calls), 0)

    def test_model_failure_becomes_review_without_dropping_images(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); display = fixture(root); model = FakePhase()
            with patch.object(model, 'compare', side_effect=ValueError('reference_http_503')):
                counts = run(display, root/'result', model)
            self.assertEqual(counts['phases'], {'unknown': 2})

    def test_duplicate_originals_not_compared(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); display = fixture(root)
            a = root/'batch/input/a000.png'; b = a.with_name('a001.png'); b.write_bytes(a.read_bytes())
            rows = json.loads((display/'summary.json').read_text()); rows[1]['source_sha256'] = digest(b)
            save(display/'summary.json', rows); model = FakePhase()
            self.assertEqual(run(display, root/'result', model)['phases'], {'unknown': 2})
            self.assertFalse(model.calls)

    def test_legacy_split_is_bound_to_pixels_and_real_layout(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); job, _ = pair_fixtures.PairTests().fixture(root)
            output = root/'split'; reports = prepare(job, output, evidence=FakeEvidence(), subjects=FakeSubjects())
            dataset = output/'dataset/job.json'; data = json.loads(dataset.read_text())
            # Simulate old reports with unknown phases and no new phase metadata.
            parent = reports[0]
            for child in parent['children']:
                child['phase'] = 'unknown'; child.pop('phase_evidence', None)
            save(output/'splits/pair/report.json', parent)
            child = parent['children'][0]; row = {**child, 'store': 'test', 'member': 'test'}
            phase, evidence = split_assignment(data['assets'][0], dataset, row, {})
            self.assertEqual(phase, 'before'); self.assertEqual(evidence['position'], 'left')
            tampered = copy.deepcopy(data['assets'][0]); tampered['pair_source']['panel_index'] = 2
            with self.assertRaisesRegex(ValueError, 'split_child_provenance_mismatch'):
                split_assignment(tampered, dataset, row, {})
            image = cv2.imread(child['source']); image[0, 0] = 0; cv2.imwrite(child['source'], image)
            with self.assertRaisesRegex(ValueError, 'input_fingerprint_changed'):
                split_assignment(data['assets'][0], dataset, row, {})


if __name__ == '__main__':
    unittest.main()

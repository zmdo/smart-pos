import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np

from scripts.body_scan_pairs.boundaries import (hard_candidates, rectangles, slice_image,
                                              translation, check_subjects)
from scripts.body_scan_pairs.evidence import PairEvidence, validate_layout, validate_classification
from scripts.body_scan_pairs.pipeline import prepare, sha
from scripts.body_scan_pairs.verify import verify


def layout(kind='hard', axis=0):
    value = {'is_pair': True, 'layout': 'left_right', 'confidence': .95,
             'seam': {'kind': kind, 'band': [.35, .35] if kind == 'hard' else [.32, .38]},
             'panels': [
                 {'bbox': [0, 0, .35, 1], 'subject_bbox': [.05, .15, .3, .9], 'phase': 'unknown', 'label_text': ''},
                 {'bbox': [.35, 0, 1, 1], 'subject_bbox': [.55, .15, .85, .9], 'phase': 'unknown', 'label_text': ''}]}
    if axis:
        value['layout'] = 'top_bottom'
        for p in value['panels']:
            for k in ('bbox', 'subject_bbox'):
                p[k] = [p[k][1], p[k][0], p[k][3], p[k][2]]
    return validate_layout(value)


def classification():
    return {'kind': 'body_scan', 'people': 1, 'is_comparison': False, 'view': 'front',
            'background': 'white_wall', 'wall_background': True, 'body_scan_pose': True,
            'training_activity': False, 'confidence': .95, 'phase': 'unknown'}


def composite(axis=0):
    im = np.full((320, 600, 3), (180, 190, 200), np.uint8)
    im[:, 210:] = (90, 130, 160)
    # Distinctive pixels make accidental resize, transpose or off-by-one visible.
    im[20:80, 35:75] = (41, 77, 19)
    im[90:230, 380:440] = (81, 11, 52)
    return im if axis == 0 else im.transpose(1, 0, 2).copy()


class FakeEvidence:
    def __init__(self, kind='hard', blend_review=False):
        self.kind = kind; self.blend_review = blend_review
        self.classify_calls = 0; self.review_calls = 0

    def layout(self, image):
        value = layout(self.kind)
        return value, {'result': value, 'cached': True, 'request_count': 0}

    def classify(self, image):
        self.classify_calls += 1
        value = classification()
        return value, {'result': value, 'cached': True, 'request_count': 0}

    def review_split(self, images):
        self.review_calls += 1
        value = {'accept': not self.blend_review, 'independent_photos': True,
                 'residual_other_photo': False, 'residual_blend': self.blend_review, 'new_subject_cut': False}
        return value['accept'], {'result': value}


class FakeSubjects:
    def locate(self, image, proposal):
        masks = []; boxes = []
        for x1, y1, x2, y2 in ((30, 40, 150, 290), (340, 40, 510, 290)):
            mask = np.zeros(image.shape[:2], bool); mask[y1:y2, x1:x2] = True
            masks.append(mask); boxes.append([x1, y1, x2, y2])
        return boxes, masks, {'source': 'test_fixture'}


class PairTests(unittest.TestCase):
    def fixture(self, root):
        (root/'input').mkdir()
        path = root/'input/pair.png'; cv2.imwrite(str(path), composite())
        job = root/'job.json'
        job.write_text(json.dumps({'assets': [{'id': 'pair', 'path': 'pair.png', 'store': 'test', 'member': 'test',
                                             'class': {'phase': 'both'}}]}))
        return job, path

    def test_off_center_join_not_people_or_image_midpoint(self):
        im = composite(); found = hard_candidates(im, layout())[0]
        self.assertEqual(found['cut'], 210)
        self.assertNotEqual(found['cut'], im.shape[1]//2)
        self.assertEqual(rectangles(im, layout(), found), [[0, 0, 210, 320], [210, 0, 600, 320]])

    def test_vertical_stack(self):
        im = composite(1); proposal = layout(axis=1)
        found = hard_candidates(im, proposal)[0]
        self.assertEqual(found['cut'], 210)
        self.assertEqual(rectangles(im, proposal, found), [[0, 0, 320, 210], [0, 210, 320, 600]])

    def test_no_visible_step_is_not_a_valid_seam(self):
        with self.assertRaisesRegex(ValueError, 'no_reliable'):
            hard_candidates(np.full((320, 600, 3), 180, np.uint8), layout())

    def test_grid_edge_with_partial_support_does_not_beat_seam(self):
        im = composite()
        im[:175, 219:222] = 0
        self.assertEqual(hard_candidates(im, layout())[0]['cut'], 210)

    def test_bad_or_ambiguous_layout_rejected(self):
        for change in ({'is_pair': False}, {'confidence': .5}, {'layout': 'overlap'}, {'panels': []},
                       {'seam': {'kind': 'unknown', 'band': [.35, .35]}}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate_layout({**layout(), **change})

    def test_nonfinite_coordinates_rejected(self):
        value = layout(); value['panels'][0]['bbox'][0] = float('nan')
        with self.assertRaises(ValueError):
            validate_layout(value)

    def test_subject_order_conflict_rejected(self):
        value = layout(); value['panels'].reverse()
        with self.assertRaisesRegex(ValueError, 'order'):
            validate_layout(value)

    def test_phase_requires_explicit_text_not_position_or_brand(self):
        value = layout(); value['panels'][0].update(phase='before', label_text='MAGIC')
        self.assertEqual(validate_layout(value)['panels'][0]['phase'], 'unknown')
        value['panels'][0]['label_text'] = '训练前'
        self.assertEqual(validate_layout(value)['panels'][0]['phase'], 'before')

    def test_confident_feather_layout_needs_no_more_model_calls(self):
        evidence = PairEvidence('/unused')
        with patch.object(evidence, 'ask', return_value=(layout('feather'), {})) as ask:
            result, _ = evidence.layout(composite())
        self.assertEqual(ask.call_count, 1)
        self.assertEqual(result['seam']['kind'], 'feather')

    def test_detail_identifying_feather_overrides_coarse_hard(self):
        evidence = PairEvidence('/unused')
        outputs = [(layout(), {}), ({'kind': 'feather', 'band': [.32, .38], 'confidence': .95, 'reason': 'mixed'}, {})]
        with patch.object(evidence, 'ask', side_effect=outputs) as ask:
            result, trace = evidence.layout(composite())
        self.assertEqual(ask.call_count, 2)
        self.assertEqual(result['seam']['kind'], 'feather')
        self.assertIn('detail', trace)

    def test_uncertain_detail_fails_closed_without_more_votes(self):
        evidence = PairEvidence('/unused')
        outputs = [(layout(), {}), ({'kind': 'unknown', 'confidence': .3}, {})]
        with patch.object(evidence, 'ask', side_effect=outputs) as ask:
            with self.assertRaisesRegex(ValueError, 'seam_detail_uncertain') as error:
                evidence.layout(composite())
        self.assertEqual(ask.call_count, 2)
        self.assertIn('detail', error.exception.evidence)

    def test_soft_transition_does_not_become_a_hard_cut(self):
        image = np.full((320, 600, 3), 180, np.uint8)
        for x in range(600):
            image[:, x] = round(180-80*np.clip((x-180)/60, 0, 1))
        with self.assertRaisesRegex(ValueError, 'no_reliable'):
            hard_candidates(image, layout())

    def test_child_is_independently_filtered(self):
        self.assertEqual(validate_classification(classification())['view'], 'front')
        for change in ({'people': 2}, {'wall_background': False}, {'training_activity': True},
                       {'confidence': .4}, {'view': None}, {'phase': 'both'}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate_classification({**classification(), **change})

    def test_new_subject_cut_fails_but_existing_source_crop_is_allowed(self):
        mask = np.zeros((320, 600), bool); mask[50:320, 20:200] = True
        check_subjects([[0, 0, 210, 320]], [[20, 50, 200, 320]], [mask], mask.shape)
        with self.assertRaisesRegex(ValueError, 'cuts_subject'):
            check_subjects([[0, 0, 180, 320]], [[20, 50, 200, 320]], [mask], mask.shape)

    def test_lossless_slice_and_coordinate_roundtrip(self):
        image = composite(); rect = [210, 13, 599, 319]
        child = slice_image(image, rect)
        np.testing.assert_array_equal(child[0, 0], image[13, 210])
        point = np.array([317., 82., 1.])
        np.testing.assert_array_equal(translation(rect)@point, [107, 69, 1])
        np.testing.assert_allclose(np.linalg.inv(translation(rect))@translation(rect)@point, point)
        child[:] = 0
        self.assertTrue(image[13:319, 210:599].any())

    def test_blend_skipped_before_yolo_sam_classification_or_child_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); job, source = self.fixture(root); before = sha(source)
            evidence = FakeEvidence('feather')
            subjects = FakeSubjects()
            with patch.object(subjects, 'locate', side_effect=AssertionError('must not infer')):
                rows = prepare(job, root/'result', evidence=evidence, subjects=subjects)
            self.assertEqual(rows[0]['status'], 'skipped')
            self.assertEqual(rows[0]['reason'], 'feathered_composite_not_supported')
            self.assertIn('渐变', rows[0]['reason_zh'])
            self.assertEqual(evidence.classify_calls+evidence.review_calls, 0)
            self.assertEqual(list((root/'result/dataset/input').iterdir()), [])
            self.assertEqual(sha(source), before)
            self.assertEqual(verify(root/'result')['ready_children'], 0)

    def test_review_discovering_blend_also_eliminates_pair(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); job, _ = self.fixture(root)
            evidence = FakeEvidence(blend_review=True)
            rows = prepare(job, root/'result', evidence=evidence, subjects=FakeSubjects())
            self.assertEqual(rows[0]['status'], 'skipped')
            self.assertEqual(rows[0]['reason'], 'feathered_composite_not_supported')
            self.assertEqual(evidence.classify_calls, 0)
            self.assertEqual(list((root/'result/dataset/input').iterdir()), [])

    def test_end_to_end_job_provenance_tampering_and_output_protection(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); job, _ = self.fixture(root)
            evidence = FakeEvidence(); out = root/'result'
            rows = prepare(job, out, evidence=evidence, subjects=FakeSubjects())
            self.assertEqual(evidence.classify_calls, 2)
            self.assertEqual(rows[0]['status'], 'split_ready')
            self.assertEqual([c['phase'] for c in rows[0]['children']], ['before', 'after'])
            dataset = json.loads((out/'dataset/job.json').read_text())
            self.assertEqual([a['class']['phase'] for a in dataset['assets']], ['before', 'after'])
            self.assertEqual(dataset['assets'][0]['pair_source']['layout'], 'left_right')
            self.assertEqual(dataset['assets'][0]['phase_evidence']['source'], 'comparison_position_rule')
            self.assertEqual(verify(out)['verified_lossless_children'], 2)
            with self.assertRaises(FileExistsError):
                prepare(job, out, evidence=evidence, subjects=FakeSubjects())
            path = out/'dataset/input/pair__p01.png'
            im = cv2.imread(str(path)); im[0, 0] = 0; cv2.imwrite(str(path), im)
            with self.assertRaisesRegex(ValueError, 'child_source_changed'):
                verify(out)


if __name__ == '__main__':
    unittest.main()

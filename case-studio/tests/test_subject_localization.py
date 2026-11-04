"""Routing, geometry and bounded/cached VLM requests; no GPU/API in unit tests."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from subject_localization import (CoarseBoxProvider, LocalizationError, SubjectLocalizer,
                                  expanded_roi, merge_duplicates, validate_hint)

LABELS = {'people': 1, 'phase': 'unknown', 'kind': 'body_scan', 'background': 'grid_board'}
BOX = [180., 100., 420., 900.]


def candidate(box=BOX, confidence=.8):
    return {'box': list(box), 'confidence': confidence}


def segment(img, boxes):
    result = []
    for x1, y1, x2, y2 in boxes:
        mask = np.zeros(img.shape[:2], np.uint8)
        cv2.ellipse(mask, (round((x1+x2)/2), round((y1+y2)/2)),
                    (round((x2-x1)*.45), round((y2-y1)*.48)), 0, 0, 360, 1, -1)
        result.append(mask.astype(bool))
    return result


class SubjectLocalizationTests(unittest.TestCase):
    def setUp(self):
        self.img = np.full((1000, 600, 3), 200, np.uint8)

    def unexpected_hint(self, img):
        self.fail('Successful local detection must not call VLM')

    def hint(self, img):
        return list(BOX), {'box': list(BOX), 'request_count': 1, 'cached': False}

    def test_fast_path_does_not_request_vlm(self):
        calls = []
        def detect(img, size, confidence):
            calls.append((size, confidence))
            return [candidate()]
        s = SubjectLocalizer(detect, segment, self.unexpected_hint).localize(self.img, LABELS)
        self.assertEqual(calls, [(1024, .35)])
        self.assertEqual(s.trace['route'], 'yolo_full')
        self.assertEqual(s.trace['vlm']['request_count'], 0)
        self.assertEqual(s.box, BOX)

    def test_size_retry_recovers_missed_subject_without_vlm(self):
        calls = []
        def detect(img, size, confidence):
            calls.append(size)
            return [candidate()] if size == 640 else []
        s = SubjectLocalizer(detect, segment, self.unexpected_hint).localize(self.img, LABELS)
        self.assertEqual(calls, [1024, 640])
        self.assertEqual(s.trace['route'], 'yolo_retry')

    def test_duplicate_body_boxes_are_unioned(self):
        def detect(*args):
            return [candidate([180, 100, 420, 800]), candidate([182, 250, 422, 900], .6)]
        s = SubjectLocalizer(detect, segment, self.unexpected_hint).localize(self.img, LABELS)
        self.assertEqual(s.box, [180., 100., 422., 900.])
        self.assertEqual(s.trace['attempts'][0]['subject_groups'][0]['members'], 2)

    def test_separate_people_are_not_merged(self):
        self.assertEqual(len(merge_duplicates([candidate([10, 100, 240, 900]),
                                               candidate([330, 100, 580, 900])])), 2)

    def test_roi_detections_map_back_to_original_image(self):
        hint_calls, segmentation_shapes = [], []
        roi = expanded_roi(BOX, self.img.shape, .2)
        def detect(img, size, confidence):
            if img.shape[1] == 600:
                return []
            return [candidate([BOX[0]-roi[0], BOX[1]-roi[1], BOX[2]-roi[0], BOX[3]-roi[1]])]
        def hint(img):
            hint_calls.append(1)
            return self.hint(img)
        def segmentation(img, boxes):
            segmentation_shapes.append(img.shape)
            return segment(img, boxes)
        s = SubjectLocalizer(detect, segmentation, hint).localize(self.img, LABELS)
        self.assertEqual(s.box, BOX)
        self.assertEqual(s.trace['route'], 'vlm_yolo_roi')
        self.assertEqual(hint_calls, [1])
        self.assertEqual(segmentation_shapes, [self.img.shape])

    def test_candidate_touching_crop_edge_retries_larger_roi(self):
        box = [180., 200., 420., 800.]
        def hint(img):
            return box, {'box': box, 'request_count': 1, 'cached': False}
        def detect(img, size, confidence):
            if img.shape[1] == 600:
                return []
            if img.shape[1] == 336:
                return [candidate([0, 120, 288, 720])]
            return [candidate([96, 200, 336, 800])]
        s = SubjectLocalizer(detect, segment, hint).localize(self.img, LABELS)
        self.assertEqual(s.box, box)
        self.assertEqual(s.trace['route'], 'vlm_yolo_roi')
        self.assertIn('subject_touches_crop_edge', [a.get('reason') for a in s.trace['attempts']])

    def test_direct_sam_fallback_after_all_yolo_attempts(self):
        calls = []
        def detect(*args):
            calls.append(1)
            return []
        s = SubjectLocalizer(detect, segment, self.hint).localize(self.img, LABELS)
        self.assertEqual(len(calls), 7)
        self.assertEqual(s.trace['route'], 'vlm_sam')

    def test_rectangle_fallback_cannot_validate_a_vlm_only_box(self):
        def rectangles(img, boxes):
            result = []
            for b in boxes:
                m = np.zeros(img.shape[:2], bool)
                x1, y1, x2, y2 = map(int, b)
                m[y1:y2, x1:x2] = True
                result.append(m)
            return result
        with self.assertRaises(LocalizationError) as error:
            SubjectLocalizer(lambda *a: [], rectangles, self.hint).localize(self.img, LABELS)
        self.assertEqual(error.exception.trace['sam_fallback_error'], 'segmentation_is_rectangle_fallback')

    def test_background_mask_cannot_validate_the_person_hint(self):
        def background_mask(img, boxes):
            return segment(img, [[20, 20, 580, 980] for _ in boxes])
        with self.assertRaises(LocalizationError) as error:
            SubjectLocalizer(lambda *a: [], background_mask, self.hint).localize(self.img, LABELS)
        self.assertEqual(error.exception.trace['sam_fallback_error'], 'segmentation_outside_subject_region')

    def test_comparison_and_non_grid_never_enter_detection(self):
        def fail(*args):
            self.fail('Excluded scene must not enter inference or HTTP')
        for changes in ({'phase': 'both'}, {'people': 2}, {'background': 'wood'}):
            with self.assertRaisesRegex(LocalizationError, 'scene_not_eligible'):
                SubjectLocalizer(fail, fail, fail).localize(self.img, {**LABELS, **changes})

    def test_ambiguous_vlm_response_stops_without_relabeling_scene(self):
        original = dict(LABELS)
        def hint(img):
            raise LocalizationError('vlm_subject_classification_conflict')
        with self.assertRaisesRegex(LocalizationError, 'classification_conflict'):
            SubjectLocalizer(lambda *a: [], segment, hint).localize(self.img, LABELS)
        self.assertEqual(LABELS, original)

    def test_invalid_normalized_boxes_are_rejected(self):
        valid = {'people': 1, 'is_comparison': False, 'bbox': [.2, .1, .8, .9], 'confidence': .9}
        for changes in ({'bbox': [200, 100, 800, 900]}, {'bbox': [.8, .1, .2, .9]},
                        {'bbox': [0, 0, float('nan'), 1]}, {'bbox': None},
                        {'confidence': .2}, {'people': 2}, {'is_comparison': True}):
            with self.subTest(changes=changes), self.assertRaises(LocalizationError):
                validate_hint({**valid, **changes})

    def test_vlm_hint_cache_uses_image_and_model_without_storing_credentials(self):
        cfg = {'base_url': 'https://example.invalid/v1', 'model': 'vision-test', 'api_key': 'test-secret-not-for-disk'}
        calls = []
        def request(img, config):
            calls.append(1)
            return {'people': 1, 'is_comparison': False, 'bbox': [.3, .1, .7, .9], 'confidence': .9}
        with tempfile.TemporaryDirectory() as folder:
            provider = CoarseBoxProvider(folder, lambda: cfg, request)
            first, metadata = provider(self.img)
            second, cached = provider(self.img)
            self.assertEqual(first, BOX)
            self.assertEqual(first, second)
            self.assertEqual(metadata['request_count'], 1)
            self.assertEqual(cached['request_count'], 0)
            self.assertTrue(cached['cached'])
            self.assertEqual(len(calls), 1)
            modified = self.img.copy()
            modified[0, 0] = 1
            provider(modified)
            cfg['model'] = 'another-model'
            provider(self.img)
            self.assertEqual(len(calls), 3)
            for p in Path(folder).rglob('*.json'):
                self.assertNotIn(cfg['api_key'], p.read_text())

    def test_failed_vlm_request_is_counted_and_not_retried(self):
        cfg = {'base_url': 'https://example.invalid/v1', 'model': 'vision-test', 'api_key': 'test-only'}
        calls = []
        def request(*args):
            calls.append(1)
            raise LocalizationError('vlm_http_503')
        with tempfile.TemporaryDirectory() as folder:
            provider = CoarseBoxProvider(folder, lambda: cfg, request)
            with self.assertRaises(LocalizationError) as error:
                SubjectLocalizer(lambda *a: [], segment, provider).localize(self.img, LABELS)
            self.assertEqual(calls, [1])
            self.assertEqual(error.exception.trace['vlm']['request_count'], 1)
            self.assertEqual(error.exception.trace['vlm']['error'], 'vlm_http_503')


if __name__ == '__main__':
    unittest.main()

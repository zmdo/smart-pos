import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import classify


class WallClassificationTests(unittest.TestCase):
    def result(self, **changes):
        return classify.normalize({'kind': 'body_scan', 'background': 'wood', 'view': 'back',
                                   'wall_background': True, 'body_scan_pose': True,
                                   'training_activity': False, 'people': 1, **changes})

    def test_wall_and_static_pose_are_required(self):
        self.assertEqual(self.result()['kind'], 'body_scan')
        for change in ({'wall_background': False}, {'wall_background': None},
                       {'wall_background': 'true'}, {'body_scan_pose': False},
                       {'body_scan_pose': None}):
            result = self.result(**change)
            self.assertEqual(result['kind'], 'other')
            self.assertIsNone(result['view']); self.assertIsNone(result['background'])

    def test_training_in_front_of_wall_is_still_training(self):
        self.assertEqual(self.result(training_activity=True)['kind'], 'daily_training')

    def test_open_gym_training_cannot_enter_body_scan(self):
        result = self.result(background='mirror', wall_background=False, training_activity=True)
        self.assertEqual(result['kind'], 'daily_training')

    def test_contradictory_background_is_rejected(self):
        for background in ('mirror', 'outdoor'):
            self.assertEqual(self.result(background=background)['kind'], 'other')

    def test_wall_poster_and_partial_body_remain_eligible(self):
        self.assertEqual(self.result(background='other')['kind'], 'body_scan')

    def test_missing_evidence_cannot_silently_reuse_old_labels(self):
        self.assertEqual(classify.normalize({'kind': 'body_scan', 'people': 1})['kind'], 'other')

    def test_old_prompt_cache_is_invalidated(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(classify, 'CACHE', Path(tmp)):
            path = classify._cache_path('abcdef'); path.parent.mkdir(parents=True)
            path.write_text('{"prompt_version":"cls-v2","result":{"kind":"body_scan"}}')
            self.assertIsNone(classify.cached('abcdef'))


if __name__ == '__main__':
    unittest.main()

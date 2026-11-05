import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import cv2
import numpy as np

from .. import pipeline, refinement
from ..background_screening import BackgroundScreening, POSTER_REASON, VERSION
from ..framing import UniformConfig


LABELS = {'kind': 'body_scan', 'people': 1, 'view': 'side_right', 'background': 'other',
          'wall_background': True, 'body_scan_pose': True}


def checker(background='poster_wall', confidence=.95):
    evidence = Mock()
    evidence.ask.return_value = ({'primary_background': background, 'confidence': confidence,
                                 'reason': '主体身后为人物广告海报'}, {'cached': False, 'request_count': 1})
    return BackgroundScreening(evidence), evidence


class BackgroundScreeningTests(unittest.TestCase):
    def setUp(self):
        self.image = np.full((80, 60, 3), 128, np.uint8)

    def fixture(self, root):
        source = root/'input'; source.mkdir()
        cv2.imwrite(str(source/'photo.png'), self.image)
        asset = {'id': 'a', 'path': 'photo.png', 'store': '店', 'member': '人', 'class': LABELS.copy()}
        return source, asset

    def test_poster_skips_before_localization_geometry_or_pose_and_keeps_labels(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); source, asset = self.fixture(root); out = root/'out'; out.mkdir()
            screening, evidence = checker(); localizer, pose, geometry = Mock(), Mock(), Mock()
            row = pipeline.process(asset, source, out, localizer, pose, UniformConfig(), geometry, screening)
            self.assertEqual((row['status'], row['reason']), ('skipped', POSTER_REASON))
            self.assertEqual(row['classification']['kind'], 'body_scan')
            self.assertEqual(asset['class'], LABELS)
            self.assertEqual(row['stopped_at'], 'standardization_background_screening')
            self.assertEqual(row['background_screening']['source_sha256'],
                             hashlib.sha256((source/'photo.png').read_bytes()).hexdigest())
            self.assertTrue(row['reason_detail'])
            self.assertEqual(json.loads((out/'a/report.json').read_text()), row)
            self.assertFalse((out/'a/aligned.png').exists())
            localizer.localize.assert_not_called(); pose.locate.assert_not_called(); geometry.assert_not_called()
            evidence.ask.assert_called_once()

    def test_plain_grid_wood_and_other_wall_continue_to_localization(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); source, asset = self.fixture(root)
            for background in ('plain_wall', 'grid_wall', 'wood_wall', 'other_wall'):
                with self.subTest(background=background):
                    screening, _ = checker(background)
                    localizer = Mock(); localizer.localize.side_effect = ValueError('localization_reached')
                    row = pipeline.process(asset, source, root/'out', localizer, Mock(), UniformConfig(),
                                           background_screening=screening)
                    self.assertEqual(row['reason'], 'localization_reached')
                    self.assertEqual(row['background_screening']['status'], 'allowed')
                    localizer.localize.assert_called_once()

    def test_uncertain_and_invalid_evidence_never_silently_pass(self):
        for background, confidence in [('unknown', .99), ('poster_wall', .79), ('wood_wall', True),
                                       ('plain_wall', float('nan')), ('grid_wall', 2), ('unexpected', .9)]:
            with self.subTest(background=background, confidence=confidence):
                screening, _ = checker(background, confidence)
                row = screening.check(self.image, 'sha')
                self.assertEqual(row['status'], 'needs_review')
        screening, evidence = checker()
        evidence.ask.return_value = ({'primary_background': 'plain_wall', 'confidence': .95}, {})
        self.assertEqual(screening.check(self.image, 'sha')['status'], 'needs_review')

    def test_request_failure_is_reviewable_and_error_text_is_not_leaked(self):
        screening, evidence = checker()
        evidence.ask.side_effect = ValueError('sensitive provider response')
        row = screening.check(self.image, 'sha')
        self.assertEqual(row['status'], 'needs_review')
        self.assertEqual(row['reason'], 'standardization_background_check_failed')
        self.assertNotIn('sensitive', json.dumps(row))

    def test_upstream_ineligible_image_does_not_call_screening(self):
        screening, evidence = checker()
        row = pipeline.process({'id': 'a', 'class': {'kind': 'daily_training'}}, Path('/missing'),
                               Path('/missing'), Mock(), Mock(), UniformConfig(), background_screening=screening)
        self.assertEqual(row['reason'], 'not_body_scan'); evidence.ask.assert_not_called()

    def test_refinement_of_old_baseline_cannot_bypass_poster_rule(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); source, asset = self.fixture(root); base = root/'base'; base.mkdir()
            (base/'a').mkdir(); (base/'a/aligned.png').write_bytes(b'old approved output')
            row = {'asset_id': 'a', 'classification': LABELS, 'store': '店', 'member': '人',
                   'status': 'rectangular', 'route': 'non_grid', 'source': str(source/'photo.png'),
                   'source_sha256': hashlib.sha256((source/'photo.png').read_bytes()).hexdigest()}
            (base/'summary.json').write_text(json.dumps([row]))
            (base/'config.json').write_text(json.dumps({'version': 'body-scan-unified-v2-pinhole',
                'non_grid_transform': 'pinhole', 'width': 768, 'height': 1792, 'torso_fraction': .27,
                'shoulder_y': .23, 'background_rgb': [238, 234, 227]}))
            (base/'groups.json').write_text(json.dumps([{'group_id': 'g001', 'asset_ids': ['a']}]))
            screening, _ = checker(); evidence = Mock(); out = root/'out'
            with patch.object(refinement, 'make_previews'):
                rows = refinement.run(base, out, evidence, background_screening=screening)
            self.assertEqual(rows[0]['reason'], POSTER_REASON)
            self.assertFalse((out/'a/aligned.png').exists())
            self.assertEqual((base/'a/aligned.png').read_bytes(), b'old approved output')
            evidence.scene.assert_not_called()
            self.assertEqual(json.loads((out/'config.json').read_text())['background_screening_version'], VERSION)

    def test_preview_shows_exclusion_reason_and_escapes_model_text(self):
        from ..preview import make_previews
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            make_previews(root, [{'asset_id': 'a', 'status': 'skipped', 'reason': POSTER_REASON,
                'store': '店', 'member': '人', 'reason_detail': '海报背景 <script>alert(1)</script>'}],
                [], Path('/no-font'))
            page = (root/'index.html').read_text()
            self.assertIn('已跳过', page); self.assertIn('海报背景', page)
            self.assertNotIn('<script>', page)


if __name__ == '__main__':
    unittest.main()

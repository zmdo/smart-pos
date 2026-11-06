import copy
import json
import tempfile
import unittest
from pathlib import Path
import cv2
import numpy as np
from scripts.body_scan_cover_frames.geometry import plan_pair, project
from scripts.body_scan_cover_frames.pipeline import render, run, save, sha


def meta(aid='a1', top=0, width=1200, tilt=0):
    H = [[1, tilt, -width/2], [0, 1, -400], [0, 0, 1]]
    points = [[0, -200]]*17
    for i, p in {5: [-130, 0], 6: [130, 0], 11: [-90, 450], 12: [90, 450]}.items():
        points[i] = p
    return {'asset_id': aid, 'store': '测试店', 'member': '测试', 'status': 'displayed',
            'H_source_to_normalized': H, 'H_aligned_to_normalized': np.eye(3).tolist(),
            'upstream_report': {'size': [width, 1800], 'subject_box': [width/2-200, 150, width/2+200, 1700],
                'frame': {'source_content_bounds_xyxy': [0, top, width, 1800],
                          'H_source_to_aligned': H, 'H_corrected_to_aligned': np.eye(3).tolist()}},
            'keypoints_normalized': points, 'keypoint_confidence': [.99]*17,
            'visible_bounds_normalized': [-200, -280, 200, 1300],
            'visibility': {'head': 'complete', 'lower_extent': 'feet_cut'}}


class FrameTests(unittest.TestCase):
    def test_two_sources_share_scale_frame_and_shoulder(self):
        plans = plan_pair([meta(), meta('a2', width=1050)])
        self.assertEqual(plans[0]['shared_pair_size'], plans[1]['shared_pair_size'])
        self.assertEqual(plans[0]['neutral_shoulder_output'], plans[1]['neutral_shoulder_output'])
        self.assertGreater(plans[0]['shared_pair_size'][0], 768)
        for p in plans:
            self.assertAlmostEqual(p['scale_x'], p['scale_y'])
            self.assertFalse(p['new_head_crop'])

    def test_six_image_crop_and_stretch_are_not_inputs(self):
        pair = [meta(), meta('a2')]; expected = plan_pair(pair)
        for m in pair:
            m['normalized_bounds'] = [-20, 0, 20, 100]
            m['group_plan'] = {'H_normalized_to_display': [[1, 0, 0], [0, 4, 0], [0, 0, 1]]}
        self.assertEqual(expected, plan_pair(pair))

    def test_original_cut_head_does_not_cut_other_complete_head(self):
        cut = meta(top=350); cut['visibility']['head'] = 'cut'
        plans = plan_pair([cut, meta('a2')])
        self.assertTrue(plans[0]['shoulder_alignment_relaxed'])
        self.assertTrue(plans[0]['head_already_incomplete'])
        self.assertFalse(plans[1]['new_head_crop'])

    def test_perspective_footprint_and_real_pixels(self):
        with tempfile.TemporaryDirectory() as d:
            m = meta(tilt=.08); m['source'] = str(Path(d)/'source.png')
            cv2.imwrite(m['source'], np.full((1800, 1200, 3), 170, np.uint8))
            p = plan_pair([m, meta('a2')])[0]; image, valid = render(m, p)
            self.assertTrue(np.all(valid == 255)); self.assertTrue(np.all(image == 170))

    def test_cannot_sample_neighbouring_panel(self):
        with tempfile.TemporaryDirectory() as d:
            m = meta(width=1200); m['source'] = str(Path(d)/'source.png')
            image = np.zeros((1800, 1200, 3), np.uint8); image[:, :800] = [50, 80, 110]; image[:, 800:] = [255, 0, 255]
            cv2.imwrite(m['source'], image)
            m['upstream_report']['frame']['source_content_bounds_xyxy'][2] = 800
            p = plan_pair([m, m])[0]; result, _ = render(m, p)
            self.assertTrue(np.all(result == [50, 80, 110]))

    def test_anisotropic_upstream_scale_rejected(self):
        m = meta(); m['upstream_report']['frame']['H_corrected_to_aligned'][1][1] = 1.1
        with self.assertRaisesRegex(ValueError, 'uniform'):
            plan_pair([m, meta('a2')])

    def test_almost_vertical_edges_do_not_move_subject_down_for_subpixel_gain(self):
        first = meta(); second = meta('a2', width=1100, tilt=.00002)
        plans = plan_pair([first, second])
        self.assertFalse(plans[0]['shoulder_alignment_relaxed'])
        self.assertEqual(plans[0]['neutral_shoulder_output'], plans[1]['neutral_shoulder_output'])
        self.assertGreater(plans[1]['crop_xyxy_normalized'][1], -350)

    def test_narrow_source_uses_available_asymmetric_margins(self):
        m = meta(width=650)
        m['H_source_to_normalized'][0][2] = -380
        m['upstream_report']['frame']['H_source_to_aligned'][0][2] = -380
        plans = plan_pair([m, m])
        self.assertGreater(plans[0]['shared_pair_size'][0], 600)
        self.assertLess(abs(plans[0]['horizontal_center_normalized']), 75)

    def test_model_and_stage_are_not_recomputed_and_stale_rows_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); metadata = []; stages = []
            for i, phase in enumerate(['before', 'after']):
                m = meta('a'+str(i)); path = root/(m['asset_id']+'.png')
                cv2.imwrite(str(path), np.full((1800, 1200, 3), 170+i, np.uint8))
                m.update(source=str(path), source_sha256=sha(path)); metadata.append(m)
                stages.append({'asset_id': m['asset_id'], 'source_sha256': m['source_sha256'], 'group_id': 'g001',
                               'store': '测试店', 'member': '测试', 'view': 'front', 'phase': phase,
                               'requires_review': True, 'label': phase+'（推断）', 'confidence': .61})
            save(root/'summary.json', metadata); save(root/'result.json', {'items': stages})
            request = {'version': 'cover-frame-request-v1', 'gaps': [], 'review_target': {'base_revision': 1},
                'phase_result': {'path': str(root/'result.json'), 'sha256': sha(root/'result.json')},
                'pairs': [{'group_id': 'g001', 'store': '测试店', 'member': '测试', 'assets': [
                    {'stage': s, 'display_summary': {'path': str(root/'summary.json'), 'sha256': sha(root/'summary.json')}} for s in stages]}]}
            save(root/'request.json', request); result = run(root/'request.json', root/'out')
            self.assertEqual(result['model_requests'], 0); self.assertEqual(len(result['cases']), 1)
            self.assertEqual([f['stage'] for f in result['cases'][0]['frames']], stages)
            request['pairs'][0]['assets'][0]['stage']['confidence'] = .99
            save(root/'changed.json', request); changed = run(root/'changed.json', root/'stale')
            self.assertFalse(changed['cases']); self.assertIn('snapshot_mismatch', changed['gaps'][0]['reason'])


if __name__ == '__main__':
    unittest.main()

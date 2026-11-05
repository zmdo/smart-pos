import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import httpx
import numpy as np

from scripts.body_scan_full_eval.client import MeasuredClient
from scripts.body_scan_full_eval.sweep import is_reference
from scripts.body_scan_phase_sessions.client import ModelCallFailure


def response(value, status=200):
    result = Mock(status_code=status)
    result.json.return_value = {'model': 'returned-alias', 'usage': {'prompt_tokens': 100, 'completion_tokens': 20},
        'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps(value)}}]}
    return result


class MeasuredTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.settings = self.root/'settings.json'
        self.settings.write_text(json.dumps({'base_url': 'https://example.invalid/v1', 'model': 'vision', 'api_key': 'PRIVATE-TEST-KEY'}))
        self.cache = self.root/'cache'
        self.image = np.zeros((12, 12, 3), np.uint8)
        self.transport = Mock()
        self.transport.__enter__ = Mock(return_value=self.transport)
        self.transport.__exit__ = Mock(return_value=False)
        self.transport.post.return_value = response({'ok': True})
        self.patcher = patch('scripts.body_scan_full_eval.client.httpx.Client', return_value=self.transport)
        self.patcher.start(); self.addCleanup(self.patcher.stop)

    def test_provider_options_are_separate_and_pixels_identical(self):
        for provider in ('qwen', 'deepseek'):
            MeasuredClient(self.settings, self.cache, provider).ask([self.image], 'prompt', 'v1')
        qwen, deepseek = [call.kwargs['json'] for call in self.transport.post.call_args_list]
        self.assertFalse(qwen['enable_thinking']); self.assertNotIn('thinking', qwen)
        self.assertEqual(deepseek['thinking'], {'type': 'disabled'}); self.assertNotIn('enable_thinking', deepseek)
        self.assertEqual(qwen['messages'], deepseek['messages'])
        self.assertEqual(len(list((self.cache/'history').glob('*.json'))), 2)

    def test_successful_cache_replay_adds_no_billed_call(self):
        client = MeasuredClient(self.settings, self.cache, 'qwen')
        _, first = client.ask([self.image], 'prompt', 'v1')
        _, second = client.ask([self.image], 'prompt', 'v1')
        self.assertEqual(first['attempts'][0]['usage']['prompt_tokens'], 100)
        self.assertEqual(second['request_count'], 0)
        self.assertEqual(self.transport.post.call_count, 1)
        self.assertEqual(len(list((self.cache/'history').glob('*.json'))), 1)
        self.assertNotIn('PRIVATE-TEST-KEY', ''.join(p.read_text() for p in self.cache.rglob('*.json')))

    def test_failed_history_survives_resume(self):
        client = MeasuredClient(self.settings, self.cache, 'qwen')
        self.transport.post.return_value = response({'private': 'SECRET'}, 401)
        with self.assertRaises(ModelCallFailure):
            client.ask([self.image], 'prompt', 'v1')
        self.transport.post.return_value = response({'ok': True})
        client.ask([self.image], 'prompt', 'v1')
        traces = [json.loads(p.read_text()) for p in (self.cache/'history').glob('*.json')]
        self.assertEqual(sorted(t['success'] for t in traces), [False, True])
        self.assertEqual(self.transport.post.call_count, 2)
        self.assertNotIn('SECRET', str(traces))

    def test_retry_usage_and_failure_count_are_retained(self):
        self.transport.post.side_effect = [httpx.ReadTimeout('private transport'), response({'ok': True})]
        with patch('scripts.body_scan_full_eval.client.time.sleep'):
            _, trace = MeasuredClient(self.settings, self.cache, 'deepseek').ask([self.image], 'prompt', 'v1')
        self.assertEqual(trace['request_count'], 2)
        self.assertEqual(trace['attempts'][0]['error'], 'request_timeout')
        self.assertNotIn('private transport', str(trace))

    def test_dataset_excludes_entire_reference_package_including_originals(self):
        self.assertTrue(is_reference({'store': '（模板/标准包）', 'member': '宝安店-曾繁治（原始素材）'}))
        self.assertTrue(is_reference({'store': '（模板/标准包）', 'member': '宝安店-曾繁治（输出成品）'}))
        self.assertFalse(is_reference({'store': '石厦店', 'member': '黎国萍'}))
        self.assertTrue(is_reference({'store': '宝安店', 'path': '私教会员案例项目/参考模板/宝安店-原始素材/照片.jpg'}))
        self.assertTrue(is_reference({'store': '景田店', 'path': '私教会员案例项目/会员案例素材生产标准（说明文件）/清单.png'}))
        self.assertFalse(is_reference({'store': '石厦店', 'path': '私教会员案例项目/石厦店/会员/照片.jpg'}))

    def test_fixed_pair_metrics_map_swapped_direction_before_scoring(self):
        from scripts.body_scan_full_eval.metrics import fixed_observations
        def row(a,b):
            return {'kind':'same_view_candidate','primary_direction':{'after':a},'swapped_direction':{'after':b},
                'decision':{'after':None,'reason':'test'},'primary':{},'swapped':{}}
        metrics=fixed_observations([row('A','B'),row('A','A'),row('B',None),row(None,None)])
        self.assertEqual(metrics['primary_directional_pairs'],3)
        self.assertEqual(metrics['stable_direction_after_swap'],1)
        self.assertEqual(metrics['opposite_direction_after_swap'],1)
        self.assertEqual(metrics['direction_lost_after_swap'],1)

    def test_inventory_counts_duplicate_bytes_and_non_image_files(self):
        from scripts.body_scan_full_eval.inventory import inventory
        directory=self.root/'source';directory.mkdir()
        (directory/'one.jpg').write_bytes(b'identical')
        (directory/'two.jpg').write_bytes(b'identical')
        (directory/'notes.pdf').write_bytes(b'document')
        (directory/'.DS_Store').write_bytes(b'metadata')
        value=inventory(directory)
        self.assertEqual(len(value['files']),3)
        self.assertEqual(value['counts'],{'.pdf':1,'.jpg':2})
        self.assertEqual(sum(r['sha256']==value['files'][1]['sha256'] for r in value['files']),2)

    def test_unavailable_swapped_answer_remains_in_stability_denominator(self):
        from scripts.body_scan_full_eval.metrics import fixed_observations
        metrics=fixed_observations([{'kind':'same_view_candidate','primary_direction':{'after':'A'},
            'swapped_direction':None,'primary':{},'swapped':{'error':'invalid_json'},
            'decision':{'after':None,'reason':'model_response_unavailable'}}])
        self.assertEqual(metrics['primary_directional_pairs'],1)
        self.assertEqual(metrics['direction_stability_fraction'],0)
        self.assertEqual(metrics['directional_primary_but_swap_unavailable'],1)
        self.assertEqual(metrics['validated_response_stages'],1)


if __name__ == '__main__':
    unittest.main()

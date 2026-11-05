import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import httpx
import numpy as np

from scripts.body_scan.reference import VisualEvidence
from scripts.body_scan_phase_sessions.client import EvidenceClient, ModelCallFailure
from scripts.body_scan_phase_sessions.evidence import SessionEvidence, validate_observations


def config():
    return {'base_url': 'https://example.invalid/v1', 'model': 'fixture-vision', 'api_key': 'unit-test-key'}


def response(value, status=200, finish='stop'):
    mock = Mock(status_code=status)
    mock.json.return_value = {'choices': [{'finish_reason': finish, 'message': {'content': json.dumps(value)}}]}
    return mock


class ClientTests(unittest.TestCase):
    def setUp(self):
        self.images = [np.zeros((5,5,3), np.uint8)]

    def client_mock(self):
        mock = Mock(); mock.__enter__ = Mock(return_value=mock); mock.__exit__ = Mock(return_value=False)
        return mock

    def test_timeout_recovers_once_and_valid_response_uses_compatible_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            transport = self.client_mock()
            transport.post.side_effect = [httpx.ReadTimeout('do not log transport content'), response({'ok': True})]
            with patch('scripts.body_scan_phase_sessions.client.httpx.Client', return_value=transport), patch('scripts.body_scan_phase_sessions.client.time.sleep'):
                client = EvidenceClient(tmp, config)
                raw, trace = client.ask(self.images, 'prompt', 'version')
                self.assertEqual(trace['request_count'], 2)
                self.assertEqual(trace['attempts'][0]['error'], 'model_timeout')
                self.assertEqual(client.ask(self.images, 'prompt', 'version')[1]['request_count'], 0)
                self.assertEqual(VisualEvidence(tmp,config).ask(self.images,'prompt','version')[0], raw)
                self.assertEqual(transport.post.call_count,2)

    def test_auth_failure_does_not_retry_or_expose_response_body(self):
        with tempfile.TemporaryDirectory() as tmp:
            transport=self.client_mock(); transport.post.return_value=response({'sensitive':'never logged'},401)
            with patch('scripts.body_scan_phase_sessions.client.httpx.Client', return_value=transport):
                with self.assertRaises(ModelCallFailure) as caught:
                    EvidenceClient(tmp,config).ask(self.images,'prompt','version')
            self.assertEqual(str(caught.exception),'model_http_401')
            self.assertEqual(transport.post.call_count,1)
            self.assertNotIn('sensitive',str(caught.exception.trace))
            self.assertFalse(list(Path(tmp).glob('*.json')))

    def test_truncated_response_is_distinct_from_semantic_rejection(self):
        with tempfile.TemporaryDirectory() as tmp:
            transport=self.client_mock(); transport.post.side_effect=[response({},finish='length'),response({'ok':True})]
            with patch('scripts.body_scan_phase_sessions.client.httpx.Client',return_value=transport), patch('scripts.body_scan_phase_sessions.client.time.sleep'):
                _,trace=EvidenceClient(tmp,config).ask(self.images,'prompt','version')
            self.assertEqual(trace['attempts'][0]['error'],'model_response_truncated')
            self.assertEqual(transport.post.call_args.kwargs['json']['max_tokens'],3500)

    def test_valid_json_with_invalid_semantics_is_not_retried(self):
        with tempfile.TemporaryDirectory() as tmp:
            transport=self.client_mock(); transport.post.return_value=response({'wrong_schema':True})
            with patch('scripts.body_scan_phase_sessions.client.httpx.Client',return_value=transport):
                result,audit=SessionEvidence(tmp,config).attempt(self.images,'prompt','version',validate_observations)
            self.assertIsNone(result); self.assertEqual(transport.post.call_count,1)
            self.assertEqual(audit['request_count'],1); self.assertIn('error',audit)

    def test_repeated_transport_failure_is_bounded_and_trace_survives(self):
        with tempfile.TemporaryDirectory() as tmp:
            transport=self.client_mock(); transport.post.side_effect=httpx.ReadTimeout('private payload')
            with patch('scripts.body_scan_phase_sessions.client.httpx.Client',return_value=transport), patch('scripts.body_scan_phase_sessions.client.time.sleep'):
                result,audit=SessionEvidence(tmp,config).attempt(self.images,'prompt','version',validate_observations)
            self.assertIsNone(result); self.assertEqual(transport.post.call_count,2)
            self.assertEqual(audit['request_count'],2); self.assertNotIn('private',str(audit))


if __name__ == '__main__':
    unittest.main()

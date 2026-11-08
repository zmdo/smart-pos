import tempfile, unittest
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
from test_studio import sample
from studio import store, config, render_errors
from studio.common import save
import app


class RenderErrorTests(unittest.TestCase):
    def test_known_privacy_error_survives_process_boundary(self):
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)/'output'
            render_errors.record(out,ValueError('面部遮挡尚未完成检查，请在会员信息顶部准备或重新检查'))
            error=render_errors.read_error(out)
            self.assertEqual(error.code,'privacy_unprepared')
            self.assertIn('准备头部遮挡',str(error))
            self.assertNotIn('封面',str(error))

    def test_unknown_error_and_untrusted_code_cannot_expose_private_details(self):
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)/'output'
            render_errors.record(out,ValueError('API key=private-example /private/path'))
            self.assertFalse(render_errors.error_file(out).exists())
            save(render_errors.error_file(out),{'code':'arbitrary-secret'})
            self.assertIsNone(render_errors.read_error(out))

    def test_cover_error_keeps_instruction_without_raw_nested_details(self):
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)/'output'
            render_errors.record(out,ValueError('封面取景不可用，请调整到有效原图范围内：/private/source'))
            error=render_errors.read_error(out)
            self.assertEqual(error.code,'cover_crop_invalid')
            self.assertNotIn('/private',str(error))

    def test_api_returns_specific_privacy_error_and_section_aware_fallback(self):
        store.initialize();jid=store.create('preview-error-test',config.snapshot())['id']
        store.save_review(jid,{'members':[sample()]},0)
        client=TestClient(app.app);client.cookies.set('studio_session',store.issue_session())
        self.addCleanup(client.close)
        url=f'/api/jobs/{jid}/preview/m001';headers={'Origin':'http://testserver'}
        with patch('studio.review.preview',side_effect=render_errors.RenderInputError('privacy_unprepared')):
            response=client.post(url,json={'version':1,'section':'three_views'},headers=headers)
            self.assertEqual(response.status_code,422)
            self.assertIn('准备头部遮挡',response.json()['detail'])
            self.assertNotIn('封面',response.json()['detail'])
        with patch('studio.review.preview',side_effect=RuntimeError('private internal error')):
            response=client.post(url,json={'version':1,'section':'three_views'},headers=headers)
            self.assertIn('完整六图',response.json()['detail'])
            self.assertNotIn('private',response.text)
        self.assertEqual(store.review(jid)['version'],1)

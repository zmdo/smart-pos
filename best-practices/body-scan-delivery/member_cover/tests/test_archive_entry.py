import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from member_cover.__main__ import main

ROOT = Path(__file__).resolve().parents[2]


class CoverArchiveTests(unittest.TestCase):
    def test_cover_frame_argument_is_required_without_legacy_fallback(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
            main(['--delivery', '/unused', '--out', '/unused'])
        self.assertEqual(error.exception.code, 2)

    def test_old_frames_rejected_before_rendering(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root/'frames.json').write_text(json.dumps({'version':'body-scan-cover-frames-v1'}))
            with self.assertRaisesRegex(ValueError, 'requires_head_hip_frames_v2'):
                main(['--delivery', '/unused', '--cover-frames', tmp, '--out', str(root/'output')])
            self.assertFalse((root/'output').exists())

    def test_cover_imports_without_models_network_or_development_modules(self):
        program = '''
import sys, importlib, importlib.abc
from pathlib import Path
root = Path(sys.argv[1]).resolve()
class Block(importlib.abc.MetaPathFinder):
 def find_spec(self, name, path=None, target=None):
  blocked = ('httpx', 'requests', 'openai', 'torch', 'cv2', 'scripts.body_scan_cover',
             'scripts.body_report_compare', 'scripts.body_scan_phase_classification',
             'scripts.body_scan_group_display', 'scripts.body_scan_person_scale')
  if any(name == p or name.startswith(p+'.') for p in blocked):
   raise ImportError('forbidden_cover_dependency: '+name)
sys.meta_path.insert(0, Block())
for name in ('__main__', 'pipeline', 'prepare', 'compare', 'render', 'frame_bundle', 'selection', 'copy'):
 importlib.import_module('member_cover.'+name)
for name, module in list(sys.modules.items()):
 if name.split('.')[0] in ('scripts', 'member_cover', 'three_views', 'view_comparison', 'single_view'):
  locations = [module.__file__] if getattr(module, '__file__', None) else list(module.__path__)
  assert locations and all(Path(p).resolve().is_relative_to(root) for p in locations), name
'''
        result = subprocess.run([sys.executable, '-c', program, str(ROOT)], cwd=ROOT,
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

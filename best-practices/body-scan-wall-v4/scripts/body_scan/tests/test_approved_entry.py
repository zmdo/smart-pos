"""The approved entry cannot omit the guard or overwrite an intermediate stage."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, Mock

from scripts.body_scan import __main__ as full
from scripts import body_scan_approved as approved


class ApprovedEntryTests(unittest.TestCase):
    def test_plain_entry_defaults_to_wall_then_guard(self):
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp)/'result'; job = Path(temp)/'job.json'
            with patch('sys.argv', ['body_scan', '--job', str(job), '--out', str(out)]), \
                 patch.object(full, 'verify_integrity'), patch.object(full, 'run', return_value=([], [])) as base, \
                 patch.object(full, 'SubjectLocalizer'), patch.object(full, 'ShoulderPose'), \
                 patch.object(full, 'make_previews'), patch.object(full, 'finish') as guard, \
                 patch('scripts.body_scan.refinement.run') as wall:
                full.main()
                self.assertEqual(base.call_args.args[1], out.with_name('result-pinhole'))
                wall.assert_called_once_with(out.with_name('result-pinhole'), out.with_name('result-wall'))
                self.assertEqual(guard.call_args.args, ([out.with_name('result-wall')], out))

    def test_existing_intermediate_aborts_before_processing(self):
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp)/'result'; out.with_name('result-wall').mkdir()
            with patch('sys.argv', ['body_scan', '--job', 'job.json', '--out', str(out)]), \
                 patch.object(full, 'run') as process:
                with self.assertRaisesRegex(ValueError, 'must_not_exist'):
                    full.main()
                process.assert_not_called()
                self.assertFalse(out.exists())

    def test_v2_upgrade_always_finishes_with_guard(self):
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp)/'result'; baseline = Path(temp)/'v2'
            with patch('sys.argv', ['upgrade', '--baseline', str(baseline), '--out', str(out)]), \
                 patch.object(approved, 'verify_integrity'), patch.object(approved, 'refine') as wall, \
                 patch.object(approved, 'finish', return_value={}) as guard:
                approved.main()
                self.assertEqual(wall.call_args.args, (baseline, out.with_name('result-wall')))
                self.assertEqual(guard.call_args.args[:2], ([out.with_name('result-wall')], out))


if __name__ == '__main__':
    unittest.main()

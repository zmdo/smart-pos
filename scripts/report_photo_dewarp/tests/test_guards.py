"""Run on the remote image-processing environment."""
import hashlib
from pathlib import Path
import tempfile
import unittest

import numpy as np

from scripts.report_photo_dewarp.__main__ import grid_checks, select_rows


class DewarpGuards(unittest.TestCase):
    def test_identity_and_folded_grid(self):
        x, y = np.meshgrid(np.linspace(-1, 1, 31), np.linspace(-1, 1, 45))
        grid = np.stack([x, y])
        self.assertEqual(grid_checks(grid)['fold_fraction'], 0)
        self.assertEqual(grid_checks(grid[:, :, ::-1])['fold_fraction'], 1)
        grid[0, 0, 0] = np.nan
        with self.assertRaisesRegex(ValueError, 'invalid_model_grid'):
            grid_checks(grid)

    def test_source_binding_and_excluded_material(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / '测试店/会员/report.jpg'
            source.parent.mkdir(parents=True)
            source.write_bytes(b'not decoded in selection')
            row = {'asset_id': 'a0001', 'store': '测试店', 'member': '会员',
                   'source': '/remote/私教会员案例项目/测试店/会员/report.jpg',
                   'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
                   'qwen': {'kind': 'body_report'}}
            self.assertEqual(len(select_rows([row], root, set())), 1)
            source.write_bytes(b'changed source')
            with self.assertRaisesRegex(ValueError, 'source_hash_mismatch'):
                select_rows([row], root, set())
            row['source'] = '/remote/私教会员案例项目/参考模板/report.jpg'
            row['store'] = '参考模板'
            with self.assertRaisesRegex(ValueError, 'not_store_material'):
                select_rows([row], root, set())


if __name__ == '__main__':
    unittest.main()

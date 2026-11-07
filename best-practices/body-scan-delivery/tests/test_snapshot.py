import shutil
import tempfile
import unittest
from pathlib import Path

from category import generate
from snapshot import verify_integrity

ROOT = Path(__file__).resolve().parents[1]


class SnapshotTests(unittest.TestCase):
    def test_imports_resolve_only_within_snapshot(self):
        import scripts.body_scan_delivery.render as renderer
        import scripts.body_scan_contracts.bundles as contracts
        import three_views.render as grid
        import view_comparison.render as vs
        import single_view.render as single
        import testimonial_album.render as testimonial
        import testimonial_album.pipeline as testimonial_pipeline
        import testimonial_album.privacy as privacy
        import training_daily.pipeline as training
        import training_daily.routing as training_routing
        import life_photos.pipeline as lifestyle
        for module in (renderer, contracts, grid, vs, single, testimonial, testimonial_pipeline, privacy, training, training_routing, lifestyle):
            self.assertTrue(Path(module.__file__).resolve().is_relative_to(ROOT))
        self.assertIs(renderer.seamless_grid, grid.seamless_grid)
        self.assertIs(renderer.draw_vs, vs.draw_vs)
        self.assertIs(renderer.draw_single, single.draw_single)

    def test_changed_renderer_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            copy = Path(tmp)/'package'
            shutil.copytree(ROOT, copy, ignore=shutil.ignore_patterns('__pycache__'))
            with (copy/'three_views/render.py').open('a') as handle:
                handle.write('\n# altered\n')
            with self.assertRaisesRegex(ValueError, 'snapshot_file_mismatch'):
                verify_integrity(copy)

    def test_extra_module_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            copy = Path(tmp)/'package'
            shutil.copytree(ROOT, copy, ignore=shutil.ignore_patterns('__pycache__'))
            (copy/'injected.py').write_text('')
            with self.assertRaisesRegex(ValueError, 'unexpected_or_missing_snapshot_module'):
                verify_integrity(copy)

    def test_existing_output_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(FileExistsError):
                generate('single', '/nonexistent-input', tmp)

    def test_unknown_category_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'unsupported_product_kind'):
            generate('cover', '/nonexistent-input', '/unused-output')

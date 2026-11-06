import tempfile
import unittest
from pathlib import Path
from scripts.body_scan_contracts.io import save
from scripts.body_scan_cover.frame_bundle import load_frames, consume_frames


class FrameContractTests(unittest.TestCase):
    def test_previous_phase_revision_cannot_be_used_for_new_cover(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            save(root/'frames.json', {'version': 'body-scan-cover-frames-v1', 'phase_result_sha256': 'old'})
            with self.assertRaisesRegex(ValueError, 'another_phase_revision'):
                load_frames(root, 'new', {})

    def test_swapped_stages_are_rejected_even_for_same_assets(self):
        identity = {'group_id': 'g001', 'store': '测试店', 'member': '测试'}
        rows = [{'asset_id': 'a1', 'phase': 'before'}, {'asset_id': 'a2', 'phase': 'after'}]
        case = {**identity, 'frames': [{'stage': r} for r in reversed(rows)]}
        with self.assertRaisesRegex(ValueError, 'stage_or_selected_pair_changed'):
            consume_frames((Path('/unused'), {'g001': case}, {}), rows, identity, {})

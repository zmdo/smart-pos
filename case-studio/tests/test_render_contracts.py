"""Exercise the integration against real frozen renderers, without model calls."""

import os, sys, tempfile, unittest
from pathlib import Path
from PIL import Image

ROOT = Path(os.environ.get("STUDIO_REPO", Path(__file__).resolve().parents[2]))
FONT = Path("/root/autodl-fs/case-studio/fonts/NotoSansSC.ttf")
sys.path.insert(0, str(ROOT / "best-practices/body-scan-delivery"))


@unittest.skipUnless(
    FONT.is_file() and (ROOT / "best-practices/body-scan-delivery").is_dir(),
    "remote frozen-renderer environment required",
)
class RenderContractTests(unittest.TestCase):
    def test_default_vs_pixels_preserved_and_text_edit_changes_pixels(self):
        from view_comparison.render import draw_vs, TITLES

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "photo.png"
            Image.new("RGB", (300, 600), "#ddd").save(path)
            rows = [{"asset_id": "a"}, {"asset_id": "b"}]
            photos = {"a": path, "b": path}
            c = dict(
                width=540,
                metrics=[],
                brand_name="UP",
                nickname="会员",
                address="地址",
                consent_text="",
            )
            original = draw_vs(rows, photos, FONT, c, "front")
            defaults = draw_vs(
                rows,
                photos,
                FONT,
                dict(
                    c,
                    titles=TITLES,
                    before_text="Before",
                    after_text="After",
                    vs_text="VS",
                ),
                "front",
            )
            self.assertEqual(original.tobytes(), defaults.tobytes())
            changed = draw_vs(
                rows,
                photos,
                FONT,
                dict(c, before_text="起点", after_text="现在"),
                "front",
            )
            self.assertNotEqual(original.tobytes(), changed.tobytes())
            self.assertEqual(original.size, changed.size)

    def test_arbitrary_reviewed_rows_render_with_fixed_height(self):
        from report_comparison.render import render

        with tempfile.TemporaryDirectory() as tmp:
            row = dict(
                type="自定义肩宽",
                key="custom",
                before="40",
                after="41",
                delta="+1",
                unit="cm",
            )
            c = dict(rows=[], reviewed_rows=[row], pair={})
            one = render(c, {}, 1080, FONT, Path(tmp) / "one.png")
            c["reviewed_rows"] = [row] * 10
            ten = render(c, {}, 1080, FONT, Path(tmp) / "ten.png")
            self.assertEqual(one["height"], ten["height"])
            self.assertEqual(ten["row_count"], 10)
            self.assertEqual(one["display_metrics"], ["自定义肩宽"])

    def test_default_cover_badge_preserves_pixels(self):
        from member_cover.render import draw_cover

        ims = [
            Image.new("RGB", (500, 478), "#ccc"),
            Image.new("RGB", (500, 478), "#bbb"),
        ]
        c = dict(
            title="每一步都算数",
            subtitle="记录改变",
            headline="把改变留在镜头里",
            segments=[dict(text="记录每个阶段的自己。", emphasis=False)],
            address="UP 健身私教馆",
        )
        a, _ = draw_cover(ims, c, {}, FONT, "甲店")
        b, _ = draw_cover(
            ims, dict(c, badge="会员案例", store_text="甲店"), {}, FONT, "甲店"
        )
        self.assertEqual(a.tobytes(), b.tobytes())

    def test_package_integrity(self):
        from snapshot import verify_integrity

        self.assertGreater(verify_integrity()["verified_files"], 100)


if __name__ == "__main__":
    unittest.main()

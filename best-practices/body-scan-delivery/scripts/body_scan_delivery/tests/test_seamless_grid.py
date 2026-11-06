import json
import tempfile
import unittest
from pathlib import Path
from PIL import Image,ImageChops

from scripts.body_scan_delivery.render import draw_product,render,GRID_RENDERER


class SeamlessGridTests(unittest.TestCase):
    def fixture(self,root):
        rows=[];photos={}
        for i,view in enumerate(('front','side','back')*2):
            aid='a'+str(i);phase='before' if i<3 else 'after'
            rows.append({'asset_id':aid,'phase':phase,'view':view,'label':'训练前（推断）' if i<3 else '训练后（推断）',
                         'label_kind':'inferred','review_flags':[],'requires_review':True})
            image=Image.new('RGB',(7,11),(i*31,110,210))
            image.putpixel((0,0),(255,0,i));image.putpixel((6,10),(i,255,0))
            path=root/(aid+'.png');image.save(path);photos[aid]=str(path)
        product={'product_id':'g1-three-views','group_id':'g1','store':'测试店','member':'测试人',
                 'kind':'three_views','view':'all','asset_ids':[r['asset_id'] for r in rows]}
        return product,rows,photos

    def test_native_pixels_cover_the_entire_grid_without_font(self):
        with tempfile.TemporaryDirectory() as tmp:
            p,rows,photos=self.fixture(Path(tmp));image=draw_product(p,rows,photos,None)
            self.assertEqual(image.size,(21,22))
            for i,row in enumerate(rows):
                x=i%3*7;y=i//3*11
                with Image.open(photos[row['asset_id']]) as original:
                    self.assertIsNone(ImageChops.difference(image.crop((x,y,x+7,y+11)),original).getbbox())

    def test_mismatched_sizes_are_rejected_without_stretching(self):
        with tempfile.TemporaryDirectory() as tmp:
            p,rows,photos=self.fixture(Path(tmp));Image.new('RGB',(8,11)).save(photos['a5'])
            with self.assertRaisesRegex(ValueError,'equal_frame_sizes'):draw_product(p,rows,photos,None)

    def test_incomplete_grid_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            p,rows,photos=self.fixture(Path(tmp))
            with self.assertRaisesRegex(ValueError,'six_frames'):draw_product(p,rows[:5],photos,None)

    def test_old_style_is_invalidated_and_label_only_review_reuses_new_grid(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);p,rows,photos=self.fixture(root);old=root/'old';old.mkdir()
            (old/'result.json').write_text(json.dumps({'outputs':[{'product_id':p['product_id'],
                'dependency_sha256':'old-red-label-renderer','file':'old.jpg','sha256':'unused'}]}))
            first=render([p],rows,photos,root/'new',None,old)
            self.assertFalse(first[0]['reused']);self.assertEqual(first[0]['renderer_version'],GRID_RENDERER)
            self.assertEqual((first[0]['width'],first[0]['height']),(21,22))
            self.assertTrue(first[0]['file'].endswith('.png'))
            with Image.open(root/'new'/first[0]['file']) as image:
                self.assertEqual(image.format,'PNG')
                self.assertEqual(image.tobytes(),draw_product(p,rows,photos,None).tobytes())
            (root/'new/result.json').write_text(json.dumps({'outputs':first}))
            for row in rows:row.update(label_kind='human',label='已确认',requires_review=False)
            second=render([p],rows,photos,root/'reviewed',None,root/'new')
            self.assertTrue(second[0]['reused']);self.assertFalse(second[0]['requires_review'])
            self.assertEqual(first[0]['sha256'],second[0]['sha256'])

"""Run image and geometry checks on the remote processing server."""
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np
from PIL import Image

from scripts.report_photo_crop.geometry import make_frame, parse_ratio, rectangle_in_source
from scripts.report_photo_crop.__main__ import reused_selections


class CropTests(unittest.TestCase):
    def source(self, size):
        return Image.fromarray(np.random.default_rng(3).integers(0, 250, (size[1], size[0], 3), dtype=np.uint8))

    def assert_exact_source_rectangle(self, source, crop, output, evidence):
        x1,y1,x2,y2 = evidence['crop_xyxy']
        self.assertTrue(0 <= x1 < x2 <= source.width and 0 <= y1 < y2 <= source.height)
        self.assertEqual((x2-x1)*4, (y2-y1)*3)
        expected = np.asarray(source)[y1:y2,x1:x2]
        np.testing.assert_array_equal(np.asarray(crop), expected)
        np.testing.assert_array_equal(np.asarray(output), expected)
        self.assertFalse(evidence['background_mask_applied'])
        self.assertFalse(evidence['padding_applied'])

    def test_screenshot_moves_rectangle_below_app_ui(self):
        source=self.source((1000,2400))
        selection={'is_report':True,'medium':'screenshot','content_box':[50,250,950,550]}
        output,crop,g=make_frame(source,selection)
        self.assert_exact_source_rectangle(source,crop,output,g)
        self.assertTrue(g['content_fully_contained'])
        self.assertGreater(g['crop_xyxy'][1],200)

    def test_paper_ignores_polygon_and_keeps_every_pixel_inside_rectangle(self):
        source=self.source((800,1100))
        selection={'is_report':True,'medium':'paper_photo','content_box':[150,150,850,850],
                   'paper_box':[100,100,900,900],'paper_polygon':'deliberately-invalid-and-ignored'}
        output,crop,g=make_frame(source,selection)
        self.assert_exact_source_rectangle(source,crop,output,g)
        self.assertTrue(g['content_fully_contained'])

    def test_wide_source_cannot_be_faked_into_complete_portrait(self):
        source=self.source((1920,1280))
        selection={'is_report':True,'medium':'screenshot','content_box':[0,0,1000,1000]}
        output,crop,g=make_frame(source,selection)
        self.assertEqual(crop.size,(960,1280))
        self.assertFalse(g['content_fully_contained'])
        self.assertEqual(g['content_box_coverage'],.5)
        self.assert_exact_source_rectangle(source,crop,output,g)

    def test_priority_repositions_tall_report_to_keep_bottom_data(self):
        source=self.source((900,2400))
        selection={'is_report':True,'medium':'screenshot','content_box':[10,50,990,950]}
        output,crop,g=make_frame(source,selection,priority={'primary_box':[100,600,900,950]})
        self.assertFalse(g['content_fully_contained'])
        self.assertTrue(g['priority_fully_contained'])
        self.assertTrue(g['priority_used'])
        self.assertGreaterEqual(g['crop_xyxy'][1],1080)
        self.assert_exact_source_rectangle(source,crop,output,g)

    def test_priority_cannot_hide_impossible_important_region(self):
        source=self.source((1920,1280))
        selection={'is_report':True,'medium':'screenshot','content_box':[0,0,1000,1000]}
        _,_,g=make_frame(source,selection,priority={'primary_box':[0,0,800,1000]})
        self.assertFalse(g['priority_fully_contained'])
        self.assertLess(g['priority_box_coverage'],1)
        self.assertEqual(g['crop_xyxy'][0],0)  # Preserve metric names before optional right columns.

    def test_screenshot_priority_window_stops_before_bottom_toolbar(self):
        source=self.source((1000,2400))
        selection={'is_report':True,'medium':'screenshot','content_box':[0,50,1000,950]}
        _,_,g=make_frame(source,selection,priority={'primary_box':[100,500,900,850]})
        self.assertEqual(g['crop_xyxy'][3],2040)
        self.assertTrue(g['priority_fully_contained'])

    def test_export_cap_is_uniform_and_preserves_ratio(self):
        source=self.source((1500,2000))
        selection={'is_report':True,'medium':'screenshot','content_box':[100,100,900,900]}
        output,crop,g=make_frame(source,selection,max_side=720)
        self.assertEqual(output.size,(540,720))
        self.assertEqual(output.width/crop.width,output.height/crop.height)
        np.testing.assert_array_equal(np.asarray(output),np.asarray(crop.resize(output.size,Image.Resampling.LANCZOS)))
        self.assertEqual(parse_ratio('6:8'),(3,4))

    def test_solver_random_bounds_and_optimal_box_coverage(self):
        rng=np.random.default_rng(8)
        for _ in range(500):
            w,h=map(int,rng.integers(12,60,2))
            x1,x2=sorted(map(int,rng.choice(w+1,2,replace=False)))
            y1,y2=sorted(map(int,rng.choice(h+1,2,replace=False)))
            core=[x1,y1,x2,y2];preferred=[max(0,x1-3),max(0,y1-3),min(w,x2+3),min(h,y2+3)]
            box,contained=rectangle_in_source((w,h),core,preferred,(3,4))
            a,b,c,d=box;cw,ch=c-a,d-b
            self.assertTrue(0<=a<c<=w and 0<=b<d<=h)
            self.assertEqual(cw*4,ch*3)
            overlap=max(0,min(c,x2)-max(a,x1))*max(0,min(d,y2)-max(b,y1))
            self.assertEqual(overlap,min(cw,x2-x1)*min(ch,y2-y1))
            self.assertEqual(contained,overlap==(x2-x1)*(y2-y1))

    def test_reused_boxes_are_source_bound(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'manifest.json'
            path.write_text(json.dumps({'version':'report-photo-crop-v2','rows':[
                {'asset_id':'a0001','source_sha256':'old','selection':{}}]}))
            with self.assertRaisesRegex(ValueError,'selection_source_mismatch'):
                reused_selections(path,[({'asset_id':'a0001','source_sha256':'changed'},None)])

    def test_unknown_or_invalid_regions_reject(self):
        source=Image.new('RGB',(600,800))
        with self.assertRaisesRegex(ValueError,'unknown_report_medium'):
            make_frame(source,{'is_report':True,'medium':'other'})
        with self.assertRaisesRegex(ValueError,'invalid_normalized_box'):
            make_frame(source,{'is_report':True,'medium':'screenshot','content_box':[0,-1,1000,1000]})


if __name__ == '__main__':
    unittest.main()

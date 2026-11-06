import copy
import json
import tempfile
import unittest
from pathlib import Path
from PIL import Image,ImageChops

from scripts.body_scan_delivery.presentation import load_presentation,resolve,metric_display,nickname
from scripts.body_scan_delivery.vs_layout import geometry
from scripts.body_scan_delivery.render import draw_product,render

FONT=Path('/root/autodl-fs/case-studio/fonts/NotoSansSC.ttf')


class ReferenceVSTests(unittest.TestCase):
    def fixture(self,root):
        photos={};rows=[]
        for i in range(2):
            aid=f'a{i}';path=root/(aid+'.png')
            # Different aspect ratios expose accidental stretch or fit/crop.
            Image.new('RGB',((300,240)[i],600),('navy','green')[i]).save(path)
            photos[aid]=str(path)
            rows.append(dict(asset_id=aid,phase=('before','after')[i],view='side',
                label_kind='inferred',label=('训练前（推断）','训练后（推断）')[i],review_flags=[],requires_review=True))
        product=dict(product_id='g1-vs-side',kind='vs',group_id='g1',store='测试店',member='欧阳明',view='side',asset_ids=['a0','a1'])
        return product,rows,photos

    def test_fixed_width_variable_height_no_photo_gutters_or_crop(self):
        with tempfile.TemporaryDirectory() as tmp:
            p,rows,photos=self.fixture(Path(tmp));context=resolve(p)
            image=draw_product(p,rows,photos,FONT,context)
            layout=geometry([(300,600),(240,600)],1080)
            self.assertEqual(image.size,(1080,1757))
            self.assertEqual(layout['photo_boxes'],[[0,219,600,1419],[600,219,1080,1419]])
            # A strip away from intentional reference overlays must be exactly the scaled originals.
            for box,path in zip(layout['photo_boxes'],photos.values()):
                with Image.open(path) as original:
                    scaled=original.resize((box[2]-box[0],1200),Image.Resampling.LANCZOS)
                self.assertIsNone(ImageChops.difference(image.crop((box[0],900,box[2],1100)),scaled.crop((0,681,scaled.width,881))).getbbox())

    def test_report_identity_quality_and_bilateral_deltas(self):
        product=dict(store='测试店',member='欧阳明')
        report=dict(store='测试店',member='欧阳明',status='verified_transcription',report_id='r001',source='report.pdf',source_sha256='hash',
            metrics={'arm':dict(usable=True,before_values=[30,31],after_values=[32,30],computed_delta=[2,-1],delta_unit='cm')})
        self.assertEqual(resolve(product,reports=[report])['metrics'][2]['text'],'臂围：+2/-1cm')
        self.assertFalse(resolve(dict(store='其他店',member='欧阳明'),reports=[report])['metrics'][2]['available'])
        self.assertFalse(resolve(product,reports=[report,dict(report,report_id='r002')])['metrics'][2]['available'])
        self.assertFalse(resolve(product,reports=[dict(report,status='needs_review')])['metrics'][2]['available'])
        self.assertFalse(resolve(product,reports=[dict(report,date_issue='reversed')])['metrics'][2]['available'])
        report['metrics']['arm']['computed_delta']=[-5,-5]
        self.assertFalse(metric_display('arm',report)['available'])

    def test_honorific_requires_explicit_evidence(self):
        self.assertEqual(nickname('欧阳明',{'gender':'女'}),'欧阳女士')
        self.assertEqual(nickname('张小飞',{}),'张会员')
        self.assertEqual(nickname('candy',{}),'candy会员')

    def test_logo_pixels_and_transparency_are_used_in_header(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);p,rows,photos=self.fixture(root);(root/'logo').mkdir()
            logo=Image.new('RGBA',(100,50),(0,0,0,0))
            for x in range(25,75):
                for y in range(10,40):logo.putpixel((x,y),(0,0,255,255))
            logo.save(root/'logo/brand.png')
            path=root/'config.json';path.write_text(json.dumps({'image_root':'.'}))
            config=load_presentation(path,{})
            context=resolve(p,config);image=draw_product(p,rows,photos,FONT,context)
            self.assertEqual(image.getpixel((540,100)),(0,0,255))
            self.assertEqual(image.getpixel((420,100)),(231,0,18))

    def test_logo_is_discovered_only_under_image_root_logo_and_bound(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'logo').mkdir()
            Image.new('RGBA',(20,10),'white').save(root/'logo/brand.png')
            path=root/'config.json';path.write_text(json.dumps({'image_root':'.'}));bindings={}
            config=load_presentation(path,bindings)
            self.assertEqual(Path(config['logo_path']),root/'logo/brand.png')
            self.assertIn(str(root/'logo/brand.png'),bindings)
            Image.new('RGBA',(20,10),'red').save(root/'logo/other.png')
            with self.assertRaisesRegex(ValueError,'multiple_logos'):load_presentation(path,{})
            path.write_text(json.dumps({'image_root':'.','logo_file':'../config.json'}))
            with self.assertRaisesRegex(ValueError,'invalid_logo_file'):load_presentation(path,{})

    def test_config_report_and_review_changes_invalidate_vs_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);p,rows,photos=self.fixture(root)
            config={'width':540,'address':'地址 A'}
            first=render([p],rows,photos,root/'v1',FONT,presentation=config)
            (root/'v1/result.json').write_text(json.dumps({'outputs':first}))
            same=render([p],rows,photos,root/'same',FONT,root/'v1',presentation=config)
            self.assertTrue(same[0]['reused'])
            changed=render([p],rows,photos,root/'changed',FONT,root/'v1',presentation={**config,'address':'地址 B'})
            self.assertFalse(changed[0]['reused'])
            report=dict(store=p['store'],member=p['member'],status='verified_transcription',report_id='r001',source='x.pdf',source_sha256='a',
                metrics={'waist':dict(usable=True,before_values=[80],after_values=[75],computed_delta=[-5],delta_unit='cm')})
            reported=render([p],rows,photos,root/'reported',FONT,root/'v1',presentation=config,reports=[report])
            self.assertFalse(reported[0]['reused'])
            reviewed=copy.deepcopy(rows);reviewed[0].update(label_kind='human',label='训练前',requires_review=False)
            approved=render([p],reviewed,photos,root/'reviewed',FONT,root/'v1',presentation=config)
            self.assertFalse(approved[0]['reused'])

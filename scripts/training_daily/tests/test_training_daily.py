import ast
import copy
import tempfile
import unittest
from pathlib import Path
import numpy as np
from PIL import Image,ImageChops
from scripts.body_scan_contracts.io import save,read,sha
from scripts.body_scan_contracts.bundles import seal
from scripts.training_daily import EVIDENCE_SCHEMA
from scripts.training_daily.analysis import normalize,inventory
from scripts.training_daily.geometry import plan,pixels
from scripts.training_daily.routing import screenshot_photo_box,choose_plan
from scripts.training_daily.render import settings,frame_for,render,enhance,protection
from scripts.training_daily.pipeline import run


def record(**extra):
    return dict({'asset_id':'a0001','status':'accepted','reason':'清晰训练照片','kind':'action_training',
        'store':'测试店','member':'会员','directory':'测试店/会员','source_size':[800,1000],
        'action_name':'器械训练','score':90,'usable_bbox':[0,0,1000,1000],
        'subject_bbox':[300,180,680,850],'action_bbox':[160,120,840,950],
        'protected_boxes':[{'kind':'person','bbox':[200,130,800,920]}],
        'source_cutoff_parts':[],'issues':[],'lighting':'balanced','color_cast':'neutral','cast_confidence':1,'noise':'low'},**extra)


class TrainingDailyTests(unittest.TestCase):
    def test_inventory_uses_store_scope_and_qwen_primary_labels(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'audit.json';rows=[]
            for i,(store,kind,old) in enumerate([('参考模板','daily_training','daily_training'),('测试店','life_photo','daily_training'),('测试店','daily_training','other')]):
                rows.append(dict(asset_id=f'a{i:04}',store=store,member='会员',source=f'/old/私教会员案例项目/{store}/会员/{i}.jpg',source_sha256='a'*64,qwen={'kind':kind},old={'kind':old}))
            save(p,rows);sources,groups=inventory(tmp,p)
            self.assertEqual([s['asset_id'] for s in sources],['a0002']);self.assertEqual(len(groups),1)

    def test_square_coordinates_map_back_and_preserve_protected_parts(self):
        raw=dict(kind='action_training',usable_for_product=True,subject_mode='single',geometry_confidence=.97,
            usable_bbox=[250,0,750,1000],subject_bbox=[350,200,650,800],action_bbox=[320,150,680,850],
            protected_boxes=[{'kind':'contact_equipment','bbox':[300,100,700,900]}],action_name='下拉',
            quality={'clarity':4,'action_visibility':4,'exposure':4},lighting='balanced',color_cast='neutral',cast_confidence=.9,noise='low')
        result=normalize(raw,(1000,2000),(2000,500,0))
        self.assertEqual(result['usable_bbox'],[0,0,1000,1000]);self.assertEqual(result['action_bbox'],[100,100,900,900])
        raw['subject_mode']='ambiguous';self.assertEqual(normalize(raw,(1000,2000),(2000,500,0))['status'],'needs_review')
        raw['geometry_confidence']=float('nan')
        with self.assertRaises(ValueError):normalize(raw,(1000,2000),(2000,500,0))

    def test_posed_gym_is_not_promoted_to_training_action(self):
        self.assertEqual(normalize({'kind':'posed_gym','reason':'摆拍'},(1000,1000),(1000,0,0))['status'],'rejected')

    def test_crop_preserves_body_contact_equipment_and_usable_bounds(self):
        r=record();r['protected_boxes'].append({'kind':'contact_equipment','bbox':[50,200,950,600]})
        cfg=settings({});p=plan(r,(800,1000),frame_for(cfg),cfg);self.assertTrue(p['passed'])
        l,t,rr,b=p['crop']
        for region in r['protected_boxes']:
            x1,y1,x2,y2=pixels(region['bbox'],(800,1000));self.assertTrue(l<=x1 and t<=y1 and rr>=x2 and b>=y2)
        self.assertTrue(0<=l<rr<=800 and 0<=t<b<=1000)

    def test_wide_action_uses_inset_and_too_narrow_picture_is_rejected(self):
        cfg=settings({});r=record(usable_bbox=[0,0,1000,1000],action_bbox=[0,0,1000,1000])
        r['source_size']=[1200,900];p=plan(r,(1200,900),frame_for(cfg),cfg)
        self.assertTrue(p['passed']);self.assertEqual(p['mode'],'inset')
        p=plan(r,(2000,400),frame_for(cfg),cfg);self.assertFalse(p['passed']);self.assertEqual(p['code'],'insufficient_picture')

    def test_soft_background_protection_leaves_action_untouched(self):
        m=protection((600,800),[100,150,500,700],40)
        self.assertTrue(np.all(m[150:700,100:500]==1));self.assertEqual(float(m[0,0]),0)
        arr=np.zeros((800,600,3),dtype=np.uint8);arr[:]=[85,100,130]
        im=Image.fromarray(arr);r=record(source_size=[600,800],action_bbox=[200,200,800,800])
        no_bg=settings({'background_strength':0,'sharpen_percent':0});with_bg=settings({'sharpen_percent':0})
        a,_=enhance(im,r,[0,0,600,800],no_bg);b,_=enhance(im,r,[0,0,600,800],with_bg)
        self.assertIsNone(ImageChops.difference(a.crop((120,160,480,640)),b.crop((120,160,480,640))).getbbox())
        self.assertIsNotNone(ImageChops.difference(a,b).getbbox())

    def test_disabled_enhancement_preserves_exact_crop_pixels_and_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);path=root/'source.png'
            a=np.zeros((1000,800,3),dtype=np.uint8);a[:,:,0]=np.arange(800,dtype=np.uint16)[None,:]%256;a[:,:,1]=115;a[:,:,2]=80
            im=Image.fromarray(a);im.save(path);original=sha(path)
            out=root/'product.png';p=render(path,record(),out,settings({'enhance':False}))
            self.assertTrue(p['passed']);product=Image.open(out);self.assertEqual(product.size,(1080,1440))
            x,y,w,h=p['placement'];expected=im.crop(p['crop']).resize((w,h),Image.Resampling.LANCZOS)
            self.assertIsNone(ImageChops.difference(product.crop((x,y,x+w,y+h)),expected).getbbox())
            self.assertEqual(sha(path),original)

    def test_needs_review_never_writes_a_product(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);path=root/'source.png';Image.new('RGB',(800,1000),'white').save(path)
            p=render(path,record(status='needs_review',reason='动作范围置信不足'),root/'bad.png',settings({}))
            self.assertFalse(p['passed']);self.assertFalse((root/'bad.png').exists())

    def test_narrow_screenshot_removes_only_verified_padding_at_native_resolution(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);path=root/'screenshot.png';out=root/'out.png'
            a=np.zeros((1600,800,3),dtype=np.uint8)
            a[600:920]=np.random.default_rng(42).integers(30,240,(320,800,3),dtype=np.uint8)
            a[1540:1546,300:500]=255  # The home indicator is not picture content.
            im=Image.fromarray(a);im.save(path)
            r=record(status='rejected',reason='截图过窄',source_size=[800,1600],subject_mode='single',
                geometry_confidence=.95,quality={'clarity':4,'exposure':4},usable_bbox=[0,380,1000,570],
                subject_bbox=[200,390,800,560],action_bbox=[100,390,900,560],protected_boxes=[])
            cfg=settings({'border':6,'logo_path':'unused-for-native.png'})
            meta=render(path,r,out,cfg)
            self.assertEqual(meta['mode'],'native_crop');self.assertEqual(meta['crop'],[0,600,800,920])
            with Image.open(out) as product:
                self.assertEqual(product.size,(800,320));self.assertTrue(np.array_equal(np.asarray(product),a[600:920]))
            self.assertEqual(meta['uniform_scale'],1)
            self.assertFalse(meta['tone']['enabled']);self.assertIsNone(meta['files']['before'])
            self.assertEqual(screenshot_photo_box(im,[0,0,1000,1000]),None)
            # A dark scene without actual black padding is not trimmed by a model hint.
            self.assertIsNone(screenshot_photo_box(Image.new('RGB',im.size,(20,20,20)),r['usable_bbox']))
            self.assertFalse(choose_plan(record(**{**r,'kind':'posed_gym'}),im,frame_for(cfg),cfg)['passed'])

    def test_ambiguous_subject_preserves_original_jpeg_bytes_and_orientation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);path=root/'original.jpg'
            exif=Image.Exif();exif[274]=6
            Image.new('RGB',(1000,800),(90,100,110)).save(path,exif=exif,quality=87)
            cfg=settings({'logo_path':'unused-for-raw.png'})
            p=render(path,record(status='needs_review',subject_mode='ambiguous'),root/'product.png',cfg)
            self.assertEqual(p['mode'],'original_passthrough');self.assertFalse(p['tone']['enabled'])
            self.assertEqual((p['width'],p['height']),(800,1000));self.assertEqual(p['uniform_scale'],1)
            self.assertEqual(sha(path),sha(root/p['files']['file']));self.assertFalse((root/'product.png').exists())

    def test_standard_product_has_no_border_even_with_legacy_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);path=root/'source.png';Image.new('RGB',(900,1200),(80,100,120)).save(path)
            cfg=settings({'border':6,'enhance':False});self.assertEqual(frame_for(cfg),[0,0,1080,1440])
            r=record(source_size=[900,1200],subject_bbox=[0,0,1000,1000],action_bbox=[0,0,1000,1000],protected_boxes=[])
            p=render(path,r,root/'product.png',cfg)
            a=np.asarray(Image.open(root/'product.png'))
            self.assertEqual(p['mode'],'fill');self.assertTrue(np.all(a==[80,100,120]))

    def test_pipeline_exports_ambiguous_original_without_fake_color_comparison(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp);inputs=base/'input';evidence=base/'evidence'
            path=inputs/'测试店/会员/source.jpg';path.parent.mkdir(parents=True)
            Image.new('RGB',(800,1000),(90,100,110)).save(path)
            row=record(status='needs_review',subject_mode='ambiguous',source=str(path.relative_to(inputs)),source_sha256=sha(path))
            group=dict(store='测试店',member='会员',directory='测试店/会员')
            for name,value in [('records.json',[row]),('groups.json',[group]),('sources.json',{})]:save(evidence/name,value)
            seal(evidence,EVIDENCE_SCHEMA,('records.json','groups.json','sources.json'))
            counts=run(inputs,evidence,base/'out');self.assertEqual(counts['products'],1);self.assertEqual(counts['review_groups'],0)
            g=read(base/'out/results.json')[0];p=g['products'][0]
            self.assertEqual(g['sources'][0]['status'],'needs_review')  # Keep the model's evidence intact.
            self.assertEqual(g['sources'][0]['output_status'],'selected');self.assertEqual(p['sha256'],sha(path))
            page=(base/'out/index.html').read_text();self.assertIn('下载 JPG',page)
            self.assertNotIn('src="None"',page);self.assertNotIn('data-image="before"',page)

    def test_configuration_cannot_request_excessive_effects(self):
        for bad in ({'background_strength':1},{'max_upscale':10},{'width':float('nan')},{'max_per_member':2.5}):
            with self.assertRaises(ValueError):settings(bad)

    def test_pipeline_deduplicates_limits_groups_and_preserves_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp);inputs=base/'input';evidence=base/'evidence';rows=[]
            group=dict(store='测试店',member='会员',directory='测试店/会员')
            for n in range(5):
                path=inputs/group['directory']/f'{n}.png';path.parent.mkdir(parents=True,exist_ok=True)
                if n==1:path.write_bytes((path.parent/'0.png').read_bytes())
                else:Image.new('RGB',(800,1000),(80+n*20,100,130)).save(path)
                rows.append(record(asset_id=f'a{n:04}',source=str(path.relative_to(inputs)),source_sha256=sha(path)))
            groups=[group,dict(store='测试店',member='缺图',directory='测试店/缺图')]
            for name,value in [('records.json',rows),('groups.json',groups),('sources.json',{})]:save(evidence/name,value)
            seal(evidence,EVIDENCE_SCHEMA,('records.json','groups.json','sources.json'))
            cfg=base/'config.json';save(cfg,{'enhance':False})
            counts=run(inputs,evidence,base/'out',cfg);self.assertEqual(counts['products'],3);self.assertEqual(counts['missing_groups'],1);self.assertEqual(counts['model_calls'],0)
            result=read(base/'out/results.json')[0]
            self.assertEqual(len({p['source_sha256'] for p in result['products']}),3)
            self.assertIn('duplicate',[s['output_status'] for s in result['sources']]);self.assertIn('not_selected',[s['output_status'] for s in result['sources']])
            self.assertEqual(len(list((base/'out').rglob('*.png'))),3)
            (inputs/rows[0]['source']).write_bytes(b'changed')
            with self.assertRaises(ValueError):run(inputs,evidence,base/'bad',cfg)
            self.assertFalse((base/'bad').exists())

    def test_render_modules_do_not_import_models_or_analysis(self):
        for name in ('render.py','geometry.py','routing.py','pipeline.py','__main__.py'):
            nodes=ast.walk(ast.parse((Path(__file__).parents[1]/name).read_text()))
            modules=[n.module or '' for n in nodes if isinstance(n,ast.ImportFrom)]
            self.assertFalse(any('client' in m or m.endswith('analysis') for m in modules))

if __name__=='__main__':unittest.main()

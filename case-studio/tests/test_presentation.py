import copy, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image, ImageChops
from test_studio import sample
from studio import config, fonts, presentation, privacy, review, store
from studio.common import DATA, WEB_DATA, save, read

REAL_FONT=Path('/root/autodl-fs/case-studio/fonts/NotoSansSC.ttf')
SERIF=Path('/root/autodl-fs/case-studio/fonts/NotoSerifSC.ttf')


class PresentationPolicyTests(unittest.TestCase):
    def test_output_settings_validation(self):
        original=config.load()
        self.addCleanup(lambda:save(WEB_DATA/'settings.json',original,True))
        for value in (True,541,500,2163,1080.0):
            with self.assertRaises(ValueError):config.update({'output_width':value})
        for field,value in [('output_background','white'),('output_background','#123'),('mask_lifestyle','false'),('mask_training','true'),('default_font','../secret')]:
            with self.assertRaises(ValueError):config.update({field:value})
        result=config.update({'output_width':900,'output_background':'#aaBBcc','mask_lifestyle':False})
        self.assertEqual(result['output_background'],'#AABBCC')
        self.assertEqual(result['output_width'],900)
        self.assertNotIn('access_token',result)

    def test_lifestyle_and_training_scopes_are_independent(self):
        m=sample();m['_engine'].update(photos={},metadata={},extras=[
            {'kind':'life','path':'life.jpg'}, {'kind':'training','path':'train.jpg'}])
        m['_render_settings']={'mask_lifestyle':False,'mask_training':True}
        self.assertEqual(set(privacy.source_specs(m)),{'train.jpg'})
        m['_render_settings']['mask_lifestyle']=True
        self.assertEqual(set(privacy.source_specs(m)),{'life.jpg','train.jpg'})
        m['_render_settings']['mask_training']=False
        self.assertEqual(set(privacy.source_specs(m)),{'life.jpg'})
        m['_render_settings']['mask_lifestyle']=False
        self.assertFalse(privacy.source_specs(m))

    def test_letterbox_preserves_content_and_exact_ratio(self):
        prefs=dict(output_width=1080,output_background='#112233')
        for size in ((400,400),(200,800),(1200,600),(1080,1440)):
            im=Image.new('RGB',size,'red');out=presentation.fit(im,prefs)
            self.assertEqual(out.size,(1080,1440))
            box=ImageChops.difference(out,Image.new('RGB',out.size,'#112233')).getbbox()
            self.assertAlmostEqual((box[2]-box[0])/(box[3]-box[1]),size[0]/size[1],delta=.004)
            self.assertEqual(out.getpixel((540,720)),(255,0,0))

    def test_scope_toggle_updates_status_without_rewriting_old_review(self):
        m=sample();m['_engine'].update(photos={},metadata={},extras=[{'kind':'life','path':'life.jpg','name':'生活照'}])
        m['_engine']['privacy']={'version':privacy.VERSION,'sources':{}}
        m['privacy']={**privacy.defaults(),'sticker_id':'test','status':'needs_review',
                      'issues':[{'asset_id':'生活照','reason':'小人物头部不可靠'}]}
        original=copy.deepcopy(m)
        self.assertEqual(privacy.review_state(m,{'mask_lifestyle':False})['status'],'ready')
        self.assertEqual(privacy.review_state(m,{'mask_lifestyle':True})['status'],'needs_review')
        self.assertEqual(m,original)

    def test_font_field_save_and_cache_isolation(self):
        store.initialize();j=store.create('font-test',config.snapshot());m=sample()
        data=store.save_review(j['id'],{'members':[m]},0)
        keys={s:review.preview_key(m,s) for s in ('cover','vs','table','three_views')}
        updated=review.update(j['id'],m['id'],{'version':data['version'],'member':{'fonts':{'cover.title':fonts.DEFAULT}}})
        changed=updated['members'][0]
        self.assertNotEqual(keys['cover'],review.preview_key(changed,'cover'))
        for s in ('vs','table','three_views'):self.assertEqual(keys[s],review.preview_key(changed,s))
        for invalid in ({'profile.name':fonts.DEFAULT},{'table.rows.99.type':fonts.DEFAULT},{'cover.title':'bad'}):
            with self.assertRaises(ValueError):fonts.validate_map(invalid)

    def test_render_freezes_settings_without_changing_review(self):
        data={'members':[sample()]};frozen=presentation.freeze(data)
        self.assertNotIn('_render_settings',data)
        frozen['_render_settings']['output_width']=900
        self.assertNotEqual(presentation.settings()['output_width'],900)

    def test_table_fonts_collapse_without_changing_other_sections(self):
        old={'cover.title':'cover-font','table.table_title':'title-font','table.rows.0.type':'cell-font'}
        self.assertEqual(fonts.unify_table(old),{'cover.title':'cover-font','table.all':'title-font'})
        self.assertEqual(fonts.unify_table(dict(old,**{'table.all':'chosen'}))['table.all'],'chosen')
        self.assertIn('table.rows.0.type',old)
        self.assertTrue(fonts.valid_key('table.all'))


@unittest.skipUnless(REAL_FONT.exists(),'server font required')
class FontLibraryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir=DATA);self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        patcher=patch.object(fonts,'ROOT',self.root);patcher.start();self.addCleanup(patcher.stop)

    def test_upload_preview_deactivate_reuse_and_path_privacy(self):
        info=fonts.upload(REAL_FONT.read_bytes(),'test.ttf','测试字体')
        self.assertNotIn('path',info)
        self.assertTrue(fonts.preview(info['id']).is_file())
        old={'cover.title':info['id']}
        fonts.deactivate(info['id'])
        self.assertEqual(fonts.validate_map(old,old),old)
        with self.assertRaises(ValueError):fonts.validate_map(old)
        again=fonts.upload(REAL_FONT.read_bytes(),'again.ttf')
        self.assertTrue(again['active']);self.assertEqual(again['id'],info['id'])
        self.assertEqual(len(read(self.root/'catalog.json')),1)

    def test_invalid_or_executable_upload_rejected(self):
        for data,name in [(b'<script>','x.ttf'),(b'OTTOjunk','x.otf'),(b'abc','x.svg')]:
            with self.assertRaises(ValueError):fonts.upload(data,name)
        with self.assertRaises(ValueError):fonts.get('../../settings.json')


@unittest.skipUnless(REAL_FONT.exists() and SERIF.exists(),'server rendering environment required')
class FixedRendererTests(unittest.TestCase):
    def test_reports_flow_directly_into_table_without_distortion(self):
        from report_comparison.render import render
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);images={}
            for side,size in [('before',(600,800)),('after',(700,400))]:
                images[side]=root/(side+'.png');Image.new('RGB',size,'#72a086').save(images[side])
            row=dict(type='体重',before='80',after='70',delta='-10',unit='kg')
            for width in (540,1080,2160):
                for count in (1,9,20):
                    case=dict(rows=[],reviewed_rows=[row]*count,pair={},canvas_height=width*4//3)
                    meta=render(case,images,width,REAL_FONT,root/'report.png')
                    bottom=max(g['placement'][1]+g['placement'][3] for g in meta['images'])
                    self.assertEqual(meta['table_frame'][1]-round(width*.046)-bottom,round(width*.018))
                    for g in meta['images']:
                        self.assertAlmostEqual(g['placement'][2]/g['placement'][3],g['source_size'][0]/g['source_size'][1],delta=.01)
                        self.assertFalse(g['content_clipped'])
                    self.assertEqual(meta['table_frame'][1]+meta['table_frame'][3],case['canvas_height']-round(width*.025)-1)

    def test_unified_report_font_overrides_legacy_cell_fonts(self):
        from report_comparison.render import render
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);row=dict(type='体重',before='80',after='70',delta='-10',unit='kg')
            case=dict(rows=[],reviewed_rows=[row],pair={},canvas_height=1440,fonts={'all':str(SERIF)})
            render(case,{},1080,REAL_FONT,root/'a.png')
            case['fonts'].update({'table_title':str(REAL_FONT),'rows.0.type':str(REAL_FONT),'headers.1':str(REAL_FONT)})
            render(case,{},1080,REAL_FONT,root/'b.png')
            self.assertEqual((root/'a.png').read_bytes(),(root/'b.png').read_bytes())

    def test_vs_photos_touch_without_distortion_and_outside_padding_uses_color(self):
        from view_comparison.render import geometry, draw_vs
        for sizes in ([(768,1792),(768,1792)],[(400,900),(300,600)],[(800,300),(1000,300)]):
            g=geometry(sizes,1080,3,1440);a,b=g['photo_boxes']
            self.assertEqual(a[2],b[0]);self.assertEqual(a[1],b[1]);self.assertEqual(g['height'],1440)
            for (w,h),box in zip(sizes,(a,b)):
                self.assertAlmostEqual((box[2]-box[0])/(box[3]-box[1]),w/h,delta=.01)
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp)/'photo.png';Image.new('RGB',(400,1000),'#74a082').save(p)
            c=dict(width=1080,canvas_height=1440,background='#112233',metrics=[],brand_name='UP',nickname='会员',address='地址')
            image=draw_vs([{'asset_id':'a'},{'asset_id':'b'}],{'a':p,'b':p},REAL_FONT,c,'front')
            self.assertEqual(image.size,(1080,1440));self.assertEqual(image.getpixel((10,600)),(17,34,51))

    def test_table_fills_fixed_canvas_and_font_changes_only_targeted_region(self):
        from report_comparison.render import render
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);row=dict(type='体重',before='80',after='70',delta='-10',unit='kg')
            case=dict(rows=[],reviewed_rows=[row],pair={},canvas_height=1440)
            a=render(case,{},1080,REAL_FONT,root/'a.png')
            b=render(dict(case,fonts={'rows.0.type':str(SERIF)}),{},1080,REAL_FONT,root/'b.png')
            self.assertEqual(a['height'],1440);self.assertEqual(a['table_frame'],b['table_frame'])
            self.assertGreater(a['table_frame'][3],1200)
            with Image.open(root/'a.png') as first,Image.open(root/'b.png') as second:
                box=ImageChops.difference(first,second).getbbox()
                self.assertIsNotNone(box);self.assertLess(box[2],250)
            for count in (1,6,20):
                c=render(dict(case,reviewed_rows=[row]*count),{},1080,REAL_FONT,root/f'{count}.png')
                self.assertEqual((c['width'],c['height']),(1080,1440))

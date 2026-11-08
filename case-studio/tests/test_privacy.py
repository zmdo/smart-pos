import base64, copy, io, json, tempfile, unittest
import httpx
from pathlib import Path
from unittest.mock import patch
from PIL import Image, ImageDraw, ImageChops
from test_studio import sample
from studio import privacy, privacy_panels, avatar_api, stickers, config, review, store
from studio.common import DATA, WEB_DATA, save, sha, job_dir


class FacePrivacyTests(unittest.TestCase):
    def setUp(self):
        store.initialize()
        self.folder=Path(tempfile.mkdtemp(dir=DATA))
        self.source=self.folder/'person.png'
        Image.new('RGB',(240,300),'#f02020').save(self.source)
        self.sticker=self.folder/'sticker.png'
        im=Image.new('RGBA',(100,120),'#3d7188'); im.putalpha(255); im.save(self.sticker)
        self.face={'box':[250,200,650,600],'state':'uncovered','front':True,'confidence':.96}
        self.evidence={'faces':[self.face],'source_sha256':sha(self.source),'version':privacy.VERSION}
        self.m=sample(); self.m['_engine'].update(photos={'a0001':str(self.source)},metadata={},extras=[],editors={})
        self.m['privacy']={**privacy.defaults(),'sticker_id':'demo','status':'ready'}
        self.m['_engine']['privacy']={'version':privacy.VERSION,'sources':{str(self.source):self.evidence}}

    def test_normalized_faces_distinguish_existing_sticker_and_side_face(self):
        r=privacy.normalize_scan({'complete':True,'confidence':.96,'faces':[self.face,{**self.face,'state':'sticker'}, {**self.face,'state':'hidden'}]})
        self.assertEqual([x['state'] for x in r['faces']],['uncovered','sticker','hidden'])
        self.assertFalse(r['faces'][1]['front'])

    def test_uncertain_incomplete_low_confidence_and_invalid_boxes_block(self):
        for face in [{**self.face,'box':[500,20,100,30]}, {**self.face,'box':[0,0,float('nan'),20]}, {**self.face,'state':'uncertain'}, {**self.face,'state':'sticker','confidence':.8}]:
            with self.assertRaises(ValueError): privacy.normalize_scan({'complete':True,'confidence':.95,'faces':[face]})
        with self.assertRaises(ValueError): privacy.normalize_scan({'complete':False,'confidence':.99,'faces':[]})
        with self.assertRaises(ValueError): privacy.normalize_scan({'complete':True,'confidence':.4,'faces':[]})

    def test_no_face_is_valid_only_after_complete_scan(self):
        self.assertEqual(privacy.normalize_scan({'complete':True,'confidence':.99,'faces':[]})['faces'],[])

    def test_masked_copy_changes_face_not_source_and_is_cached(self):
        before=self.source.read_bytes()
        with patch.object(stickers,'get',return_value={'path':str(self.sticker)}):
            result=privacy.masked_source(self.m,str(self.source))
            with Image.open(result) as im:
                self.assertNotEqual(im.getpixel((100,100)),(240,32,32))
                self.assertEqual(im.getpixel((0,0)),(240,32,32))
            with patch.object(privacy,'overlay',side_effect=AssertionError('must reuse')):
                self.assertEqual(result,privacy.masked_source(self.m,str(self.source)))
        self.assertEqual(before,self.source.read_bytes())

    def test_multiface_masks_all_uncovered_and_preserves_existing(self):
        faces=[dict(self.face,box=[40,100,260,400]),dict(self.face,box=[720,100,940,400]),dict(self.face,box=[400,650,600,900],state='sticker')]
        out=self.folder/'multi.png'; privacy.overlay(self.source,{'faces':faces},self.sticker,out)
        with Image.open(out) as im:
            self.assertNotEqual(im.getpixel((35,75)),(240,32,32)); self.assertNotEqual(im.getpixel((200,75)),(240,32,32))
            self.assertEqual(im.getpixel((120,235)),(240,32,32))

    def test_border_faces_do_not_error(self):
        out=self.folder/'edge.png'
        privacy.overlay(self.source,{'faces':[dict(self.face,box=[0,0,160,200])]},self.sticker,out)
        self.assertTrue(out.is_file())

    def test_transparent_sticker_pixels_never_gain_an_extra_backing(self):
        avatar=Image.new('RGBA',(80,110),(190,130,80,0))
        for width,height in [(1,1),(3,7),(7,3),(17,23),(23,17),(97,187),(215,287),(300,120)]:
            with self.subTest(size=(width,height)):
                layer=privacy.face_layer(avatar,width,height)
                self.assertIsNone(layer.getchannel('A').getbbox())

    def test_single_photo_keeps_original_pixels_through_sticker_holes(self):
        source=Image.new('RGB',(240,300),'white')
        for x in range(0,240,8):
            ImageDraw.Draw(source).rectangle((x,0,x+3,299),fill='black')
        source.save(self.source)
        avatar=Image.new('RGBA',(100,120),'#3d7188')
        ImageDraw.Draw(avatar).rectangle((25,25,75,95),fill=(0,0,0,0))
        avatar.save(self.sticker)
        for state in ('uncovered','hidden'):
            out=self.folder/(state+'.png')
            privacy.overlay(self.source,{'faces':[dict(self.face,state=state)]},self.sticker,out)
            with Image.open(out) as result:
                self.assertEqual(result.getpixel((108,120)),source.getpixel((108,120)))
                self.assertIsNotNone(ImageChops.difference(result,source).getbbox())

    def test_compact_avatar_reduces_footprint_without_stretching(self):
        avatar=Image.new('RGBA',(634,755),(190,130,80,255))
        for width,height in [(215,287),(97,187)]:
            layer=privacy.face_layer(avatar,width,height)
            old_scale=max(width*1.55/avatar.width,height*1.55/avatar.height)
            self.assertLess(layer.width,avatar.width*old_scale*.80)
            self.assertLess(layer.height,avatar.height*old_scale*.80)
            self.assertAlmostEqual(layer.width/layer.height,avatar.width/avatar.height,delta=.01)

    def test_existing_sticker_never_overwritten(self):
        self.evidence['faces'][0]['state']='sticker'
        with patch.object(stickers,'get',side_effect=AssertionError('not needed')):
            self.assertEqual(privacy.masked_source(self.m,str(self.source)),str(self.source))

    def test_rear_head_is_masked_without_changing_source(self):
        self.evidence['faces'][0].update(state='hidden',front=False)
        before=self.source.read_bytes()
        with patch.object(stickers,'get',return_value={'path':str(self.sticker)}):
            output=privacy.masked_source(self.m,str(self.source))
        self.assertNotEqual(output,str(self.source))
        with Image.open(output) as im:self.assertNotEqual(im.getpixel((100,100)),(240,32,32))
        self.assertEqual(self.source.read_bytes(),before)

    def test_legacy_back_without_head_box_requires_check(self):
        self.m['photos'][0]['view']='back';self.evidence['faces']=[]
        with self.assertRaisesRegex(ValueError,'背向图'):
            privacy.checked_evidence(self.m,str(self.source))
        self.evidence['scan_version']=privacy.SCAN_VERSION
        self.assertEqual(privacy.checked_evidence(self.m,str(self.source))['faces'],[])

    def test_known_body_evidence_reused_and_rear_count_reported(self):
        self.evidence['faces'][0].update(state='hidden',front=False)
        with patch.object(privacy,'scan',side_effect=AssertionError('reuse bound head box')), patch.object(stickers,'get',return_value={}):
            result=privacy.prepare(self.m,'test')
        self.assertEqual(result['privacy']['masked_back_heads'],1)
        self.assertEqual(result['privacy']['masked_faces'],0)

    def test_missing_and_changed_evidence_cannot_leak_source(self):
        self.m['_engine']['privacy']['sources']={}
        with self.assertRaises(ValueError): privacy.masked_source(self.m,str(self.source))
        self.m['_engine']['privacy']['sources']={str(self.source):dict(self.evidence,source_sha256='wrong')}
        with self.assertRaises(ValueError): privacy.masked_source(self.m,str(self.source))

    def test_disabled_explicitly_uses_original(self):
        self.m['privacy']['enabled']=False; self.m['_engine']['privacy']={}
        self.assertEqual(privacy.masked_source(self.m,str(self.source)),str(self.source))

    def test_existing_member_sticker_is_fixed_no_regeneration(self):
        with patch.object(privacy,'scan',return_value=self.evidence), patch.object(stickers,'get',return_value={}), patch.object(avatar_api,'generate',side_effect=AssertionError('no regeneration')):
            result=privacy.prepare(self.m,'test')
        self.assertEqual(result['privacy']['sticker_id'],'demo')
        self.assertEqual(result['privacy']['status'],'ready')

    def test_no_front_uses_standard_gender_and_scan_failure_flags_review(self):
        self.m['privacy']['sticker_id']=None
        with patch.object(privacy,'scan',side_effect=RuntimeError('scan failed')), patch.object(stickers,'default',return_value={'id':'standard'}) as standard, patch.object(stickers,'get',return_value={}):
            result=privacy.prepare(self.m,'test',rescan=True)
        standard.assert_called_once_with('男')
        self.assertEqual(result['privacy']['status'],'needs_review')
        self.assertEqual(len(result['privacy']['issues']),1)

    def test_ai_uses_front_reference_once(self):
        self.m['privacy']['sticker_id']=None
        with patch.object(privacy,'scan',return_value=self.evidence), patch.object(avatar_api,'generate',return_value=(self.sticker,{'model':'qwen'})) as generate, patch.object(stickers,'register',return_value={'id':'new-ai'}), patch.object(stickers,'get',return_value={}):
            result=privacy.prepare(self.m,'test')
        self.assertEqual(result['privacy']['sticker_id'],'new-ai')
        self.assertEqual(generate.call_args.args[1],str(self.source))

    def test_retry_resumes_the_requested_regeneration_nonce(self):
        with patch.object(privacy,'scan',return_value=self.evidence), patch.object(avatar_api,'generate',side_effect=RuntimeError('仍在处理')) as first, patch.object(stickers,'default',return_value={'id':'standard'}), patch.object(stickers,'get',return_value={}):
            result=privacy.prepare(self.m,'test',regenerate=True)
        nonce=first.call_args.kwargs['nonce']
        with patch.object(privacy,'scan',return_value=self.evidence), patch.object(avatar_api,'generate',return_value=(self.sticker,{})) as retry, patch.object(stickers,'register',return_value={'id':'finished'}), patch.object(stickers,'get',return_value={}):
            result=privacy.prepare(result,'test')
        self.assertEqual(retry.call_args.kwargs['nonce'],nonce)
        self.assertNotIn('avatar_issue',result['privacy'])

    def test_gender_mismatch_and_arbitrary_ai_id_rejected(self):
        incoming={'enabled':True,'mode':'library','sticker_id':'female'}
        with patch.object(stickers,'get',return_value={'gender':'female'}), patch.object(stickers,'catalog',return_value=[{'id':'female'}]):
            with self.assertRaises(ValueError): privacy.validate_update(self.m,incoming)
        with patch.object(stickers,'get',return_value={'gender':'male'}), patch.object(stickers,'catalog',return_value=[]):
            with self.assertRaises(ValueError): privacy.validate_update(self.m,{**incoming,'sticker_id':'ai-secret'})

    def test_random_only_matching_or_neutral(self):
        items=[{'id':'m','gender':'male'},{'id':'f','gender':'female'},{'id':'n','gender':'neutral'}]
        with patch.object(stickers,'catalog',return_value=items), patch.object(stickers,'get',side_effect=lambda sid:sid):
            for _ in range(50): self.assertIn(stickers.random_sticker('女'),('f','n'))

    def test_privacy_changes_invalidate_visual_cache_not_report(self):
        before={s:review.preview_key(self.m,s) for s in ('vs','cover','table')}
        self.m['privacy']['enabled']=False
        self.assertNotEqual(before['vs'],review.preview_key(self.m,'vs'))
        self.assertNotEqual(before['cover'],review.preview_key(self.m,'cover'))
        self.assertEqual(before['table'],review.preview_key(self.m,'table'))

    def test_overlay_version_invalidates_images_but_reuses_face_evidence(self):
        before={s:review.preview_key(self.m,s) for s in ('vs','cover','table')}
        with patch.object(stickers,'get',return_value={'path':str(self.sticker)}):
            old=privacy.masked_source(self.m,str(self.source))
            with patch.object(privacy,'RENDER_VERSION','next-overlay'):
                new=privacy.masked_source(self.m,str(self.source))
                self.assertNotEqual(old,new)
                for section in ('vs','cover'):
                    self.assertNotEqual(before[section],review.preview_key(self.m,section))
                self.assertEqual(before['table'],review.preview_key(self.m,'table'))
        self.assertEqual(self.evidence['version'],privacy.VERSION)

    def test_old_background_job_cannot_overwrite_new_review(self):
        jid=store.create('privacy-test',config.snapshot())['id']
        data=store.save_review(jid,{'members':[self.m],'excluded':[]},0)
        def slow(member,*args):
            current=store.review(jid);current['members'][0]['profile']['name']='新名字'
            store.save_review(jid,current,current['version'])
            return member
        with patch.object(privacy,'prepare',side_effect=slow): privacy.run_job(jid,'m001',data['version'])
        self.assertEqual(store.review(jid)['members'][0]['profile']['name'],'新名字')
        self.assertEqual(privacy.status(jid,'m001')['status'],'failed')

    def test_full_preview_rebuilds_after_renderer_change_and_keeps_old_files(self):
        jid=store.create('privacy-preview-test',config.snapshot())['id']
        data=store.save_review(jid,{'members':[self.m],'excluded':[]},0)
        destinations=[]
        def render(_jid,args,_log):
            dest=Path(args[6]);destinations.append(dest)
            save(dest/'result.json',{'products':[]})
        with patch('studio.workflow.command',side_effect=render):
            review.preview(jid,'m001',data['version'])
            with patch.object(privacy,'RENDER_VERSION','new-panel-renderer'):
                review.preview(jid,'m001',data['version'])
                review.preview(jid,'m001',data['version'])
        self.assertEqual(len(destinations),2)
        self.assertNotEqual(destinations[0],destinations[1])
        self.assertTrue(all((p/'result.json').exists() for p in destinations))


class SharedPanelTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir=DATA);self.addCleanup(self.tmp.cleanup)
        root=Path(self.tmp.name);self.source=root/'source.png';self.avatar=root/'avatar.png'
        Image.new('RGB',(240,300),'#f02020').save(self.source)
        Image.new('RGBA',(100,120),'#3d7188').save(self.avatar)
        self.face={'box':[250,200,650,600],'state':'uncovered','confidence':.99,'front':True}
        self.evidence={'faces':[self.face],'source_sha256':sha(self.source),'version':privacy.VERSION}
        self.member=sample();self.member['privacy']={**privacy.defaults(),'sticker_id':'test'}
        self.member['_engine']['privacy']={'version':privacy.VERSION,'sources':{str(self.source):self.evidence}}

    def panel(self,scale=1,size=(480,600),dx=0,dy=0):
        return {'source':str(self.source),'image':Image.new('RGB',size,'#f02020'),
                'transform':[[scale,0,dx],[0,scale,dy],[0,0,1]]}

    def mask(self,panels,**kwargs):
        with patch.object(stickers,'get',return_value={'path':str(self.avatar)}):
            return privacy_panels.mask_panels(self.member,panels,**kwargs)

    def test_source_boxes_follow_resize_and_crop_matrix(self):
        evidence={'faces':[dict(self.face,box=[100,200,300,400])]}
        f=privacy_panels.project_faces(evidence,(1000,1000),[[.5,0,-20],[0,.25,10],[0,0,1]],(500,478))
        self.assertEqual(f[0]['box'],[30,60,130,110])

    def test_panel_keeps_photo_detail_through_transparent_sticker_area(self):
        avatar=Image.new('RGBA',(100,120),'#3d7188')
        ImageDraw.Draw(avatar).rectangle((25,25,75,95),fill=(0,0,0,0))
        avatar.save(self.avatar)
        for state in ('uncovered','hidden'):
            self.face['state']=state
            panel=self.panel()
            for x in range(0,480,8):
                ImageDraw.Draw(panel['image']).rectangle((x,0,x+3,599),fill='black')
            outputs,layout=self.mask([panel])
            l,t,r,b=layout['panels'][0]['faces'][0]['sticker_rect']
            point=((l+r)//2,(t+b)//2)
            self.assertEqual(outputs[0].getpixel(point),panel['image'].getpixel(point))
            self.assertIsNotNone(ImageChops.difference(outputs[0],panel['image']).getbbox())

    def test_nonfinite_or_singular_projection_is_rejected(self):
        for H in [[[1,0,0],[0,1,0],[0,0,0]],[[0,0,0],[0,0,0],[0,0,1]],[[float('nan'),0,0],[0,1,0],[0,0,1]]]:
            with self.assertRaises(ValueError):privacy_panels.project_faces(self.evidence,(240,300),H,(480,600))

    def test_different_zoom_produces_identical_final_artwork_sizes(self):
        before=self.source.read_bytes();panels=[self.panel(1.5),self.panel(2)]
        outputs,layout=self.mask(panels)
        faces=[p['faces'][0] for p in layout['panels']]
        self.assertNotEqual(faces[0]['face_box'],faces[1]['face_box'])
        self.assertEqual(faces[0]['sticker_size'],faces[1]['sticker_size'])
        self.assertEqual(faces[0]['sticker_size'],[230,277])
        for image,f in zip(outputs,faces):
            l,t,r,b=f['sticker_rect']
            self.assertEqual([r-l,b-t],layout['shared_sticker_size'])
            self.assertEqual(image.crop((l,t,r,b)).getextrema(),((61,61),(113,113),(136,136)))
        self.assertEqual(before,self.source.read_bytes())

    def test_near_edge_fits_whole_group_without_moving_chins(self):
        panels=[self.panel(1,dy=-44),self.panel(1)]
        _,layout=self.mask(panels)
        first,second=[p['faces'][0] for p in layout['panels']]
        self.assertEqual(first['sticker_size'],second['sticker_size'])
        for face in (first,second):
            self.assertAlmostEqual(face['sticker_rect'][3],face['head_anchor'][1],delta=.5)
        self.assertGreaterEqual(first['sticker_rect'][1],0)

    def test_top_edge_head_clips_artwork_without_moving_jaw_or_resizing_photo(self):
        for box in ([268,0,652,165], [268,12,638,152]):
            with self.subTest(box=box):
                self.face['box']=box
                panels=[self.panel(),self.panel(dy=100)]
                before=self.source.read_bytes()
                images,layout=self.mask(panels)
                faces=[p['faces'][0] for p in layout['panels']]
                self.assertEqual(faces[0]['sticker_size'],faces[1]['sticker_size'])
                self.assertLess(faces[0]['default_rect'][1],0)
                self.assertGreater(faces[1]['default_rect'][1],0)
                for original,im,f in zip(panels,images,faces):
                    self.assertEqual(im.size,original['image'].size)
                    self.assertAlmostEqual(f['sticker_rect'][3],f['head_anchor'][1],delta=.5)
                    bottom=f['sticker_rect'][3]
                    self.assertEqual(im.crop((0,bottom,im.width,im.height)).tobytes(),
                                     original['image'].crop((0,bottom,im.width,im.height)).tobytes())
                self.assertNotEqual(images[0].getpixel((110,0)),panels[0]['image'].getpixel((110,0)))
                self.assertEqual(self.source.read_bytes(),before)

    def test_top_clipping_does_not_relax_horizontal_or_invalid_jaw_bounds(self):
        self.face['box']=[268,0,652,165]
        for panel in (self.panel(size=(120,600)),self.panel(dy=590)):
            with self.assertRaisesRegex(ValueError,'取景框过紧'):
                self.mask([panel])

    def test_previously_fitting_edge_head_keeps_existing_group_scale(self):
        panel={'image':Image.new('RGB',(300,400))}
        edge={'box':[110,5,190,100],'state':'uncovered'}
        other={'box':[110,100,190,200],'state':'uncovered'}
        # A real top-edge head that already fits with the accepted 15% reduction
        # must not enlarge this panel or any other avatar in the same product.
        size=privacy_panels.fit_shared_size((100,110),[(panel,edge),(panel,other)])
        self.assertEqual(size,(94,103))

    def test_head_with_clear_top_margin_still_requires_avatar_to_fit(self):
        self.face['box']=[268,60,652,165]
        with self.assertRaisesRegex(ValueError,'取景框过紧'):
            self.mask([self.panel()])

    def test_preserved_faces_and_offscreen_faces_do_not_change_the_pair_size(self):
        panels=[self.panel(1),self.panel(3),self.panel(10,dx=-10000)]
        with patch.object(privacy,'checked_evidence',side_effect=[self.evidence,dict(self.evidence,faces=[dict(self.face,state='sticker')]),self.evidence]):
            outputs,layout=self.mask(panels)
        self.assertEqual(layout['shared_sticker_size'],[116,140])
        self.assertEqual(outputs[1].tobytes(),panels[1]['image'].tobytes())
        self.assertEqual(outputs[2].tobytes(),panels[2]['image'].tobytes())

    def test_background_faces_keep_individual_small_size(self):
        self.evidence['faces'].append(dict(self.face,box=[800,500,850,550]))
        _,layout=self.mask([self.panel(1.5),self.panel(2)])
        for panel in layout['panels']:
            main,extra=panel['faces']
            self.assertTrue(main['shared']);self.assertFalse(extra['shared'])
            self.assertLess(extra['sticker_size'][0],main['sticker_size'][0]/2)

    def test_six_panels_share_size_but_follow_each_person(self):
        _,layout=self.mask([self.panel(s) for s in (1,1.1,1.2,1.3,1.4,1.5)])
        self.assertEqual(len({tuple(p['faces'][0]['sticker_size']) for p in layout['panels']}),1)
        self.assertGreater(len({tuple(p['faces'][0]['sticker_rect']) for p in layout['panels']}),1)
        for panel in layout['panels']:
            f=panel['faces'][0];l,t,r,b=f['sticker_rect']
            self.assertAlmostEqual((l+r)/2,f['head_anchor'][0],delta=.5)
            self.assertAlmostEqual(b,f['head_anchor'][1],delta=.5)

    def test_jaw_anchor_prevents_big_avatar_from_covering_neck(self):
        _,layout=self.mask([self.panel(1.5),self.panel(2)])
        a,b=[p['faces'][0] for p in layout['panels']]
        self.assertEqual(a['sticker_size'],b['sticker_size'])
        self.assertNotEqual(a['sticker_rect'],b['sticker_rect'])
        for f in (a,b):
            l,t,r,bottom=f['face_box']
            self.assertAlmostEqual(f['sticker_rect'][3],bottom+.04*(bottom-t),delta=.5)
        self.assertEqual(layout['alignment'],'individual_head_and_jaw')

    def test_reliable_ears_connect_avatar_to_head_not_nose(self):
        face=dict(self.face,box=[100,80,220,230])
        points=[[140,150,.99],[120,120,.99],[180,120,.99],[110,155,.95],[210,155,.96]]
        anchor,method=privacy_panels.head_anchor(face,points)
        self.assertEqual(anchor,[160,236]);self.assertEqual(method,'bilateral_ears')
        side=dict(face,front=False)
        points[3][2]=.1
        anchor,method=privacy_panels.head_anchor(side,points)
        self.assertEqual(anchor,[210,236]);self.assertEqual(method,'visible_ear')

    def test_unreliable_or_unrelated_pose_does_not_displace_avatar(self):
        face=dict(self.face,box=[100,80,220,230])
        for points in [None,[[999,999,.99]]*7,[[140,150,.2]]*7,[[float('nan'),150,.99]]*7]:
            self.assertEqual(privacy_panels.head_anchor(face,points),([160,236],'face_box'))

    def test_each_panel_projects_its_own_head_attachment(self):
        panels=[self.panel(1.5),self.panel(2)]
        for panel in panels:
            scale=panel['transform'][0][0]
            panel['head_points']=[[110*scale,110*scale,.99]]*7
        _,layout=self.mask(panels)
        for scale,p in zip((1.5,2),layout['panels']):
            f=p['faces'][0];l,t,r,b=f['sticker_rect']
            self.assertEqual(f['anchor_method'],'bilateral_ears')
            self.assertAlmostEqual((l+r)/2,110*scale,delta=.5)
        self.assertEqual(layout['panels'][0]['faces'][0]['sticker_size'],layout['panels'][1]['faces'][0]['sticker_size'])

    def test_tight_crop_fails_instead_of_truncating_one_avatar(self):
        with self.assertRaisesRegex(ValueError,'取景框过紧'):
            self.mask([self.panel(2,size=(200,300)),self.panel(1)])

    def test_disabled_masking_keeps_pixels_without_evidence(self):
        self.member['privacy']['enabled']=False;self.member['_engine']['privacy']={}
        panels=[self.panel(1),self.panel(2)]
        result,layout=self.mask(panels)
        self.assertFalse(layout['enabled'])
        self.assertEqual([i.tobytes() for i in result],[p['image'].tobytes() for p in panels])

    def test_all_six_views_including_rear_heads_receive_same_avatar(self):
        panels=[self.panel(1.5)]*6
        rear=dict(self.evidence,faces=[dict(self.face,state='hidden',front=False)])
        with patch.object(privacy,'checked_evidence',side_effect=[self.evidence,self.evidence,rear]*2):
            outputs,layout=self.mask(panels)
        faces=[p['faces'][0] for p in layout['panels']]
        self.assertEqual(len(faces),6)
        self.assertEqual(sum(f['head_state']=='hidden' for f in faces),2)
        self.assertEqual(len({tuple(f['sticker_size']) for f in faces}),1)
        for original,protected in zip(panels,outputs):self.assertNotEqual(original['image'].tobytes(),protected.tobytes())

    def test_rear_head_uses_both_ears_without_a_visible_nose(self):
        face=dict(self.face,box=[100,80,220,230],state='hidden',front=False)
        points=[[110,110,.1]]*7;points[3]=[110,150,.9];points[4]=[210,150,.9]
        anchor,method=privacy_panels.head_anchor(face,points)
        self.assertEqual(anchor,[160,236]);self.assertEqual(method,'bilateral_ears')
        points[4]=[210,150,.1]
        self.assertEqual(privacy_panels.head_anchor(face,points)[1],'face_box')

    def test_missing_evidence_blocks_transformed_output(self):
        self.member['_engine']['privacy']['sources']={}
        with self.assertRaisesRegex(ValueError,'尚未完成检查'):self.mask([self.panel()])


class ExpressiveStyleTests(unittest.TestCase):
    def test_reference_crop_includes_hair_but_excludes_neck(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'reference.png';im=Image.new('RGB',(200,300),'white')
            ImageDraw.Draw(im).rectangle((0,200,199,299),fill='red');im.save(p)
            encoded=avatar_api.data_url(p,[250,200,750,600]).split(',',1)[1]
            with Image.open(io.BytesIO(base64.b64decode(encoded))) as crop:
                self.assertLess(crop.height,200)
                r,g,b=crop.getpixel((crop.width//2,crop.height-1))
                self.assertGreater(g,240);self.assertGreater(b,240)

    def test_gender_styles_and_retry_determinism(self):
        female=avatar_api.build_prompt('女','member-one',reference=True)
        male=avatar_api.build_prompt('男','member-one',reference=True)
        self.assertIn('蝴蝶结',female);self.assertIn('可爱',female)
        self.assertIn('帽',male);self.assertIn('帅气',male)
        self.assertIn('chin is the lowest opaque point',female)
        self.assertIn('参考图仅用于',female)
        self.assertEqual(female,avatar_api.build_prompt('女','member-one',reference=True))
        self.assertNotEqual(female,male)
        self.assertIn('不参考任何真实人物',avatar_api.build_prompt(''))

    def test_current_defaults_and_legacy_ids_both_resolve(self):
        for gender in ('男','女',''):
            item=stickers.default(gender)
            self.assertEqual(item['style_version'],avatar_api.STYLE_VERSION)
            self.assertIn('装饰',item['tags'])
        self.assertEqual(len(stickers.catalog()),100)
        self.assertEqual(stickers.get('ai-standard-male')['id'],'ai-standard-male')
        self.assertNotIn('ai-standard-male',{s['id'] for s in stickers.catalog()})


class AvatarAlphaTests(unittest.TestCase):
    def test_real_alpha_required_and_noise_cleaned(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); raw=root/'raw.png';out=root/'clean.png'
            Image.new('RGB',(100,100),'white').save(raw)
            with self.assertRaises(RuntimeError): avatar_api.clean_alpha(raw,out)
            im=Image.new('RGBA',(100,100),(255,255,255,2)); im.paste((200,150,100,254),(25,25,75,75));im.save(raw)
            avatar_api.clean_alpha(raw,out)
            with Image.open(out) as clean:
                self.assertEqual(clean.size,(50,50));self.assertEqual(clean.getchannel('A').getextrema(),(255,255))

    def test_opaque_rgba_is_not_mistaken_for_transparent(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'raw.png';Image.new('RGBA',(64,64),'white').save(p)
            with self.assertRaises(RuntimeError):avatar_api.clean_alpha(p,p.with_name('out.png'))

    def test_key_redacted_and_reuse_only_same_host(self):
        cfg=config.load();cfg['model']={'base_url':'https://one.test/v1','model':'qwen','api_key':'secret'}
        cfg['image_model'].update(base_url='https://two.test/api/v1',api_key='second-secret',reuse_model_key=True)
        self.assertNotIn('secret',json.dumps(config.public(cfg)))
        with patch.object(config,'load',return_value=cfg):
            with self.assertRaises(RuntimeError):avatar_api.settings()
        cfg['image_model']['base_url']='https://one.test/api/v1'
        with patch.object(config,'load',return_value=cfg):self.assertEqual(avatar_api.settings()['api_key'],'secret')


class AvatarAPITests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.cfg={'base_url':'https://qwen.test/api/v1','model':'qwen-image-2.1-pro','api_key':'private-test-key'}
        buf=io.BytesIO();im=Image.new('RGBA',(100,100),(255,255,255,0));im.paste((160,100,70,255),(20,20,80,80));im.save(buf,'PNG');self.png=buf.getvalue()
        self.requests=[]
        self.client=httpx.Client

    def handler(self,req):
        self.requests.append(req)
        if req.method=='POST':
            self.assertEqual(req.headers['X-DashScope-Async'],'enable')
            self.assertIn('RGBA',json.loads(req.content)['input']['messages'][0]['content'][-1]['text'])
            return httpx.Response(200,json={'output':{'task_id':'job-1','task_status':'PENDING'}})
        if req.url.host=='storage.test':
            self.assertNotIn('Authorization',req.headers)
            return httpx.Response(200,content=self.png)
        return httpx.Response(200,json={'output':{'task_status':'SUCCEEDED','choices':[{'message':{'content':[{'image':'https://storage.test/avatar.png'}]}}]}})

    def run_api(self,handler=None,**kwargs):
        transport=httpx.MockTransport(handler or self.handler)
        with patch.object(avatar_api,'WEB_DATA',self.root), patch.object(avatar_api,'settings',return_value=self.cfg), patch.object(avatar_api.httpx,'Client',side_effect=lambda **kw:self.client(transport=transport,**kw)):
            return avatar_api.generate(avatar_api.STYLE,**kwargs)

    def test_async_result_parsing_auth_isolation_and_cached_reuse(self):
        result,trace=self.run_api()
        self.assertTrue(result.is_file());self.assertFalse(trace['cached'])
        again,trace=self.run_api()
        self.assertEqual(result,again);self.assertTrue(trace['cached'])
        self.assertEqual(sum(r.method=='POST' for r in self.requests),1)
        self.assertNotIn(self.cfg['api_key'],(result.parent/'request.json').read_text())

    def test_timeout_resumes_task_without_another_paid_submission(self):
        with self.assertRaisesRegex(RuntimeError,'任务已保存'):self.run_api(timeout=0)
        result,_=self.run_api()
        self.assertTrue(result.exists());self.assertEqual(sum(r.method=='POST' for r in self.requests),1)

    def test_unknown_submission_does_not_automatically_resubmit(self):
        def broken(req):
            self.requests.append(req)
            raise httpx.ConnectError('lost response')
        with self.assertRaisesRegex(RuntimeError,'结果尚不确定'):self.run_api(broken)
        with self.assertRaisesRegex(RuntimeError,'避免自动重复计费'):self.run_api()
        self.assertEqual(len(self.requests),1)


if __name__=='__main__':unittest.main()

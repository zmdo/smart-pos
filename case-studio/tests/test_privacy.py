import copy, io, json, tempfile, unittest
import httpx
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from test_studio import sample
from studio import privacy, avatar_api, stickers, config, review, store
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

    def test_sticker_and_hidden_never_overwritten(self):
        for state in ('sticker','hidden'):
            self.evidence['faces'][0]['state']=state
            with patch.object(stickers,'get',side_effect=AssertionError('not needed')):
                self.assertEqual(privacy.masked_source(self.m,str(self.source)),str(self.source))

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
            result=privacy.prepare(self.m,'test')
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

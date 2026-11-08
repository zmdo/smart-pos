import asyncio, copy, json, sqlite3, subprocess, sys, tempfile, threading, time, unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from test_studio import sample
from studio import store, review, mask_editor, privacy_panels, privacy, config, storage_backup, workflow
from studio.common import DATA, APP_ROOT, save, cache_dir
from fastapi.testclient import TestClient
import app, httpx


class RequestTests(unittest.TestCase):
    def test_slow_session_read_does_not_block_health_request(self):
        async def run():
            with patch.object(store,'session_valid',side_effect=lambda _:time.sleep(.2) or True),patch.object(store,'listing',return_value=[]):
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app.app),base_url='http://testserver',cookies={'studio_session':'test'}) as client:
                    pending=asyncio.create_task(client.get('/api/jobs'))
                    await asyncio.sleep(.02)
                    response=await client.get('/api/health')
                    self.assertEqual(response.status_code,200);self.assertFalse(pending.done())
                    self.assertEqual((await pending).status_code,200)
        asyncio.run(run())

    def test_compact_save_updates_only_requested_section_and_returns_current_member(self):
        self.addCleanup(workflow.STOPPING.clear)
        store.initialize();jid=store.create('compact-save',config.snapshot())['id'];m=sample()
        store.save_review(jid,{'members':[m,dict(copy.deepcopy(m),id='m002')]},0)
        with TestClient(app.app) as client:
            client.cookies.set('studio_session',store.issue_session())
            cover=dict(m['cover'],title='新标题')
            response=client.patch(f'/api/jobs/{jid}/members/m001?compact=true',headers={'Origin':'http://testserver'},json={'version':1,'member':{'cover':cover}})
            self.assertEqual(response.status_code,200)
            self.assertEqual(set(response.json()),{'member','version'})
            self.assertNotIn('_engine',response.json()['member'])
            saved=store.review(jid)
            self.assertEqual(saved['members'][0]['cover']['title'],'新标题')
            self.assertEqual(saved['members'][1]['cover'],m['cover'])
            self.assertEqual(saved['members'][0]['photos'],m['photos'])


class CacheTests(unittest.TestCase):
    def setUp(self):
        store.initialize()
        self.jid=store.create('performance-regression',config.snapshot())['id']
        self.member=sample()
        self.member['privacy']={**privacy.defaults(),'sticker_id':'demo','status':'ready'}
        store.save_review(self.jid,{'members':[self.member]},0)

    def test_editor_reuses_geometry_for_copy_position_and_rear_toggle(self):
        keys={s:mask_editor.geometry_key(self.member,s) for s in mask_editor.SECTIONS}
        m=copy.deepcopy(self.member)
        m['cover']['title']='改变标题';m['vs']['before_text']='之前'
        m['mask_edits']={'vs:front':{'a0001':{'faces':{'0':{'deleted':True}}}}}
        m['privacy']['mask_back']=False
        for s in keys:self.assertEqual(mask_editor.geometry_key(m,s),keys[s])
        m['cover']['crops']={'a0001':[0,0,100,100]}
        self.assertNotEqual(mask_editor.geometry_key(m,'cover'),keys['cover'])
        self.assertEqual(mask_editor.geometry_key(m,'vs'),keys['vs'])
        m['privacy']['sticker_id']='different'
        for s in keys:self.assertNotEqual(mask_editor.geometry_key(m,s),keys[s])

    def test_cached_editor_applies_live_move_delete_back_state_without_render(self):
        _,_,key,base=mask_editor.context(self.jid,'m001',1,'vs')
        panel={'asset_id':'a0001','size':[400,600],'signature':'geom','back':True,
               'faces':[{'source_face':0,'sticker_size':[100,120],'default_rect':[100,60,200,180],'head_state':'uncovered'}]}
        base.mkdir(parents=True);image=base/'photo.jpg';Image.new('RGB',(40,60)).save(image)
        save(base/'output/editor.json',{'groups':[{'scope':'vs:back','panels':[dict(panel,file=str(image))]}],'sticker_file':str(image)})
        data=store.review(self.jid);m=data['members'][0]
        m['mask_edits']={'vs:back':{'a0001':{'signature':'geom','faces':{'0':{'position':[.5,.3],'deleted':True}}}}}
        m['privacy']['mask_back']=False
        store.save_review(self.jid,data,1)
        with patch('studio.workflow.command') as render:
            loaded=mask_editor.load(self.jid,'m001',2,'vs')
        render.assert_not_called()
        face=loaded['groups'][0]['panels'][0]['faces'][0]
        self.assertEqual(face['sticker_rect'],[200,180,300,300]);self.assertTrue(face['deleted']);self.assertTrue(face['back_disabled'])
        self.assertEqual(loaded['fingerprint'],key)

    def render(self,jid,args,log):
        dest=args[-2];dest.mkdir(parents=True)
        file=dest/'test.png';Image.new('RGB',(2000,2400),'white').save(file)
        save(dest/'result.json',{'products':[{'file':str(file),'kind':args[-1]}]})

    def test_different_sections_render_concurrently_and_both_pointers_survive(self):
        barrier=threading.Barrier(2)
        def render(*args):
            barrier.wait(timeout=4);self.render(*args)
        with patch('studio.workflow.command',side_effect=render) as call,ThreadPoolExecutor(2) as pool:
            results=list(pool.map(lambda s:review.section_preview(self.jid,'m001',1,s),['vs','cover']))
        self.assertEqual(call.call_count,2)
        self.assertEqual(set(store.latest_previews(self.jid,'m001')),{'vs','cover'})
        for result in results:
            with Image.open(store.media_file(self.jid,result['products'][0]['media'])) as im:
                self.assertLessEqual(im.width,1440);self.assertLessEqual(im.height,1920)

    def test_identical_concurrent_requests_render_once_and_old_version_cannot_publish(self):
        with patch('studio.workflow.command',side_effect=self.render) as call,ThreadPoolExecutor(2) as pool:
            list(pool.map(lambda _:review.section_preview(self.jid,'m001',1,'vs'),range(2)))
        self.assertEqual(call.call_count,1)
        data=store.review(self.jid);store.save_review(self.jid,data,1)
        store.set_latest_preview(self.jid,'m001','table',{'products':[]},1)
        self.assertNotIn('table',store.latest_previews(self.jid,'m001'))

    def test_final_products_remain_original_resolution(self):
        root=cache_dir(self.jid);root.mkdir(parents=True)
        file=root/'original.png';Image.new('RGB',(2000,2400)).save(file)
        result=review.output_public(self.jid,{'products':[{'file':str(file)}]})
        self.assertEqual(store.media_file(self.jid,result['products'][0]['media']),file)


class MigrationTests(unittest.TestCase):
    def test_migration_and_backup_preserve_all_rows_including_uncheckpointed_wal(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=root/'source.sqlite3';dest=root/'local.sqlite3';backup=root/'persistent/latest.sqlite3'
            with closing(sqlite3.connect(source)) as c:
                c.execute('PRAGMA journal_mode=WAL');c.execute('CREATE TABLE reviews(id INTEGER PRIMARY KEY,data TEXT)')
                c.execute('INSERT INTO reviews VALUES(?,?)',(1,'审核内容'));c.commit()
                subprocess.run([sys.executable,str(APP_ROOT/'scripts/migrate_runtime.py'),'--source',str(source),'--destination',str(dest)],check=True,capture_output=True)
            with closing(sqlite3.connect(dest)) as c:
                self.assertEqual(c.execute('SELECT data FROM reviews').fetchone()[0],'审核内容')
                c.execute('INSERT INTO reviews VALUES(?,?)',(2,'最新修改'));c.commit()
                with patch.object(storage_backup,'DB_PATH',dest),patch.object(storage_backup,'DB_BACKUP',backup):storage_backup.backup()
            with closing(sqlite3.connect(backup)) as c:
                self.assertEqual(c.execute('PRAGMA integrity_check').fetchone()[0],'ok')
                self.assertEqual(c.execute('SELECT count(*) FROM reviews').fetchone()[0],2)
            self.assertTrue(source.exists());self.assertFalse(Path(str(backup)+'-wal').exists())

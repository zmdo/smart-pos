import copy, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image, ImageChops
from test_studio import sample
from studio import privacy, privacy_panels, mask_editor, review, store, config, stickers
from studio.common import DATA, save, sha


class ManualMaskTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir=DATA);self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.source=self.root/'photo.png';self.avatar=self.root/'sticker.png'
        Image.new('RGB',(240,300),'red').save(self.source)
        Image.new('RGBA',(100,120),'blue').save(self.avatar)
        self.member=sample();self.member['privacy']={**privacy.defaults(),'sticker_id':'demo','status':'ready'}
        self.face={'box':[250,200,650,600],'state':'uncovered','front':True,'confidence':.99}
        self.evidence={'source_sha256':sha(self.source),'faces':[self.face],'version':privacy.VERSION}
        self.member['_engine']['privacy']={'version':privacy.VERSION,'sources':{str(self.source):self.evidence}}
        self.panels=[{'source':str(self.source),'asset_id':a,'image':Image.new('RGB',(480,600),'red'),
                      'transform':[[1,0,0],[0,1,0],[0,0,1]]} for a in ('a0001','a0002')]

    def render(self,scope='vs:front'):
        with patch.object(stickers,'get',return_value={'path':str(self.avatar)}):
            return privacy_panels.mask_panels(self.member,self.panels,scope)

    def edits(self,deleted=False,position=None):
        _,layout=self.render()
        self.member['mask_edits']={'vs:front':{'a0001':{'signature':layout['panels'][0]['signature'],
                          'faces':{'0':{'position':position,'deleted':deleted}}}}}

    def test_move_changes_only_selected_photo_and_product(self):
        old,old_layout=self.render()
        self.edits(position=[.5,.3]);new,new_layout=self.render()
        self.assertEqual(new_layout['panels'][0]['faces'][0]['sticker_rect'][:2],[240,180])
        self.assertEqual(new_layout['shared_sticker_size'],old_layout['shared_sticker_size'])
        self.assertEqual(old[1].tobytes(),new[1].tobytes())
        other,_=self.render('three_views:all')
        self.assertEqual(old[0].tobytes(),other[0].tobytes())

    def test_delete_and_restore_keep_other_avatars_fixed(self):
        old,layout=self.render();self.edits(deleted=True)
        new,changed=self.render()
        self.assertEqual(new[0].tobytes(),self.panels[0]['image'].tobytes())
        self.assertEqual(old[1].tobytes(),new[1].tobytes())
        self.assertEqual(layout['shared_sticker_size'],changed['shared_sticker_size'])
        self.member['mask_edits']={}
        restored,_=self.render();self.assertEqual(old[0].tobytes(),restored[0].tobytes())

    def test_top_clipped_default_can_move_and_restore_without_jumping(self):
        self.face['box']=[268,0,652,165]
        old,layout=self.render()
        default=layout['panels'][0]['faces'][0]['default_rect']
        self.assertLess(default[1],0)
        self.edits(position=[default[0]/480,(default[1]+5)/600])
        _,changed=self.render()
        self.assertEqual(changed['panels'][0]['faces'][0]['sticker_rect'][1],default[1]+5)
        self.edits(position=[default[0]/480,-1])
        _,clamped=self.render()
        self.assertEqual(clamped['panels'][0]['faces'][0]['sticker_rect'],default)
        self.member['mask_edits']={}
        restored,_=self.render()
        self.assertEqual(old[0].tobytes(),restored[0].tobytes())

    def test_changed_crop_or_detection_cannot_apply_stale_position(self):
        self.edits(position=[.5,.3])
        self.panels[0]['transform'][0][2]=20
        _,layout=self.render()
        self.assertIsNone(layout['panels'][0]['faces'][0]['manual_position'])
        self.assertNotEqual(layout['panels'][0]['faces'][0]['sticker_rect'][:2],[240,180])

    def test_back_toggle_keeps_front_photo_and_its_size(self):
        self.panels[1]['back']=True
        old,layout=self.render();self.member['privacy']['mask_back']=False
        new,changed=self.render()
        self.assertEqual(old[0].tobytes(),new[0].tobytes())
        self.assertEqual(new[1].tobytes(),self.panels[1]['image'].tobytes())
        self.assertEqual(layout['shared_sticker_size'],changed['shared_sticker_size'])
        self.assertTrue(changed['panels'][1]['faces'][0]['back_disabled'])

    def test_hidden_head_in_independent_photo_follows_toggle(self):
        self.face['state']='hidden';self.member['privacy']['mask_back']=False
        self.member['_engine'].update(photos={'a0001':str(self.source)},metadata={},editors={},extras=[])
        self.assertEqual(privacy.masked_source(self.member,str(self.source)),str(self.source))
        self.member['privacy']['mask_back']=True
        with patch.object(stickers,'get',return_value={'path':str(self.avatar)}):
            self.assertNotEqual(privacy.masked_source(self.member,str(self.source)),str(self.source))

    def test_legacy_update_preserves_back_setting_and_rejects_invalid_flag(self):
        self.member['privacy']['mask_back']=False
        with patch.object(stickers,'get',return_value={}):
            result=privacy.validate_update(self.member,{'enabled':True,'mode':'ai','sticker_id':'demo'})
            self.assertFalse(result['mask_back'])
            with self.assertRaises(ValueError):
                privacy.validate_update(self.member,{'enabled':True,'mode':'ai','sticker_id':'demo','mask_back':1})


class MaskEditorPersistenceTests(unittest.TestCase):
    def setUp(self):
        store.initialize();self.jid=store.create('mask-editor',config.snapshot())['id']
        self.member=sample();self.member['privacy']={**privacy.defaults(),'sticker_id':'demo','status':'ready'}
        self.data=store.save_review(self.jid,{'members':[self.member]},0)
        self.mid=self.member['id'];self.version=self.data['version']
        _,_,self.key,base=mask_editor.context(self.jid,self.mid,self.version,'vs')
        self.manifest={'groups':[{'scope':'vs:front','panels':[{'asset_id':'a0001','signature':'geometry',
            'size':[400,600],'faces':[{'source_face':0,'sticker_size':[100,120]}]}]}]}
        save(base/'output/editor.json',self.manifest)
        self.payload={'version':self.version,'section':'vs','fingerprint':self.key,
                      'edits':[{'scope':'vs:front','asset_id':'a0001','face':0,'position':[.2,.1],'deleted':False}]}

    def test_save_persists_revision_and_does_not_change_unrelated_data(self):
        result=mask_editor.update(self.jid,self.mid,self.payload)
        saved=result['members'][0];edit=saved['mask_edits']['vs:front']['a0001']
        self.assertEqual(edit['signature'],'geometry');self.assertEqual(edit['faces']['0']['position'],[.2,.1])
        self.assertEqual(saved['photos'],self.member['photos']);self.assertEqual(saved['profile'],self.member['profile'])
        self.assertEqual(result['version'],self.version+1)
        self.assertNotIn('mask_edits',store.review(self.jid,self.version)['members'][0])

    def test_bad_targets_duplicate_missing_and_nonfinite_edits_rejected(self):
        variants=[[],self.payload['edits']*2,
            [dict(self.payload['edits'][0],asset_id='someone-else')],
            [dict(self.payload['edits'][0],scope='cover:front')],
            [dict(self.payload['edits'][0],position=[float('nan'),0])],
            [dict(self.payload['edits'][0],position=[.9,0])],
            [dict(self.payload['edits'][0],position=[True,0])],
            [dict(self.payload['edits'][0],deleted='false')]]
        for edits in variants:
            with self.subTest(edits=edits),self.assertRaises(ValueError):
                mask_editor.update(self.jid,self.mid,dict(self.payload,edits=edits))
        self.assertEqual(store.review(self.jid)['version'],self.version)

    def test_stale_version_or_fingerprint_rejected(self):
        for values in ({'version':self.version-1},{'fingerprint':'old'}):
            with self.assertRaises(store.Conflict):mask_editor.update(self.jid,self.mid,dict(self.payload,**values))

    def test_negative_position_requires_existing_top_clipped_geometry(self):
        edit=dict(self.payload['edits'][0],position=[.2,-.05])
        with self.assertRaisesRegex(ValueError,'不能移出'):
            mask_editor.update(self.jid,self.mid,dict(self.payload,edits=[edit]))
        face=self.manifest['groups'][0]['panels'][0]['faces'][0]
        face['default_rect']=[80,-60,180,60]
        _,_,_,base=mask_editor.context(self.jid,self.mid,self.version,'vs')
        save(base/'output/editor.json',self.manifest)
        with self.assertRaisesRegex(ValueError,'不能移出'):
            mask_editor.update(self.jid,self.mid,dict(self.payload,edits=[dict(edit,position=[.2,-.11])]))
        result=mask_editor.update(self.jid,self.mid,dict(self.payload,edits=[edit]))
        self.assertEqual(result['members'][0]['mask_edits']['vs:front']['a0001']['faces']['0']['position'],[.2,-.05])

    def test_restore_clears_override_and_keeps_other_product(self):
        current=store.review(self.jid)
        current['members'][0]['mask_edits']={'cover:front':{'a0001':{'faces':{}}}}
        current=store.save_review(self.jid,current,self.version)
        _,_,key,base=mask_editor.context(self.jid,self.mid,current['version'],'vs')
        save(base/'output/editor.json',self.manifest)
        edit=dict(self.payload['edits'][0],position=None,deleted=False)
        result=mask_editor.update(self.jid,self.mid,dict(self.payload,version=current['version'],fingerprint=key,edits=[edit]))
        self.assertEqual(result['members'][0]['mask_edits'],{'cover:front':{'a0001':{'faces':{}}}})

    def test_keys_invalidate_only_edited_product(self):
        before={s:review.preview_key(self.member,s) for s in ('vs','cover','three_views','table')}
        self.member['mask_edits']={'vs:front':{'a0001':{'signature':'geom','faces':{'0':{'deleted':True}}}}}
        self.assertNotEqual(before['vs'],review.preview_key(self.member,'vs'))
        for s in ('cover','three_views','table'):self.assertEqual(before[s],review.preview_key(self.member,s))

    def test_cannot_edit_without_ready_enabled_avatar(self):
        for field,value in [('enabled',False),('status','unprepared'),('sticker_id',None)]:
            data=store.review(self.jid);data['members'][0]['privacy'][field]=value
            data=store.save_review(self.jid,data,data['version'])
            with self.assertRaises(ValueError):mask_editor.context(self.jid,self.mid,data['version'],'vs')

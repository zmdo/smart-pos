import copy, unittest
from fastapi.testclient import TestClient
from test_studio import sample
from studio import store, config, review
from studio.render_materials import key
import app

class InstantReviewTests(unittest.TestCase):
    def setUp(self):
        store.initialize();self.j=store.create('instant-test',config.snapshot())['id']
        self.m=sample();self.m['mask_edits']={'vs:front':{'a':{}},'cover:front':{'b':{}}}
        store.save_review(self.j,{'members':[self.m]},0)
        self.client=TestClient(app.app,headers={'Origin':'http://testserver'})
        self.client.post('/api/session',json={'code':config.load()['access_token']}).raise_for_status()
        self.url=f'/api/jobs/{self.j}/members/{self.m["id"]}'
    def test_material_key_ignores_text_and_new_mask_positions(self):
        first=key(self.m);m=copy.deepcopy(self.m);m['cover']['title']='编辑';m['mask_edits']={'vs:front':{'a':{'signature':'canvas-v1:test','faces':{}}}}
        # Empty legacy edit markers in synthetic sample have no usable geometry.
        self.m['mask_edits']={};self.assertEqual(key(self.m),key(m))
    def test_defaults_follow_identity_and_not_later_copy(self):
        r=store.review(self.j);m=r['members'][0];m['profile']['name']='新会员';m['cover']['title']='自定义';store.save_review(self.j,r,1)
        b=self.client.get(self.url+'/defaults');b.raise_for_status();self.assertEqual(b.json()['cover']['title'],self.m['cover']['title']);self.assertEqual(b.json()['vs']['nickname'],review.honorific(m['profile']))
    def test_reset_is_versioned_scoped_and_preserves_photo_labels(self):
        r=store.review(self.j);m=r['members'][0];m['cover']['title']='自定义封面';m['vs']['nickname']='自定义对比';m['photos'][0]['phase']='after';store.save_review(self.j,r,1)
        response=self.client.post(self.url+'/reset',json={'version':2,'section':'cover'});response.raise_for_status()
        new=store.review(self.j)['members'][0]
        self.assertEqual(new['cover'],self.m['cover']);self.assertEqual(new['vs']['nickname'],'自定义对比');self.assertEqual(new['photos'][0]['phase'],'after');self.assertNotIn('cover:front',new['mask_edits']);self.assertIn('vs:front',new['mask_edits'])
        self.assertEqual(self.client.post(self.url+'/reset',json={'version':2,'section':'cover'}).status_code,409)
        self.assertEqual(store.review(self.j,1)['members'][0],self.m)
    def test_six_reset_only_restores_masks(self):
        r=store.review(self.j);r['members'][0]['mask_edits']['three_views:all']={'a':{}};store.save_review(self.j,r,1)
        response=self.client.post(self.url+'/reset',json={'version':2,'section':'three_views'});response.raise_for_status()
        self.assertEqual(store.review(self.j)['members'][0]['photos'],self.m['photos'])
        self.assertNotIn('three_views:all',store.review(self.j)['members'][0]['mask_edits'])
    def test_authentication_covers_new_endpoints(self):
        public=TestClient(app.app,headers={'Origin':'http://testserver'})
        for url in (self.url+'/materials',self.url+'/defaults','/api/fonts/noto-sans-sc/file'):
            self.assertEqual(public.get(url).status_code,401)
        self.assertEqual(public.post(self.url+'/reset',json={'version':1,'section':'cover'}).status_code,401)

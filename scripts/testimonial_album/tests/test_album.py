import ast
import copy
import json
import os
import tempfile
import unittest
from pathlib import Path
from PIL import Image,ImageChops
from scripts.testimonial_album.policy import normalize,score,rank_messages,choose_layout,box
from scripts.testimonial_album.render import render_page,pixel_box
from scripts.testimonial_album.evidence import inventory
from scripts.testimonial_album.pipeline import run
from scripts.testimonial_album import EVIDENCE_SCHEMA
from scripts.body_scan_contracts.io import save,sha,read
from scripts.body_scan_contracts.bundles import seal

FONT=Path(os.environ.get('CASE_TEST_FONT','/root/autodl-fs/case-studio/fonts/NotoSansSC.ttf'))

def message(**extra):
    return dict({'role':'member','text':'训练三个月，肩背力量提升，感谢教练耐心指导。','bbox':[100,100,900,500],
        'role_confidence':.98,'bbox_confidence':.96,'specificity':4,'emotional_expression':3,'readability':5,
        'sentiment':'positive','text_line_height':20,'cut_off':False,'score_reason':'有具体经历'},**extra)

def record(**extra):
    return normalize(dict(is_testimonial=True,reason='反馈',context_bbox=[0,50,1000,950],
                          messages=[message(**extra)],issues=[]),dict(asset_id='a0001',source_size=[600,1000]))

class AlbumTests(unittest.TestCase):
    def test_coach_messages_never_rank_as_member(self):
        r=normalize(dict(is_testimonial=True,context_bbox=[0,0,1000,1000],messages=[message(role='coach'),message()]),{'asset_id':'a0001'})
        self.assertEqual(len(r['messages']),1)
        self.assertEqual(r['messages'][0]['role'],'member')

    def test_negative_and_positive_same_expression_get_same_score(self):
        self.assertEqual(score(message(sentiment='negative')),score(message(sentiment='positive')))

    def test_length_saturates_and_boilerplate_cannot_outrank_specific_feedback(self):
        self.assertEqual(score(message(text='字'*400))[1]['length'],score(message(text='字'*4000))[1]['length'])
        self.assertLess(score(message(text='谢谢'*500,specificity=0,emotional_expression=1))[2],score(message())[2])

    def test_invalid_and_nonfinite_geometry_rejected(self):
        for value in ([0,0,1001,1000],[20,0,10,100],[0,0,float('nan'),1000]):
            with self.assertRaises(ValueError):box(value)

    def test_uncertain_role_does_not_override_confident_hero(self):
        a=record();b=record(text='字'*400,role_confidence=.5)
        b['asset_id']='a0002';b['messages'][0]['message_id']='a0002-m01'
        self.assertEqual(rank_messages([b,a])[0]['asset_id'],'a0001')

    def test_context_expands_to_keep_whole_member_bubble(self):
        r=normalize(dict(is_testimonial=True,context_bbox=[100,200,800,400],messages=[message()]),{'asset_id':'a0001'})
        self.assertEqual(r['context_bbox'],[100,100,900,500])

    def test_inventory_excludes_reference_and_nonstore_directories(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);rows=[]
            for i,(store,ref) in enumerate([('参考模板',False),('说明文件',False),('测试店',True),('测试店',False)]):
                rows.append(dict(asset_id=f'a{i:04}',store=store,member='会员',reference_material=ref,
                    source=f'/old/私教会员案例项目/{store}/会员/image{i}.png',source_sha256='a'*64,qwen={'kind':'testimonial'}))
            p=root/'audit.json';p.write_text(json.dumps(rows))
            selected,groups=inventory(root,p)
            self.assertEqual(len(selected),1);self.assertEqual(len(groups),1)

    def test_render_modules_do_not_import_model_clients(self):
        for name in ('render.py','pipeline.py','__main__.py'):
            p=Path(__file__).parents[1]/name
            modules=[n.module or '' for n in ast.walk(ast.parse(p.read_text())) if isinstance(n,ast.ImportFrom)]
            self.assertFalse(any('client' in n or n.endswith('evidence') for n in modules))

    @unittest.skipUnless(FONT.exists(),'font not installed')
    def test_all_layouts_preserve_screenshot_pixels_and_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);p=root/'source.png'
            im=Image.new('RGB',(600,1000),'#e9ecef')
            for y in range(100,900,70):
                from PIL import ImageDraw
                ImageDraw.Draw(im).rectangle((60,y,540,y+25),fill=(y%255,40,100))
            im.save(p);source=p.read_bytes();r=record(text='字'*400);before=copy.deepcopy(r)
            for layout in ('long_story','focused_story','short_reply','wide_reply'):
                out=root/(layout+'.png');result=render_page([r],{'a0001':p},rank_messages([r])[0],FONT,out,{'layout':layout})
                with Image.open(out) as product:
                    self.assertEqual(product.size,(1080,1440))
                    self.assertEqual(product.getpixel((0,0)),(230,0,18))
                    self.assertEqual(len(result['layers']),1)
                    for layer in result['layers']:
                        x,y,w,h=layer['placement'];expected=im.crop(tuple(layer['crop'])).resize((w,h),Image.Resampling.LANCZOS)
                        self.assertIsNone(ImageChops.difference(product.crop((x,y,x+w,y+h)),expected).getbbox())
                        self.assertTrue(layer['uniform_scale']);self.assertFalse(layer['content_clipped'])
            self.assertEqual(p.read_bytes(),source);self.assertEqual(r,before)

    @unittest.skipUnless(FONT.exists(),'font not installed')
    def test_two_sources_use_once_each_on_same_fixed_canvas(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);a=record();b=copy.deepcopy(a);b['asset_id']='a0002'
            b['messages'][0]['message_id']='a0002-m01'
            paths={}
            for r in (a,b):
                p=root/(r['asset_id']+'.png');Image.new('RGB',(600,1000),'white').save(p);paths[r['asset_id']]=p
            out=root/'out.png';result=render_page([a,b],paths,rank_messages([a,b])[0],FONT,out,{})
            self.assertEqual([r['asset_id'] for r in result['layers']],['a0001','a0002'])
            with Image.open(out) as im:self.assertEqual(im.size,(1080,1440))
            with self.assertRaisesRegex(ValueError,'duplicate_source'):
                render_page([a,a],paths,rank_messages([a])[0],FONT,root/'bad.png',{})

    def test_layout_variants_depend_on_length_and_score(self):
        self.assertEqual(choose_layout({'char_count':400,'score':90}),'long_story')
        self.assertEqual(choose_layout({'char_count':200,'score':75}),'focused_story')
        self.assertEqual(choose_layout({'char_count':60,'score':80}),'short_reply')

    @unittest.skipUnless(FONT.exists(),'font not installed')
    def test_pipeline_deduplicates_across_pages_and_keeps_one_batch_size(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp);root=base/'input';evidence=base/'evidence';records=[]
            groups=[dict(store='测试店',member=m,directory='测试店/'+m) for m in ('多图会员','单图会员')]
            # Five unique screenshots plus a byte-identical sixth must yield 3 pages.
            for i,group in enumerate([groups[0]]*6+[groups[1]],1):
                p=root/group['directory']/f'{i}.png';p.parent.mkdir(parents=True,exist_ok=True)
                if i==6:p.write_bytes((root/groups[0]['directory']/'1.png').read_bytes())
                else:Image.new('RGB',(600,1000),(i*20,50,90)).save(p)
                r=record();r.update(group,asset_id=f'a{i:04}',source=str(p.relative_to(root)),source_sha256=sha(p))
                r['messages'][0]['message_id']=r['asset_id']+'-m01';records.append(r)
            for name,value in [('records.json',records),('groups.json',groups),('sources.json',{})]:save(evidence/name,value)
            seal(evidence,EVIDENCE_SCHEMA,('records.json','groups.json','sources.json'))
            config=base/'config.json';save(config,{'width':720,'height':960,'members':{groups[1]['directory']:{'width':1080,'height':1440}}})
            out=base/'products';counts=run(root,evidence,out,FONT,config)
            self.assertEqual(counts['pages'],4);self.assertEqual(counts['model_calls'],0)
            results=read(out/'results.json');self.assertEqual([len(r['pages']) for r in results],[3,1])
            self.assertEqual([len(p['layers']) for p in results[0]['pages']],[2,2,1])
            for r in results:
                used=[layer['asset_id'] for p in r['pages'] for layer in p['layers']]
                self.assertEqual(len(used),len(set(used)))
                hashes=[next(s['source_sha256'] for s in r['sources'] if s['asset_id']==aid) for aid in used]
                self.assertEqual(len(hashes),len(set(hashes)))
                for page in r['pages']:
                    with Image.open(out/page['file']) as im:self.assertEqual(im.size,(720,960))
            self.assertIn('统一720×960',(out/'index.html').read_text())

    @unittest.skipUnless(FONT.exists(),'font not installed')
    def test_too_long_brand_fails_without_an_unbounded_font_loop(self):
        from scripts.testimonial_album.render import draw_brand
        with self.assertRaisesRegex(ValueError,'brand_text_too_long'):
            draw_brand(Image.new('RGB',(720,960)),[500,0,160,960],FONT,{'brand':'长'*40})

    @unittest.skipUnless(FONT.exists(),'font not installed')
    def test_adaptive_brand_elements_do_not_overlap_or_leave_the_panel(self):
        from scripts.testimonial_album.render import draw_brand
        for w,h in ((1050,130),(1050,400),(1050,600),(1050,1200),(150,1410),(330,1410)):
            elements=draw_brand(Image.new('RGB',(w,h)),[0,0,w,h],FONT,{})
            for i,element in enumerate(elements):
                l,t,r,b=element['bounds'];self.assertTrue(0<=l<r<=w and 0<=t<b<=h,(w,h,element))
                for other in elements[:i]:
                    ol,ot,orr,ob=other['bounds']
                    self.assertFalse(max(l,ol)<min(r,orr) and max(t,ot)<min(b,ob),(element,other))

    @unittest.skipUnless(FONT.exists(),'font not installed')
    def test_short_and_tall_images_fill_their_frame_without_losing_pixels(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for w,h in ((1200,220),(1000,1000),(600,1300)):
                p=root/f'{w}-{h}.png';Image.new('RGB',(w,h),'#e9ecef').save(p)
                r=record();r['context_bbox']=[0,0,1000,1000]
                result=render_page([r],{'a0001':p},rank_messages([r])[0],FONT,root/'out.png',{})
                layer=result['layers'][0]
                self.assertEqual(layer['crop'],[0,0,w,h]);self.assertEqual(len(result['layers']),1)
                self.assertGreaterEqual(layer['frame_fill'],.99)

if __name__=='__main__':unittest.main()

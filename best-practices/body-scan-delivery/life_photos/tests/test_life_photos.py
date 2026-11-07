import ast
from pathlib import Path
import tempfile
import unittest
from scripts.body_scan_contracts.io import save,read,sha
from life_photos.pipeline import run,inventory


class LifePhotoTests(unittest.TestCase):
    def source(self,root,aid='a0001',kind='life_photo',store='测试店',name='source.JPG',**extra):
        rel=Path(store)/'会员'/name;path=root/rel;path.parent.mkdir(parents=True,exist_ok=True)
        path.write_bytes(b'original bytes including metadata: '+aid.encode())
        return dict(asset_id=aid,store=store,member='会员',source=str(rel),source_sha256=sha(path),qwen={'kind':kind},**extra)

    def test_classification_precedence_store_scope_and_no_extra_quality_filter(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);audit=root/'audit.json'
            rows=[self.source(root,'a0001',confidence=.1),
                  self.source(root,'a0002',kind='daily_training',old={'kind':'life_photo'}),
                  self.source(root,'a0003',store='参考模板'),
                  self.source(root,'a0004',reference_material=True),
                  self.source(root,'a0005',store='会员案例素材生产标准（说明文件）')]
            save(audit,rows);selected,groups=inventory(root,audit)
            self.assertEqual([r['asset_id'] for r in selected],['a0001']);self.assertEqual(len(groups),1)

    def test_every_selected_original_is_byte_identical_with_no_stage_or_limit(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp);root=base/'input';audit=base/'audit.json';out=base/'products'
            rows=[self.source(root,f'a{i:04}',name=f'{i}.JPG') for i in range(1,6)]
            rows.append(self.source(root,'a0006',kind='body_scan',store='无生活照店'))
            save(audit,rows);counts=run(root,audit,out);self.assertEqual(counts['products'],5)
            self.assertEqual(counts['missing_groups'],1);self.assertEqual(counts['model_calls'],0)
            result=next(g for g in read(out/'results.json') if g['products'])
            for p in result['products']:
                self.assertEqual(sha(out/p['file']),sha(root/p['source']))
                self.assertTrue(p['file'].endswith('.JPG'));self.assertFalse(p['processing_applied']);self.assertNotIn('phase',p)
            with self.assertRaises(FileExistsError):run(root,audit,out)

    def test_tampered_or_missing_original_fails_before_creating_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp);root=base/'input';audit=base/'audit.json';row=self.source(root)
            save(audit,[row]);path=root/row['source'];path.write_bytes(b'changed')
            with self.assertRaises(ValueError):run(root,audit,base/'bad')
            self.assertFalse((base/'bad').exists());path.unlink()
            with self.assertRaises(FileNotFoundError):run(root,audit,base/'missing')
            self.assertFalse((base/'missing').exists())

    def test_non_image_returns_reason_and_duplicate_ids_or_traversal_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp);root=base/'input';audit=base/'audit.json';row=self.source(root,name='clip.mp4')
            save(audit,[row]);counts=run(root,audit,base/'out')
            self.assertEqual(counts['products'],0);self.assertEqual(counts['rejected_sources'],1)
            self.assertTrue(read(base/'out/review.json')[0]['reason'])
            save(audit,[row,row])
            with self.assertRaises(ValueError):inventory(root,audit)
            row['source']='测试店/会员/../../../outside.jpg';save(audit,[row])
            with self.assertRaises(ValueError):inventory(root,audit)

    def test_exporter_has_no_image_processing_or_model_dependencies(self):
        tree=ast.parse((Path(__file__).parents[1]/'pipeline.py').read_text())
        modules=[n.module or '' for n in ast.walk(tree) if isinstance(n,ast.ImportFrom)]
        modules += [a.name for n in ast.walk(tree) if isinstance(n,ast.Import) for a in n.names]
        self.assertFalse(any(any(x in module for x in ('PIL','cv2','numpy','client','training_daily')) for module in modules))


if __name__=='__main__':unittest.main()

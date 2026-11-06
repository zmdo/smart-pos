import argparse
import hashlib
import json
import shutil
import zipfile
from collections import Counter
from pathlib import Path


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def build(source, out, default_case=None, default_category=None):
    source = Path(source).resolve(); out = Path(out).resolve()
    result_path = source/'result.json'
    original_hash = sha(result_path)
    result = json.loads(result_path.read_text(encoding='utf-8'))
    rows = {r['asset_id']:r for r in result['items']}
    if len(rows) != len(result['items']):
        raise ValueError('duplicate_input_asset')
    products = {p['product_id']:p for p in result['outputs']}
    if len(products) != len(result['outputs']):
        raise ValueError('duplicate_input_product')
    grids = [p for p in products.values() if p['kind'] == 'three_views']
    if not grids:
        raise ValueError('no_complete_three_view_case')
    out.mkdir(parents=True, exist_ok=False); (out/'media').mkdir()
    copies = {}; cases = []

    def copy_product(product):
        pid = product['product_id']
        if pid in copies:
            return copies[pid]
        path = (source/product['file']).resolve()
        if not path.is_relative_to(source) or sha(path) != product['sha256']:
            raise ValueError('product_path_or_hash_mismatch')
        # Generated names contain no member data and need no URL escaping.
        filename = f'media/image-{len(copies)+1:03d}{path.suffix.lower()}'
        shutil.copyfile(path, out/filename)
        if sha(out/filename) != product['sha256']:
            raise ValueError('copied_product_changed')
        value = {k:product[k] for k in ('product_id','kind','view','width','height','asset_ids','sha256')}
        value.update(file=filename, requires_review=product['requires_review'],
                     renderer_version=product.get('renderer_version','body-delivery-v1'))
        if product.get('presentation'):value['presentation']=product['presentation']
        copies[pid] = value
        return value

    family = lambda v:'side' if v.startswith('side') else v
    expected = [(phase,view) for phase in ('before','after') for view in ('front','side','back')]
    for grid in grids:
        members = [rows[k] for k in grid['asset_ids']]
        if len({r['asset_id'] for r in members}) != 6 or [(r['phase'],family(r['view'])) for r in members] != expected:
            raise ValueError('invalid_three_view_slots')
        if any((r['group_id'],r['store'],r['member']) != (grid['group_id'],grid['store'],grid['member']) for r in members):
            raise ValueError('case_identity_mismatch')
        comparisons = []
        for i,view in enumerate(('front','side','back')):
            pair_ids = [members[i]['asset_id'],members[i+3]['asset_id']]
            matches = [p for p in products.values() if p['group_id']==grid['group_id'] and p['kind']=='vs'
                       and p['view']==view and p['asset_ids']==pair_ids]
            if len(matches) != 1:
                raise ValueError('matching_comparison_missing')
            comparisons.append(copy_product(matches[0]))
        singles = []
        for member in members:
            matches = [p for p in products.values() if p['kind']=='single' and p['asset_ids']==[member['asset_id']]]
            if len(matches) != 1:
                raise ValueError('matching_single_missing')
            singles.append(copy_product(matches[0]))
        cases.append({k:grid[k] for k in ('group_id','store','member')} | {
            'grid':copy_product(grid), 'comparisons':comparisons, 'singles':singles,
            'review_count':sum(r['requires_review'] for r in members),
            'label_counts':dict(Counter(r['label_kind'] for r in members)),
            'slots':[{k:r.get(k) for k in ('asset_id','view','phase','label','label_kind','requires_review')} for r in members]})
    cases.sort(key=lambda c:(c['review_count']>0,c['store'],c['member']))
    counts = {'cases':len(cases), 'stores':len({c['store'] for c in cases}),
              'three_views':len(cases),'vs':len(cases)*3,'single':len(cases)*6}
    seamless = all(p.get('layout')=='seamless-3x2' for p in grids)
    reference_vs = all(p.get('renderer_version')=='body-same-view-reference-v3' for c in cases for p in c['comparisons'])
    if default_case and default_case not in {c['group_id'] for c in cases}:raise ValueError('unknown_default_case')
    if default_category and default_category not in ('three_views','vs','single'):raise ValueError('unknown_default_category')
    default_case=default_case or cases[0]['group_id']
    data = {'title':'三视图体测 · 当前成品样式','version':'reference-v3' if reference_vs else 'seamless-v2' if seamless else 'current-v1',
            'vs_style':'reference' if reference_vs else 'basic','default_category':default_category or ('vs' if reference_vs else 'three_views'),
            'grid_style':'seamless' if seamless else 'labeled',
            'source_delivery':result['delivery_id'],'source_revision':result['revision'],
            'default_case':default_case,'counts':counts,'cases':cases}
    templates = Path(__file__).parent
    payload = json.dumps(data,ensure_ascii=False).replace('<','\\u003c').replace('\u2028','\\u2028').replace('\u2029','\\u2029')
    html = (templates/'template.html').read_text(encoding='utf-8').replace('<!--GALLERY_DATA-->',payload)
    (out/'index.html').write_text(html,encoding='utf-8')
    for name in ('gallery.css','gallery.js'):
        shutil.copyfile(templates/name,out/name)
    (out/'cases.json').write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    if sha(result_path) != original_hash:
        raise ValueError('source_result_changed_during_build')
    verification = {'passed':True, 'source_result_sha256':original_hash, 'source_result_unchanged':True,
                    'copied_images':len(copies), 'all_image_bytes_unchanged':True, 'model_requests':0,
                    'image_processing':False, 'counts':counts, 'default_case':next(c['member'] for c in cases if c['group_id']==default_case)}
    (out/'verification.json').write_text(json.dumps(verification,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    with zipfile.ZipFile(out/'preview.zip','w',zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(out.rglob('*')):
            if path.is_file() and path.name!='preview.zip':
                archive.write(path,path.relative_to(out))
    return verification


if __name__=='__main__':
    parser=argparse.ArgumentParser(description='使用既有成品生成离线分类预览，不运行上游处理或模型')
    parser.add_argument('--input',type=Path,required=True,help='含 result.json 的成品版本目录')
    parser.add_argument('--out',type=Path,required=True,help='全新预览目录')
    parser.add_argument('--default-case',help='默认展示的 group_id')
    parser.add_argument('--default-category',choices=('three_views','vs','single'))
    args=parser.parse_args()
    print(json.dumps(build(args.input,args.out,args.default_case,args.default_category),ensure_ascii=False,indent=2))

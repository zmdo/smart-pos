"""Verify delivery coverage, phase markers, real pair dependencies and review queues."""
import argparse
import zipfile
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path

from PIL import Image,ImageChops

from scripts.body_scan_contracts.labels import family
from .pipeline import current,read,sha,digest_json,save
from .render import GRID_RENDERER,VS_RENDERER
from .vs_layout import geometry


class Links(HTMLParser):
    def __init__(self):super().__init__();self.paths=[]
    def handle_starttag(self,tag,attrs):
        self.paths.extend(v for k,v in attrs if k in ('href','src') and v and not v.startswith(('#','http','/api/')))


def verify(root):
    root=Path(root);result,directory=current(root);source=read(root/'private-inputs.json')
    rows=result['items'];lookup={r['asset_id']:r for r in rows}
    original=read(Path(source['phase_input'])/('labels.json' if source.get('classification_schema') else 'summary.json'))
    if len(rows)!=len(lookup) or set(lookup)!={r['asset_id'] for r in original}:raise ValueError('input_image_coverage_changed')
    if any(sha(p)!=h for p,h in source['bindings'].items()):raise ValueError('bound_source_changed')
    if digest_json(source['bindings'])!=result['source_manifest_sha256']:raise ValueError('manifest_identity_changed')
    for row in rows:
        if row['phase'] not in ('before','after'):raise ValueError('unassigned_phase')
        suffix={'inferred':'（推断）','pending':'（待审）'}.get(row['label_kind'],'')
        expected={'before':'训练前','after':'训练后'}[row['phase']]+suffix
        if row['label']!=expected or bool(suffix) and not row['requires_review']:raise ValueError('missing_uncertainty_label')
    single_ids=[]
    for output in result['outputs']:
        selected=[lookup[k] for k in output['asset_ids']]
        if output['requires_review']!=any(r['requires_review'] for r in selected):raise ValueError('output_review_flag_incorrect')
        if set(output['review_asset_ids'])!={r['asset_id'] for r in selected if r['requires_review']}:raise ValueError('review_dependencies_incomplete')
        if sha(directory/output['file'])!=output['sha256']:raise ValueError('product_bytes_changed')
        with Image.open(directory/output['file']) as image:
            if image.size!=(output['width'],output['height']):raise ValueError('wrong_canvas_size')
            if output.get('renderer_version')==GRID_RENDERER:
                if output['kind']!='three_views' or output.get('image_annotations') is not False or image.format!='PNG':
                    raise ValueError('invalid_seamless_grid_metadata')
                tile_width,tile_height=image.width//3,image.height//2
                if image.size!=(tile_width*3,tile_height*2):raise ValueError('invalid_grid_dimensions')
                for index,row in enumerate(selected):
                    with Image.open(source['photos'][row['asset_id']]) as original:
                        if original.size!=(tile_width,tile_height):raise ValueError('grid_frame_size_changed')
                        x=(index%3)*tile_width;y=(index//3)*tile_height
                        if ImageChops.difference(image.crop((x,y,x+tile_width,y+tile_height)).convert('RGB'),original.convert('RGB')).getbbox():
                            raise ValueError('grid_frame_pixels_changed')
            elif output.get('renderer_version') in (VS_RENDERER,'body-same-view-reference-v3'):
                sizes=[]
                for row in selected:
                    with Image.open(source['photos'][row['asset_id']]) as original:sizes.append(original.size)
                context=output['presentation']
                layout=geometry(sizes,context['width'],len(context['metrics']))
                if image.size!=(layout['width'],layout['height']):raise ValueError('wrong_vs_canvas_size')
                for (w,h),box in zip(sizes,layout['photo_boxes']):
                    if abs((box[2]-box[0])-(box[3]-box[1])*w/h)>1.01:raise ValueError('vs_photo_aspect_changed')
            elif image.size!=(1080,1440):raise ValueError('wrong_legacy_canvas_size')
        if output['kind']=='single':single_ids.extend(output['asset_ids'])
        elif output['kind']=='vs':
            if [r['phase'] for r in selected]!=['before','after'] or selected[0]['source_sha256']==selected[1]['source_sha256']:
                raise ValueError('invalid_before_after_pair')
        else:
            if [r['phase'] for r in selected]!=['before']*3+['after']*3:raise ValueError('invalid_grid_phases')
            if [family(r['view']) for r in selected]!=['front','side','back']*2:raise ValueError('invalid_grid_view_order')
    if sorted(single_ids)!=sorted(lookup):raise ValueError('some_original_missing_single_output')
    expected={r['asset_id'] for r in rows if r['requires_review']}
    review=read(directory/'review.json')
    if {r['asset_id'] for r in review['items']}!=expected or set(result['review']['asset_ids'])!=expected:raise ValueError('review_queue_incomplete')
    parser=Links();parser.feed((directory/'index.html').read_text())
    if any(not (directory/p).is_file() for p in parser.paths):raise ValueError('broken_preview_link')
    with zipfile.ZipFile(directory/'products.zip') as archive:
        if archive.testzip() or any('private-inputs' in p or p.startswith('audits/') for p in archive.namelist()):raise ValueError('invalid_download_bundle')
    checks={'passed':True,'revision':result['revision'],'images':len(rows),'products':len(result['outputs']),
            'product_kinds':dict(Counter(o['kind'] for o in result['outputs'])),'label_kinds':result['counts']['label_kinds'],
            'review_images':len(expected),'review_products':result['counts']['review_products'],
            'source_files_unchanged':len(source['bindings']),'preview_links_checked':len(parser.paths),
            'every_input_has_single_product':True,'distinct_source_pairs':True,'verified_photo_chronology':False}
    save(root/'verification.json',checks)
    return checks


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--delivery',type=Path,required=True)
    print(verify(parser.parse_args().delivery))

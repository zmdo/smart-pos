"""Offline Chromium runs exactly the same Canvas module as the audit UI."""
import base64, copy, mimetypes, shutil
from pathlib import Path
from urllib.parse import urlparse
from PIL import Image, ImageOps
from .common import APP_ROOT, read, save, sha
from . import fonts, privacy, presentation
from .render_materials import build

ORIGIN='https://studio-render.invalid'


def render(review_path, mid, out, section=None, editor=False):
    from playwright.sync_api import sync_playwright
    from .rendering import testimonial_text
    if section not in (None,'vs','cover','table','three_views'):
        raise ValueError('预览区域无效')
    review=read(review_path)
    m=copy.deepcopy(next(m for m in review['members'] if m['id']==mid))
    prefs=review.get('_render_settings') or presentation.settings()
    m['_render_settings']=prefs;m['render_settings']=prefs
    m['privacy']=privacy.review_state(m,prefs)
    m['fonts']=fonts.unify_table(m.get('fonts',{}))
    out.mkdir(parents=True,exist_ok=False)
    materials=build(m,out/'materials')
    resources={f'/assets/{k}':Path(v) for k,v in materials.pop('files').items()}
    materials['assets']={k.split('/')[-1]:ORIGIN+k for k in resources}
    font_rows=[]
    font_ids={prefs['default_font'],*prefs.get('font_overrides',{}).values(),*m['fonts'].values()}
    for row in fonts.catalog():
        if row['id'] not in font_ids:continue
        url='/fonts/'+row['id'];resources[url]=fonts.browser_file(row['id'])
        font_rows.append(dict(id=row['id'],url=ORIGIN+url))
    for path in (APP_ROOT/'static/render').glob('*.js'):
        resources['/render/'+path.name]=path
    def route(request):
        url=urlparse(request.request.url)
        if url.netloc!='studio-render.invalid':
            request.abort();return
        if url.path=='/':
            request.fulfill(content_type='text/html',body='<!doctype html><meta charset="utf-8"><title>Offline renderer</title>');return
        path=resources.get(url.path)
        if path is None:
            request.abort();return
        request.fulfill(path=path,content_type='text/javascript' if path.suffix=='.js' else mimetypes.guess_type(path)[0] or 'application/octet-stream')
    public={k:v for k,v in m.items() if not k.startswith('_')}
    products=[];groups=[];cover_sources=[]
    def product(path,kind,name,**extra):
        with Image.open(path) as image:size=list(image.size)
        products.append(dict(file=str(path),kind=kind,name=name,size=size,sha256=sha(path),**extra))
    with sync_playwright() as pw:
        browser=pw.chromium.launch(headless=True,args=['--disable-dev-shm-usage','--disable-gpu'])
        try:
            page=browser.new_page();page.route('**/*',route);page.goto(ORIGIN)
            info=page.evaluate('''async ({member,materials,fonts})=>{
              const R=await import('/render/canvas.js'),{Assets}=await import('/render/assets.js');
              window.engine={R,member,assets:new Assets(materials,fonts)};
              return R.plans(member);
            }''',dict(member=public,materials=materials,fonts=font_rows))
            gaps=info['gaps']
            for plan in info['products']:
                if section and plan['kind']!=('report' if section=='table' else section):continue
                result=page.evaluate('''async ({plan,editor,width})=>{
                  const {R,member,assets}=engine;
                  try{
                    if(editor){
                      const {images,layout}=await R.photoPanels(member,assets,plan,{neutral:true});
                      return {layout,images:images.map(c=>c.toDataURL('image/png'))};
                    }
                    const r=await R.render(null,member,assets,plan,{width});
                    return {image:r.canvas.toDataURL(plan.name.endsWith('.png')?'image/png':'image/jpeg',.94),
                      layout:r.privacy_layout,layout_hash:r.layout_hash,cover_sources:r.cover_sources};
                  }catch(e){return {error:e.message};}
                }''',dict(plan=plan,editor=editor,width=prefs['output_width']))
                if result.get('error'):
                    if plan['kind']=='cover' and not m['cover']['crops']:
                        gaps.append(dict(product='cover',reason=result['error']));continue
                    raise ValueError(result['error'])
                if editor:
                    records=[]
                    photos={p['asset_id']:p for p in m['photos']}
                    for i,(panel,url) in enumerate(zip(result['layout']['panels'],result['images'])):
                        path=out/'mask-editor'/plan['kind']/plan['view']/f'{i}.png';path.parent.mkdir(parents=True,exist_ok=True)
                        path.write_bytes(base64.b64decode(url.split(',',1)[1]))
                        record={k:v for k,v in panel.items() if k not in ('source','head_points','crop')}
                        p=photos[panel['asset_id']];record.update(file=str(path),phase=p['phase'],view=p['view'])
                        records.append(record)
                    groups.append(dict(scope=result['layout']['scope'],panels=records));continue
                path=out/plan['name'];path.write_bytes(base64.b64decode(result['image'].split(',',1)[1]))
                layout=result['layout']
                if layout:
                    for panel in layout['panels']:
                        for key in ('source','head_points','crop'):panel.pop(key,None)
                product(path,plan['kind'],plan['name'],asset_ids=plan['asset_ids'],view=plan['view'],privacy_layout=layout,layout_hash=result['layout_hash'])
                if result['cover_sources']:cover_sources=result['cover_sources']
        finally:
            browser.close()
    if editor:
        from .mask_editor import capture_sticker
        save(out/'editor.json',dict(groups=groups,sticker_file=capture_sticker(m,out)))
    for e in m['_engine']['extras'] if section is None and not editor else []:
        path=out/e['name'];masking=(e['kind']=='training' and prefs.get('mask_training')) or (e['kind']=='life' and prefs.get('mask_lifestyle'))
        source=privacy.masked_source(m,e['path']) if masking else e['path']
        if e['kind']=='life' and source==e['path']:shutil.copy2(source,path)
        else:
            with Image.open(source) as raw:
                image=ImageOps.exif_transpose(raw).convert('RGB')
                if e['kind']=='testimonial':image=testimonial_text(image,e,m,prefs)
                if e['kind']!='life':image=presentation.fit(image,prefs)
                image.save(path,**({'quality':94} if path.suffix.lower() in ('.jpg','.jpeg') else {}))
        product(path,e['kind'],e['name'])
    save(out/'result.json',dict(member_id=mid,profile=m['profile'],store=m['store'],products=products,
        gaps=gaps+m['gaps'],cover_sources=cover_sources,review_required=[p['asset_id'] for p in m['photos'] if not p['confirmed']],
        model_calls=0,privacy=m['privacy'],mask_edits=m.get('mask_edits',{}),render_settings=prefs,fonts=m['fonts'],renderer='instant-canvas-v1'))

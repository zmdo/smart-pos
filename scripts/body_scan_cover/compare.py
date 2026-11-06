"""Offline old/new cover gallery; operates on existing renders only."""
import argparse
import html
import shutil
from pathlib import Path
from scripts.body_scan_contracts.io import read, sha


def run(previous, current, frames):
    previous, current, frames = map(Path, (previous, current, frames))
    old = {c['group_id']: c for c in read(previous/'cases.json')['cases']}
    data = read(current/'cases.json'); bundle = {c['group_id']: c for c in read(frames/'frames.json')['cases']}
    dest = current/'previous'
    if dest.exists() or (current/'comparison.html').exists():
        raise FileExistsError(dest)
    dest.mkdir(); (current/'pairs').mkdir(); sections = []; links = []
    for c in data['cases']:
        gid = c['group_id']; before = old[gid]; pair = bundle[gid]
        if before['asset_ids'] != c['asset_ids'] or before['labels'] != c['labels']:
            raise ValueError('comparison_requires_same_assets_and_labels')
        path = previous/before['file']
        if sha(path) != before['sha256'] or sha(current/c['file']) != c['sha256'] or sha(frames/pair['pair_file']) != pair['pair_sha256']:
            raise ValueError('comparison_image_changed')
        shutil.copy2(path, dest/(gid+'.jpg')); shutil.copy2(frames/pair['pair_file'], current/'pairs'/(gid+'.png'))
        title = html.escape(c['store']+' / '+c['member']); links.append(f'<a href="#{gid}">{title}</a>')
        old_w = before['framing'][0]['crop_xyxy'][2]-before['framing'][0]['crop_xyxy'][0]
        # Old width is in display pixels and may differ in normalized units.
        new_w = c['framing'][0]['shared_pair_size'][0]
        notes = ''.join('<p>'+html.escape(n)+'</p>' for n in c['notes'])
        sections.append(f'<section id="{gid}"><h2>{title}</h2><div class="pair">'
            f'<figure><figcaption>旧版 · 六图成品再次取景</figcaption><img loading="lazy" src="previous/{gid}.jpg"></figure>'
            f'<figure><figcaption>新版 · 原图双图独立取景</figcaption><a href="index.html#{gid}"><img loading="lazy" src="{html.escape(c["file"])}"></a></figure>'
            f'</div><details><summary>查看封面专用双图与说明</summary><img class="raw" loading="lazy" src="pairs/{gid}.png">{notes}'
            f'<p>新框宽度 {new_w:.1f}（肩部标准坐标）；旧框宽度 {old_w:.1f}（旧成品像素）。坐标单位可能不同，不直接作为比例。</p>'
            f'<a href="pairs/{gid}.png" download>下载封面专用正面对比图</a></details></section>')
    page = '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">'
    page += '<title>封面双图取景 · 新旧对比</title><style>body{margin:0;background:#f4f1eb;color:#302d29;font:16px system-ui}header,main{max-width:1220px;margin:auto;padding:28px}h1{margin:0 0 12px}nav{display:flex;flex-wrap:wrap;gap:8px}a{color:#a60017}nav a{padding:8px 12px;background:white;border-radius:8px;text-decoration:none}section{padding:24px 0;border-top:1px solid #ddd}figure{margin:0}figcaption{padding:12px;font-weight:bold}.pair{display:grid;grid-template-columns:1fr 1fr;gap:16px}img{width:100%;height:auto;display:block}details{padding:16px;background:white;border-radius:8px}summary{cursor:pointer}.raw{max-width:1000px;margin:20px auto}p{line-height:1.6}@media(max-width:600px){header,main{padding:14px}.pair{gap:5px}figcaption{font-size:12px;padding:8px 0}}</style>'
    page += '<header><h1>封面双图取景 · 新旧对比</h1><p>左侧旧版，右侧新版。相同素材、阶段标签与文案；新版从原图复用校正，仅两张正面照共同取景，不做非等比拉伸。</p><p><a href="index.html">进入封面预览与文案编辑 →</a></p><nav>'+''.join(links)+'</nav></header><main>'+''.join(sections)+'</main></html>'
    (current/'comparison.html').write_text(page)
    page = (current/'index.html').read_text().replace('<a href="cases.json" download>', '<a href="comparison.html">新旧取景对比 ↗</a><a href="cases.json" download>')
    (current/'index.html').write_text(page)
    return len(sections)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--previous', type=Path, required=True); p.add_argument('--current', type=Path, required=True)
    p.add_argument('--frames', type=Path, required=True); a = p.parse_args()
    print({'compared': run(a.previous, a.current, a.frames)})

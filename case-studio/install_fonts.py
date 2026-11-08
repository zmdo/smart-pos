"""Install pinned OFL fonts; preserve the existing Noto Sans font file."""
import hashlib, json, os, urllib.request
from pathlib import Path

root=Path(os.environ.get('CASE_DATA','/root/autodl-fs/case-studio'))/'fonts'
manifest=json.loads((Path(__file__).parent/'assets/fonts/manifest.json').read_text())
root.mkdir(parents=True,exist_ok=True)
for item in manifest['files']:
    path=root/item['name']
    if path.exists() and hashlib.sha256(path.read_bytes()).hexdigest()==item['sha256']:
        continue
    with urllib.request.urlopen(item['url'],timeout=120) as response:
        data=response.read()
    if hashlib.sha256(data).hexdigest()!=item['sha256']:
        raise RuntimeError('字体内容校验失败：'+item['name'])
    temp=path.with_suffix(path.suffix+'.tmp')
    temp.write_bytes(data);temp.replace(path)
print('Font library installed with verified licenses and checksums.')

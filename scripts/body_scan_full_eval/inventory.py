"""Hash every business file; inventories do not decode or upload images."""
import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path


def inventory(directory):
    directory=Path(directory).resolve();rows=[]
    for path in sorted(directory.rglob('*')):
        if not path.is_file() or path.name in ('.DS_Store','Thumbs.db'):
            continue
        h=hashlib.sha256()
        with path.open('rb') as stream:
            for chunk in iter(lambda:stream.read(1024*1024),b''):h.update(chunk)
        rows.append({'path':str(path.relative_to(directory)),'sha256':h.hexdigest(),
                     'bytes':path.stat().st_size,'extension':path.suffix.lower()})
    return {'root':str(directory),'files':rows,'counts':dict(Counter(r['extension'] for r in rows))}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--input',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True);parser.add_argument('--match',type=Path)
    args=parser.parse_args();value=inventory(args.input)
    if args.match:
        other=json.loads(args.match.read_text())
        value['matches_other_inventory']=Counter(r['sha256'] for r in value['files'])==Counter(r['sha256'] for r in other['files'])
        if not value['matches_other_inventory']:raise ValueError('inventory_content_mismatch')
    args.out.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print({'files':len(value['files']),'counts':value['counts'],'matches':value.get('matches_other_inventory')})

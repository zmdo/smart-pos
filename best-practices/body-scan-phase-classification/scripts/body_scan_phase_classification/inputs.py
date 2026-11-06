"""Read approved visual analysis, retaining photo identity and file hashes."""
import re
from pathlib import Path
from scripts.body_scan_contracts.io import read, bind

def load_phase(directory):
    root=Path(directory).resolve();manifest={}
    rows=read(bind(root/'summary.json',manifest));groups=read(bind(root/'groups.json',manifest))
    if read(bind(root/'config.json',manifest)).get('version')!='body-scan-phase-regions-v1':raise ValueError('unsupported_phase_input')
    metadata={};photos={};seen=set()
    for row in rows:
        aid=row['asset_id']
        if not re.fullmatch(r'[A-Za-z0-9_-]+',aid) or aid in seen or not row['store'].endswith('店'):raise ValueError('invalid_phase_asset')
        if (row['view'] not in ('front','back','side','side_left','side_right')
                or not re.fullmatch(r'[A-Za-z0-9_-]+',row['group_id'])):raise ValueError('invalid_view_or_group_id')
        seen.add(aid);directory=Path(row['display_input']).resolve()
        if str(directory) not in metadata:
            metadata[str(directory)]={r['asset_id']:r for r in read(bind(directory/'summary.json',manifest))}
        source=metadata[str(directory)][aid]
        if any(source[k]!=row[k] for k in ('store','member','source_sha256')):raise ValueError('display_identity_mismatch')
        bind(row['source'],manifest,row['source_sha256']);bind(row['uniform'],manifest,row['uniform_sha256'])
        photos[aid]=str(bind(directory/'images'/aid/'display.png',manifest,source['output']['display_sha256']))
    grouped_ids=[aid for g in groups for aid in g['asset_ids']]
    if len(grouped_ids)!=len(rows) or set(grouped_ids)!=seen:raise ValueError('phase_group_partition_invalid')
    for group in groups:
        for row in rows:
            if row['asset_id'] in group['asset_ids'] and (row['store'],row['member'],row['group_id'])!=(group['store'],group['member'],group['group_id']):
                raise ValueError('phase_group_identity_mismatch')
    return rows,groups,photos,manifest


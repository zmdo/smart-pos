"""Extract store reports without requiring photos, phase groups or a renderer."""
import re
from pathlib import Path

from scripts.body_scan_contracts.io import bind, read, save, sha
from scripts.body_scan_contracts.bundles import seal, load_reports
from . import VERSION
from .extraction import read_document, validate_report, REPORT_PROMPT, REPORT_VERSION, norm
from .html import export


def run(root, out, client, reuse=None):
    root = Path(root).resolve(); out = Path(out).resolve()
    out.mkdir(parents=True, exist_ok=False)
    records = []; inventory = []; bindings = {}; previous = {}; reserved = set()
    if reuse:
        reuse = Path(reuse).resolve()
        for row in read(bind(reuse/'reports.json',bindings)):
            rid = row['report_id']
            if not re.fullmatch(r'r\d+',rid) or rid in reserved:
                raise ValueError('invalid_reuse_report_ids')
            reserved.add(rid); previous[row['source_sha256']] = row
    for path in sorted(root.rglob('*')):
        if not path.is_file() or path.suffix.lower() not in ('.pdf','.docx') or path.name.startswith('~$'):
            continue
        relative = path.relative_to(root); parts = relative.parts
        entry = {'relative_path':str(relative), 'status':'excluded'}; inventory.append(entry)
        if len(parts) < 3 or not parts[0].endswith('店'):
            entry['reason'] = 'not_store_material'; continue
        path = bind(path,bindings); fingerprint = bindings[str(path)]
        old = previous.get(fingerprint)
        n = 1
        while f'r{n:03d}' in reserved: n += 1
        rid = old['report_id'] if old else f'r{n:03d}'
        if any(r['report_id'] == rid for r in records):
            rid = f'r{n:03d}'
        reserved.add(rid); dest = out/rid; dest.mkdir()
        record = {'report_id':rid, 'source':str(relative), 'source_sha256':fingerprint,
                  'store':parts[0], 'member':None, 'status':'needs_review'}
        audit = {}
        try:
            content, images, pages, tables = read_document(path,dest)
            if old:
                audit = read(bind(reuse/old['report_id']/'audit.json',bindings))
                raw = audit['result']
                audit = {'result':raw, 'reused_transcription':True, 'request_count':0,
                         'source_sha256':fingerprint}
            else:
                if client is None: raise ValueError('transcription_provider_required')
                raw, trace = client.ask(images,REPORT_PROMPT+content,REPORT_VERSION)
                audit = {**trace, 'result':raw}
            member = raw.get('member') if isinstance(raw,dict) else None
            if not isinstance(member,str) or not norm(member) or norm(member).casefold() not in norm('/'.join(parts[1:-1])).casefold():
                raise ValueError('report_member_not_verified_in_member_folder')
            record['member'] = member
            record.update(validate_report(raw,parts[0],member,pages,tables))
            stated = raw.get('stated_days')
            record['stated_days'] = stated if type(stated) is int and re.search(rf'(?<!\d){stated}\s*天',content) else None
        except (ValueError,OSError,ImportError,KeyError) as error:
            audit.update(getattr(error,'trace',{})); record['reason'] = str(error)
        records.append(record)
        entry.update(report_id=rid,store=record['store'],member=record['member'],
                     status=record['status'],reason=record.get('reason'))
        save(dest/'audit.json',audit); save(dest/'report.json',record)
        print('report',record['member'],record['status'],flush=True)
    records.sort(key=lambda r:r['report_id'])
    save(out/'reports.json',records); save(out/'inventory.json',inventory)
    save(out/'sources.json',bindings)
    save(out/'config.json',{'version':VERSION,'source_root':str(root), 'photo_input_required':False,
         'phase_order_policy':'explicit_report_column_headers_only', 'reused':str(reuse) if reuse else None})
    result = export(out,out/'index.html')
    if any(sha(p) != digest for p,digest in bindings.items()):
        raise ValueError('report_source_changed_during_extraction')
    seal(out,VERSION,('reports.json','inventory.json','index.html'))
    load_reports(out)
    save(out/'counts.json',{**result,'store_documents':len(records),
         'excluded_documents':sum(e['status']=='excluded' for e in inventory),
         'needs_review':sum(r['status']=='needs_review' for r in records)})
    return read(out/'counts.json')

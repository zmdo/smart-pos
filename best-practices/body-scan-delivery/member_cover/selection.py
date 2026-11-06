"""Resolve the existing front pair without reclassifying training stage."""
from pathlib import Path
from PIL import Image
from scripts.body_scan_contracts.io import bind, sha, read
from scripts.body_scan_delivery.render import priority
from .framing import coverage_rank


def metadata_for(row, path, bindings, cache):
    summary = Path(path).parents[2]/'summary.json'
    if summary not in cache:
        cache[summary] = {r['asset_id']: r for r in read(bind(summary, bindings))}
    meta = cache[summary][row['asset_id']]
    if any(meta[k] != row[k] for k in ('store', 'member', 'source_sha256')):
        raise ValueError('cover_display_identity_mismatch')
    if meta.get('status') != 'displayed' or meta['output']['display_sha256'] != sha(path):
        raise ValueError('cover_pose_does_not_match_photo')
    with Image.open(path) as im:
        if list(im.size) != meta['group_plan']['output_size']:
            raise ValueError('cover_pose_canvas_mismatch')
    return meta


def choose_pair(rows, source, original_pair, bindings, cache):
    fronts = [r for r in rows if r['view'] == 'front']
    meta = {r['asset_id']: metadata_for(r, source['photos'][r['asset_id']], bindings, cache) for r in fronts}
    before = [r for r in fronts if r['phase'] == 'before']; after = [r for r in fronts if r['phase'] == 'after']
    options = [(a, b) for a in before for b in after if a['source_sha256'] != b['source_sha256']]
    if not options:
        raise ValueError('缺少两张不同原图的正面训练前后照')
    def score(pair):
        ranks = [coverage_rank(meta[r['asset_id']]) for r in pair]
        return (sum(r[0] for r in ranks), min(r[1] for r in ranks), sum(r[1] for r in ranks),
                sum(r[2] for r in ranks), [r['asset_id'] for r in pair] == original_pair,
                priority(pair[0]), priority(pair[1]))
    return max(options, key=score), meta

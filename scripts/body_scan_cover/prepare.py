"""Create a data contract for the upstream cover-pair best-practice branch."""
import copy
from collections import defaultdict
from pathlib import Path
from scripts.body_scan_contracts.io import read, save, sha
from scripts.body_scan_delivery.pipeline import current, digest_json
from .selection import choose_pair


def prepare(delivery, output):
    delivery = Path(delivery).resolve(); output = Path(output).resolve()
    if output.exists():
        raise FileExistsError(output)
    original, revision = current(delivery)
    source = read(delivery/'private-inputs.json'); bindings = copy.deepcopy(source['bindings'])
    if digest_json(bindings) != original['source_manifest_sha256'] or any(sha(p) != h for p, h in bindings.items()):
        raise ValueError('cover_source_manifest_changed')
    grouped = defaultdict(list)
    for row in original['items']:
        grouped[(row['group_id'], row['store'], row['member'])].append(row)
    original_pairs = {p['group_id']: p['asset_ids'] for p in original['outputs'] if p['kind'] == 'vs' and p['view'] == 'front'}
    pairs = []; gaps = []; cache = {}
    for (gid, store, member), rows in sorted(grouped.items()):
        identity = {'group_id': gid, 'store': store, 'member': member}
        try:
            pair, _ = choose_pair(rows, source, original_pairs.get(gid), bindings, cache)
            assets = []
            for row in pair:
                summary = Path(source['photos'][row['asset_id']]).parents[2]/'summary.json'
                assets.append({'stage': copy.deepcopy(row), 'display_summary': {'path': str(summary), 'sha256': sha(summary)}})
            pairs.append({**identity, 'assets': assets})
        except (ValueError, KeyError, OSError) as error:
            gaps.append({**identity, 'reason': str(error)})
    result = {'version': 'cover-frame-request-v1', 'pairs': pairs, 'gaps': gaps,
              'phase_result': {'path': str(revision/'result.json'), 'sha256': sha(revision/'result.json')},
              'review_target': {'delivery_id': original['delivery_id'], 'base_revision': original['revision'],
                                'source_manifest_sha256': original['source_manifest_sha256'], 'submit_url': original['review']['submit_url']}}
    output.parent.mkdir(parents=True, exist_ok=True); save(output, result)
    return result


if __name__ == '__main__':
    import argparse
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--delivery', type=Path, required=True); p.add_argument('--out', type=Path, required=True)
    a = p.parse_args(); r = prepare(a.delivery, a.out)
    print({'pairs': len(r['pairs']), 'gaps': len(r['gaps'])})

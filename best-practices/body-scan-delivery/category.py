"""Render one product family from a verified, existing delivery revision."""
import argparse
import copy
import shutil
import tempfile
from pathlib import Path

from scripts.body_scan_contracts.bundles import load_reports
from scripts.body_scan_delivery.pipeline import current, read, save, digest_json
from scripts.body_scan_delivery.render import render, sha


def generate(kind, delivery, out):
    if kind not in ('three_views', 'vs', 'single'):
        raise ValueError('unsupported_product_kind')
    delivery, out = Path(delivery).resolve(), Path(out).resolve()
    if out.exists():
        raise FileExistsError(out)
    result, revision = current(delivery)
    source = read(delivery/'private-inputs.json')
    bindings = source['bindings']
    if digest_json(bindings) != result['source_manifest_sha256']:
        raise ValueError('source_manifest_changed')

    def verify_sources():
        if any(sha(p) != h for p, h in bindings.items()):
            raise ValueError('bound_source_changed')

    verify_sources()
    result_hash = sha(revision/'result.json')
    # Use the exact selected pairs from the approved revision; do not reclassify or reselect.
    fields = ('product_id', 'group_id', 'store', 'member', 'kind', 'view', 'asset_ids')
    plans = [{k:p[k] for k in fields} for p in result['outputs'] if p['kind'] == kind]
    selected = {aid for p in plans for aid in p['asset_ids']}
    rows = [copy.deepcopy(r) for r in result['items'] if r['asset_id'] in selected]
    reports = load_reports(source['report_bundle']) if source.get('report_bundle') else []
    out.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix='.category-', dir=out.parent))
    try:
        outputs = render(plans, rows, source['photos'], staging, source['font'],
                         presentation=source.get('presentation'), reports=reports)
        for row in rows:
            row.pop('thumbnail', None)
            row['affected_output_ids'] = [p['product_id'] for p in outputs if row['asset_id'] in p['asset_ids']]
        gaps = [g for g in result['gaps'] if
                kind == 'vs' and g['product'].startswith('vs-') or
                kind == 'three_views' and g['product'] == 'three_views']
        review_target = {'delivery_id':result['delivery_id'], 'base_revision':result['revision'],
                         'source_manifest_sha256':result['source_manifest_sha256'],
                         'submit_url':result['review']['submit_url']}
        data = {'schema_version':'body-photo-category-v1', 'kind':kind,
                'source_result_sha256':result_hash, 'review_target':review_target,
                'items':rows, 'outputs':outputs, 'gaps':gaps,
                'counts':{'images':len(rows), 'products':len(outputs),
                          'review_images':sum(r['requires_review'] for r in rows),
                          'review_products':sum(p['requires_review'] for p in outputs)},
                'model_requests':0}
        save(staging/'result.json', data)
        save(staging/'review.json', {'target':review_target,
            'items':[r for r in rows if r['requires_review']],
            'outputs_requiring_review':[p for p in outputs if p['requires_review']]})
        verify_sources()
        if sha(revision/'result.json') != result_hash:
            raise ValueError('source_revision_changed')
        staging.rename(out)
        return data
    except Exception:
        shutil.rmtree(staging)
        raise


def main():
    p = argparse.ArgumentParser(description='只生成指定成品；使用既有版本的照片、配对和配置')
    p.add_argument('kind', choices=('three_views', 'vs', 'single'))
    p.add_argument('--delivery', type=Path, required=True, help='含 current.json 和 private-inputs.json 的完整成品根目录')
    p.add_argument('--out', type=Path, required=True, help='全新类别输出目录')
    args = p.parse_args()
    result = generate(args.kind, args.delivery, args.out)
    print({'kind':args.kind, **result['counts']})


if __name__ == '__main__':
    main()

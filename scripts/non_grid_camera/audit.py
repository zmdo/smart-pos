"""Reclassify an experiment subset without changing original jobs or shared caches."""
import argparse
import hashlib
import importlib.util
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PIL import Image


def audit(job_path, asset_ids, out, case_code, cache):
    sys.path.insert(0, str(case_code))
    spec = importlib.util.spec_from_file_location('wall_classifier', case_code/'classify.py')
    classifier = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(classifier)
    from settings import load
    cfg = load()
    job = json.loads(job_path.read_text(encoding='utf-8'))
    requested = set(asset_ids)
    assets = [a for a in job['assets'] if a['id'] in requested]
    if requested != {a['id'] for a in assets}:
        raise ValueError('unknown_asset_ids')
    out.mkdir(parents=True, exist_ok=False)
    cache.mkdir(parents=True, exist_ok=True)
    provider = hashlib.sha256((cfg['base_url']+'\0'+cfg['model']).encode()).hexdigest()

    def work(asset):
        source = (job_path.parent/'input'/asset['path']).resolve()
        if not source.is_relative_to((job_path.parent/'input').resolve()):
            raise ValueError('source_outside_input')
        sha = hashlib.sha256(source.read_bytes()).hexdigest()
        key = hashlib.sha256((sha+classifier.PROMPT_VERSION+provider).encode()).hexdigest()
        path = cache/(key+'.json')
        record = {'asset_id': asset['id'], 'source': str(source), 'source_sha256': sha,
                  'store': asset.get('store'), 'member': asset.get('member'),
                  'previous': asset.get('class'), 'prompt_version': classifier.PROMPT_VERSION}
        try:
            if path.exists():
                result = json.loads(path.read_text(encoding='utf-8'))
                hit = True
            else:
                with Image.open(source) as image:
                    # Match cv2 / upstream orientation semantics.
                    from PIL import ImageOps
                    encoded = classifier._encode(ImageOps.exif_transpose(image).convert('RGB'))
                result = classifier.normalize(classifier.call_vlm(encoded, cfg))
                path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
                hit = False
            record.update({'classification': result, 'cached': hit,
                           'status': 'body_scan' if result['kind'] == 'body_scan' else 'excluded'})
        except Exception as error:
            record.update({'status': 'needs_review', 'reason': type(error).__name__})
        print(asset['id'], record['status'], record.get('classification', {}).get('kind'), flush=True)
        return record

    with ThreadPoolExecutor(max_workers=3) as pool:
        records = list(pool.map(work, assets))
    (out/'classification.json').write_text(json.dumps(records, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    return records


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--job', type=Path, required=True)
    parser.add_argument('--asset-id', nargs='+', required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--case-code', type=Path, default=Path('/root/apps/case-studio'))
    parser.add_argument('--cache', type=Path, default=Path('/root/autodl-fs/case-studio/cache/non-grid-wall-classification'))
    args = parser.parse_args()
    audit(args.job, args.asset_id, args.out, args.case_code, args.cache)

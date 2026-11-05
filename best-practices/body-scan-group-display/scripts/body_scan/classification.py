"""Apply a wall-classification audit to historical jobs, with source binding."""
import hashlib
import json
from pathlib import Path


def apply_audit(assets, input_dir, audit_path):
    path = Path(audit_path)
    entries = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(entries, list):
        raise ValueError('invalid_classification_audit')
    ids = [entry['asset_id'] for entry in entries]
    if len(ids) != len(set(ids)):
        raise ValueError('duplicate_classification_audit_ids')
    indexed = dict(zip(ids, entries))
    result = []
    for asset in assets:
        row = dict(asset)
        if asset['id'] in indexed:
            entry = indexed[asset['id']]
            classification = entry.get('classification')
            if (entry.get('prompt_version') != 'cls-v3-wall' or not isinstance(classification, dict)
                    or classification.get('classification_rule') != 'cls-v3-wall'):
                raise ValueError('unverified_wall_classification: ' + asset['id'])
            source = (input_dir/asset['path']).resolve()
            if not source.is_relative_to(input_dir.resolve()):
                raise ValueError('source_outside_input_directory')
            digest = hashlib.sha256(source.read_bytes()).hexdigest()
            if digest != entry.get('source_sha256'):
                raise ValueError('classification_audit_source_mismatch: ' + asset['id'])
            row['class'] = classification
            row['classification_evidence'] = {'source': 'verified_wall_audit', 'source_sha256': digest,
                                              'prompt_version': entry['prompt_version']}
        result.append(row)
    return result, {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                    'applied_count': sum('classification_evidence' in a for a in result)}

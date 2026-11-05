"""Integrity check for the approved, self-contained group display snapshot."""
import hashlib
import json
from pathlib import Path


def verify_integrity(root=None):
    root = Path(root or Path(__file__).parent).resolve()
    manifest = json.loads((root/'manifest.json').read_text(encoding='utf-8'))
    paths = [item['path'] for item in manifest['files']]
    if len(paths) != len(set(paths)):
        raise ValueError('duplicate_snapshot_file')
    for item in manifest['files']:
        path = (root/item['path']).resolve()
        if (not path.is_relative_to(root) or not path.is_file()
                or hashlib.sha256(path.read_bytes()).hexdigest() != item['sha256']):
            raise ValueError('snapshot_file_mismatch: '+item['path'])
    actual = {p.relative_to(root).as_posix() for p in (root/'scripts').rglob('*.py')}
    declared = {p for p in paths if p.startswith('scripts/') and p.endswith('.py')}
    if actual != declared:
        raise ValueError('unexpected_or_missing_snapshot_module')
    return {'source_commit': manifest['source_commit'], 'version': manifest['version'],
            'verified_files': len(paths), 'snapshot_root': str(root)}

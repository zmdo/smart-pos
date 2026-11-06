"""Check the complete frozen package before importing its processing code."""
import hashlib
import json
from pathlib import Path


def verify_integrity(root=None):
    root = Path(root or Path(__file__).parent).resolve()
    manifest = json.loads((root/'manifest.json').read_text(encoding='utf-8'))
    paths = [row['path'] for row in manifest['files']]
    if len(paths) != len(set(paths)):
        raise ValueError('duplicate_snapshot_file')
    for row in manifest['files']:
        path = (root/row['path']).resolve()
        if not path.is_relative_to(root) or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != row['sha256']:
            raise ValueError('snapshot_file_mismatch: '+row['path'])
    actual = {p.relative_to(root).as_posix() for p in root.rglob('*.py')}
    expected = {p for p in paths if p.endswith('.py')}
    if actual != expected:
        raise ValueError('unexpected_or_missing_snapshot_module')
    return {'version':manifest['version'], 'source_commit':manifest['source_commit'], 'verified_files':len(paths)}

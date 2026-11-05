"""Validate this frozen copy and its explicitly pinned single-photo dependency."""
import hashlib
import json
from pathlib import Path


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check_files(root, manifest):
    for item in manifest['files']:
        path = (root/item['path']).resolve()
        if not path.is_relative_to(root) or digest(path) != item['sha256']:
            raise ValueError('snapshot_file_mismatch: '+item['path'])


def verify_integrity(root=None):
    root = Path(root or Path(__file__).parent).resolve()
    manifest = json.loads((root/'manifest.json').read_text(encoding='utf-8'))
    check_files(root, manifest)
    dependency = manifest['dependency']
    other = (root/dependency['path']).resolve()
    if not other.is_relative_to(root.parent) or other == root:
        raise ValueError('invalid_snapshot_dependency_location')
    other_manifest = other/'manifest.json'
    if digest(other_manifest) != dependency['manifest_sha256']:
        raise ValueError('single_photo_snapshot_manifest_changed')
    frozen = json.loads(other_manifest.read_text(encoding='utf-8'))
    if frozen['source_commit'] != dependency['source_commit']:
        raise ValueError('single_photo_snapshot_version_changed')
    check_files(other, frozen)
    return {'source_commit': manifest['source_commit'], 'snapshot_root': str(root),
            'verified_files': len(manifest['files']), 'dependency_root': str(other),
            'dependency_source_commit': frozen['source_commit'],
            'dependency_manifest_sha256': dependency['manifest_sha256'],
            'verified_dependency_files': len(frozen['files'])}

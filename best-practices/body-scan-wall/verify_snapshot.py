"""Verify the frozen manifest and ensure project imports stay inside this copy."""
import hashlib
import importlib
import json
import sys
from pathlib import Path


def verify():
    root = Path(__file__).resolve().parent
    manifest = json.loads((root / 'manifest.json').read_text(encoding='utf-8'))
    sys.path.insert(0, str(root))
    modules = []
    for item in manifest['files']:
        path = root / item['path']
        if not path.resolve().is_relative_to(root):
            raise ValueError('manifest_path_outside_snapshot')
        if hashlib.sha256(path.read_bytes()).hexdigest() != item['sha256']:
            raise ValueError('snapshot_hash_mismatch: ' + item['path'])
        if path.suffix == '.py' and item['path'].startswith('scripts/'):
            parts = Path(item['path']).with_suffix('').parts
            name = '.'.join(parts[:-1] if parts[-1] == '__init__' else parts)
            module = importlib.import_module(name)
            if not Path(module.__file__).resolve().is_relative_to(root):
                raise ValueError('import_outside_snapshot: ' + name)
            modules.append(name)
    for name, module in list(sys.modules.items()):
        if name == 'scripts' or name.startswith('scripts.'):
            if not Path(module.__file__).resolve().is_relative_to(root):
                raise ValueError('dependency_outside_snapshot: ' + name)
    return {'source_commit': manifest['source_commit'], 'verified_files': len(manifest['files']),
            'verified_project_imports': len(modules), 'snapshot_root': str(root)}


if __name__ == '__main__':
    print(json.dumps(verify(), ensure_ascii=False, indent=2))

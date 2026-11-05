"""Verify file hashes and the origins of all imported project modules."""
import importlib
import json
import sys
from pathlib import Path

from snapshot import verify_integrity


def verify():
    result = verify_integrity()
    root = Path(result['snapshot_root'])
    other = Path(result['dependency_root'])
    sys.path.insert(0, str(root))
    manifest = json.loads((root/'manifest.json').read_text(encoding='utf-8'))
    for item in manifest['files']:
        path = Path(item['path'])
        if path.suffix == '.py' and path.parts[0] == 'scripts':
            parts = path.with_suffix('').parts
            name = '.'.join(parts[:-1] if parts[-1] == '__init__' else parts)
            importlib.import_module(name)
    origins = {}
    for name, module in list(sys.modules.items()):
        if name == 'scripts' or name.startswith('scripts.'):
            path = Path(module.__file__).resolve()
            if not any(path.is_relative_to(base) for base in (root, other)):
                raise ValueError('development_import_in_snapshot: '+name)
            origins[name] = str(path)
    return {**result, 'verified_project_imports': len(origins), 'module_origins': origins}


if __name__ == '__main__':
    print(json.dumps(verify(), ensure_ascii=False, indent=2))

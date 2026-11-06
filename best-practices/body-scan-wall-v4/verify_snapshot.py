"""Verify hashes and import isolation without using the development checkout."""
import importlib
import json
import sys
from pathlib import Path

from snapshot import verify_integrity


def verify():
    root = Path(__file__).resolve().parent
    result = verify_integrity(root)
    manifest = json.loads((root/'manifest.json').read_text(encoding='utf-8'))
    sys.path.insert(0, str(root))
    imported = []
    for item in manifest['files']:
        path = Path(item['path'])
        if path.suffix != '.py' or path.parts[0] != 'scripts':
            continue
        parts = path.with_suffix('').parts
        name = '.'.join(parts[:-1] if parts[-1] == '__init__' else parts)
        module = importlib.import_module(name)
        if not Path(module.__file__).resolve().is_relative_to(root):
            raise ValueError('import_outside_snapshot: '+name)
        imported.append(name)
    for name, module in list(sys.modules.items()):
        if name == 'scripts' or name.startswith('scripts.'):
            locations = [module.__file__] if getattr(module, '__file__', None) else list(module.__path__)
            if not locations or any(not Path(p).resolve().is_relative_to(root) for p in locations):
                raise ValueError('dependency_outside_snapshot: '+name)
    return {**result, 'verified_project_imports': len(imported)}


if __name__ == '__main__':
    print(json.dumps(verify(), ensure_ascii=False, indent=2))

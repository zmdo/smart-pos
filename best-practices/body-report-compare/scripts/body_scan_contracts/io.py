"""Small atomic JSON and immutable file bindings; no processing dependencies."""
import hashlib
import json
import uuid
from pathlib import Path


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')
    temporary.replace(path)


def bind(path, manifest, expected=None):
    path = Path(path).resolve(); actual = sha(path)
    if expected is not None and actual != expected:
        raise ValueError('source_hash_changed')
    if str(path) in manifest and manifest[str(path)] != actual:
        raise ValueError('source_changed_during_load')
    manifest[str(path)] = actual
    return path

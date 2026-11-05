"""Expose only the pair snapshot and its verified, frozen single-photo dependency."""
import importlib.util
from pathlib import Path

_root = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location('_pair_snapshot_integrity', _root/'snapshot.py')
_integrity = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_integrity)
_verified = _integrity.verify_integrity(_root)
# No namespace fallback to the repository's mutable scripts directory.
__path__.append(str(Path(_verified['dependency_root'])/'scripts'))

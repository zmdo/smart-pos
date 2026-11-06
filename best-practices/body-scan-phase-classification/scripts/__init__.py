"""Use only this verified snapshot; never fall back to development modules."""
import importlib.util
from pathlib import Path

_root = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location('_group_display_snapshot', _root/'snapshot.py')
_integrity = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_integrity)
_verified = _integrity.verify_integrity(_root)

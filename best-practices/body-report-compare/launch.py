"""Isolated entry point for the frozen node."""
import os
import runpy
import sys
from pathlib import Path
from snapshot import verify_integrity
root=Path(__file__).resolve().parent
verify_integrity(root)
deps=Path(os.environ.get('CASE_REPORT_DEPS','/root/apps/phase-evidence-deps'))
if deps.is_dir():sys.path.insert(1,str(deps))
runpy.run_module('scripts.body_report_compare',run_name='__main__')

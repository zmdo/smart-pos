"""Isolated entry point for the frozen node."""
import os
import runpy
import sys
from pathlib import Path
from snapshot import verify_integrity
root=Path(__file__).resolve().parent
verify_integrity(root)
runpy.run_module('scripts.body_scan_phase_classification',run_name='__main__')

"""Isolated CLI shared by the suite and its three product directories."""
import os
import runpy
import sys
import unittest
from pathlib import Path
from snapshot import verify_integrity

root = Path(__file__).resolve().parent
os.environ.pop('PYTHONPATH', None)
os.chdir(root)
verify_integrity(root)
command = sys.argv[1] if len(sys.argv) > 1 else '--help'
if command == 'check':
    print(verify_integrity(root))
elif command == 'test':
    suite = unittest.TestSuite()
    for folder in ('scripts/body_scan_contracts/tests', 'scripts/body_scan_delivery/tests', 'tests'):
        suite.addTests(unittest.TestLoader().discover(folder))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    raise SystemExit(not result.wasSuccessful())
elif command in ('restyle', 'verify', 'category'):
    del sys.argv[1]
    module = 'category' if command == 'category' else 'scripts.body_scan_delivery.'+command
    runpy.run_module(module, run_name='__main__')
else:
    runpy.run_module('scripts.body_scan_delivery', run_name='__main__')

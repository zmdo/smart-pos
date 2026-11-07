"""Isolated CLI shared by all eight product directories."""
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
    for folder in ('scripts/body_scan_contracts/tests', 'scripts/body_scan_delivery/tests', 'member_cover/tests', 'report_comparison/tests', 'testimonial_album/tests', 'training_daily/tests', 'life_photos/tests', 'tests'):
        suite.addTests(unittest.TestLoader().discover(folder))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    raise SystemExit(not result.wasSuccessful())
elif command in ('training-daily','training-evidence','life-photos'):
    del sys.argv[1]
    module={'training-daily':'training_daily','training-evidence':'training_daily.analysis','life-photos':'life_photos'}[command]
    runpy.run_module(module,run_name='__main__')
elif command in ('testimonial', 'testimonial-evidence', 'testimonial-annotate'):
    del sys.argv[1]
    module = {'testimonial':'testimonial_album', 'testimonial-evidence':'testimonial_album.evidence',
              'testimonial-annotate':'testimonial_album.annotate'}[command]
    runpy.run_module(module, run_name='__main__')
elif command == 'report-comparison':
    del sys.argv[1]
    runpy.run_module('report_comparison', run_name='__main__')
elif command in ('cover', 'cover-prepare', 'cover-compare'):
    del sys.argv[1]
    module = {'cover':'member_cover', 'cover-prepare':'member_cover.prepare',
              'cover-compare':'member_cover.compare'}[command]
    runpy.run_module(module, run_name='__main__')
elif command in ('restyle', 'verify', 'category'):
    del sys.argv[1]
    module = 'category' if command == 'category' else 'scripts.body_scan_delivery.'+command
    runpy.run_module(module, run_name='__main__')
else:
    runpy.run_module('scripts.body_scan_delivery', run_name='__main__')

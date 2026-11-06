"""Optional cover-pair branch; the existing group workflow is unchanged."""
from snapshot import verify_integrity

if __name__ == '__main__':
    import runpy
    verify_integrity()
    runpy.run_module('scripts.body_scan_cover_frames', run_name='__main__')

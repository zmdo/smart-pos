"""Remote GPU entry point; writes a new experiment directory on every run."""
import argparse
import os
from pathlib import Path

import cv2

from .evidence import PairEvidence
from .pipeline import prepare, align
from .preview import make_previews
from .verify import verify


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--job', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--asset-id', nargs='+')
    parser.add_argument('--split-only', action='store_true', help='Stop after boundary verification and child classification')
    parser.add_argument('--settings', type=Path)
    parser.add_argument('--cache', type=Path, default=Path('/root/autodl-fs/case-studio/cache/body-scan-pairs'))
    args = parser.parse_args()
    if args.settings:
        os.environ['CASE_SETTINGS'] = str(args.settings.resolve())
    cv2.setNumThreads(4)
    out = args.out.resolve()
    if out.exists():
        parser.error('output directory must not exist')
    try:
        prepare(args.job, out, args.asset_id, PairEvidence(args.cache))
        if not args.split_only:
            print('Running approved single-photo correction and framing...', flush=True)
            align(out)
        verify(out)
    finally:
        if (out/'summary.json').exists():
            make_previews(out)


if __name__ == '__main__':
    main()

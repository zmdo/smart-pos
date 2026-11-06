"""Run the independent person-scale experiment without replacing best practices."""
import argparse
from pathlib import Path

import cv2

from .pipeline import run


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--baseline-display', type=Path, required=True, help='Matching previous group display and visibility audit')
    parser.add_argument('--settings', type=Path, required=True, help='Private Qwen-compatible settings JSON')
    parser.add_argument('--cache', type=Path, default=Path('/root/autodl-fs/case-studio/cache/body-scan-person-scale'))
    parser.add_argument('--workers', type=int, choices=(1, 2, 3), default=3)
    args = parser.parse_args()
    cv2.setNumThreads(4)
    run(args.input, args.out, args.settings, args.cache, args.baseline_display, args.workers)


if __name__ == '__main__':
    main()

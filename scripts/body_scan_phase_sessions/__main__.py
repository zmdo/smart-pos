import argparse
import json
import os
from pathlib import Path

import cv2

from .pipeline import run
from .preview import preview


def main():
    parser = argparse.ArgumentParser(description='拍摄批次与多朝向训练阶段标注，保留旧版输出')
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--baseline', type=Path)
    parser.add_argument('--settings', type=Path)
    parser.add_argument('--workers', type=int, default=3, choices=range(1, 5))
    args = parser.parse_args()
    if args.settings:
        os.environ['CASE_SETTINGS'] = str(args.settings.resolve())
    cv2.setNumThreads(4)
    counts = run(args.input, args.out, workers=args.workers, baseline=args.baseline)
    preview(args.out)
    print(json.dumps(counts, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()

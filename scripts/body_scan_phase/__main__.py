import argparse
import json
import os
from pathlib import Path

import cv2

from .pipeline import run
from .preview import preview


def main():
    parser = argparse.ArgumentParser(description='同组同朝向训练前后标注；使用原图及等比参考，输出到新目录')
    parser.add_argument('--input', type=Path, required=True, help='group-display-v2 result directory')
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--settings', type=Path)
    parser.add_argument('--confidence', type=float, default=.8)
    args = parser.parse_args()
    if args.settings:
        os.environ['CASE_SETTINGS'] = str(args.settings.resolve())
    cv2.setNumThreads(4)
    counts = run(args.input, args.out, threshold=args.confidence)
    preview(args.out)
    print(json.dumps(counts, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()

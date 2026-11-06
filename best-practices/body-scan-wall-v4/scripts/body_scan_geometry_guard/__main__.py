import argparse
import json
from pathlib import Path

import cv2

from .pipeline import run


def main():
    parser = argparse.ArgumentParser(description='Experiment: guarded non-grid rollback; old outputs are immutable.')
    parser.add_argument('--input', type=Path, nargs='+', required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--member', action='append', help='Exact 店名/会员名; repeat for each complete group')
    args = parser.parse_args()
    cv2.setNumThreads(4)
    print(json.dumps(run(args.input, args.out, args.member), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()

"""Run on the GPU server: python -m scripts.body_scan --job ... --out ..."""
import argparse
import os
from pathlib import Path

import cv2

from .framing import UniformConfig
from .localization import SubjectLocalizer
from .pipeline import run
from .pose import ShoulderPose
from .preview import make_previews


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--job', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True, help='New directory; existing results cannot be overwritten')
    parser.add_argument('--asset-id', nargs='+')
    parser.add_argument('--background', choices=['all', 'grid', 'non-grid'], default='all')
    parser.add_argument('--width', type=int, default=768)
    parser.add_argument('--height', type=int, default=1792)
    parser.add_argument('--torso-fraction', type=float, default=.27)
    parser.add_argument('--shoulder-y', type=float, default=.23)
    parser.add_argument('--pose-weights', type=Path, default=Path('/root/autodl-fs/portrait-studio/models/yolo11m-pose.pt'))
    parser.add_argument('--pose-cache', type=Path, default=Path('/root/autodl-fs/case-studio/cache/shoulder-pose'))
    parser.add_argument('--settings', type=Path, help='Read-only VLM settings; only used if YOLO needs a coarse-box fallback')
    parser.add_argument('--font', type=Path, default=Path('/root/autodl-fs/case-studio/fonts/NotoSansSC.ttf'))
    args = parser.parse_args()
    if args.settings:
        os.environ['CASE_SETTINGS'] = str(args.settings)
    config = UniformConfig(args.width, args.height, args.torso_fraction, args.shoulder_y)
    cv2.setNumThreads(4)
    records, groups = run(args.job, args.out, SubjectLocalizer(),
                         ShoulderPose(args.pose_weights, args.pose_cache), config, args.asset_id, args.background)
    make_previews(args.out, records, groups, args.font)


if __name__ == '__main__':
    main()

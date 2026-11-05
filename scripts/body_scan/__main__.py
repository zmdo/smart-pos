"""Run on the GPU server: python -m scripts.body_scan --job ... --out ..."""
import argparse
import os
from pathlib import Path

import cv2

from .framing import UniformConfig
from .localization import SubjectLocalizer
from .pipeline import run
from .pose import ShoulderPose
from .non_grid import NonGridTransform, DEFAULT_WEIGHTS, DEFAULT_CACHE
from .preview import make_previews


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--job', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True, help='New directory; existing results cannot be overwritten')
    parser.add_argument('--asset-id', nargs='+')
    parser.add_argument('--background', choices=['all', 'grid', 'non-grid'], default='all')
    parser.add_argument('--classification-audit', type=Path, help='Source-verified cls-v3-wall audit for historical jobs')
    parser.add_argument('--previous', type=Path, help='Optional previous run for before/after finished-image comparisons')
    parser.add_argument('--non-grid-mode', choices=['pinhole', 'identity'], default='pinhole')
    parser.add_argument('--refine-background', action='store_true', help='After pinhole, refine reliable wall geometry and registered group scale; retain an adjacent pinhole baseline')
    parser.add_argument('--camera-weights', type=Path, default=DEFAULT_WEIGHTS)
    parser.add_argument('--camera-cache', type=Path, default=DEFAULT_CACHE)
    parser.add_argument('--width', type=int, default=768)
    parser.add_argument('--height', type=int, default=1792)
    parser.add_argument('--torso-fraction', type=float, default=.27)
    parser.add_argument('--shoulder-y', type=float, default=.23)
    parser.add_argument('--pose-weights', type=Path, default=Path('/root/autodl-fs/portrait-studio/models/yolo11m-pose.pt'))
    parser.add_argument('--pose-cache', type=Path, default=Path('/root/autodl-fs/case-studio/cache/shoulder-pose'))
    parser.add_argument('--settings', type=Path, help='Read-only VLM settings for standardization background screening and optional localization fallback')
    parser.add_argument('--font', type=Path, default=Path('/root/autodl-fs/case-studio/fonts/NotoSansSC.ttf'))
    args = parser.parse_args()
    if args.refine_background and args.non_grid_mode != 'pinhole':
        parser.error('--refine-background requires --non-grid-mode pinhole')
    base_out=args.out.with_name(args.out.name+'-pinhole') if args.refine_background else args.out
    if args.out.exists() or (args.refine_background and base_out.exists()):
        parser.error('output directories must not exist')
    if args.settings:
        os.environ['CASE_SETTINGS'] = str(args.settings)
    config = UniformConfig(args.width, args.height, args.torso_fraction, args.shoulder_y)
    cv2.setNumThreads(4)
    records, groups = run(args.job, base_out, SubjectLocalizer(),
                         ShoulderPose(args.pose_weights, args.pose_cache), config, args.asset_id, args.background,
                         NonGridTransform(args.camera_weights, args.camera_cache, args.non_grid_mode), args.classification_audit)
    make_previews(base_out, records, groups, args.font, args.previous)
    if args.refine_background:
        from .refinement import run as refine_background
        refine_background(base_out,args.out)


if __name__ == '__main__':
    main()

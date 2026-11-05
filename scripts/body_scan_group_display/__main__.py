"""Independent post-standardization experiment; never overwrites approved photos."""
import argparse
import copy
import json
import os
from pathlib import Path

import cv2

from .pipeline import run
from .planning import Config, PROFILES
from .preview import make_previews
from .verify import verify


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, nargs='+', required=True, help='Approved single-photo result directories')
    parser.add_argument('--out', type=Path, required=True, help='A new experiment directory')
    parser.add_argument('--audit', type=Path, help='Reuse a fingerprint-matched visibility audit including boundary guards')
    parser.add_argument('--settings', type=Path)
    parser.add_argument('--workers', type=int, choices=range(1, 5), default=3)
    parser.add_argument('--width', type=int, default=768)
    parser.add_argument('--max-stretch', type=float, default=1.10, help='Maximum vertical / horizontal scaling ratio')
    parser.add_argument('--max-crop-loss', type=float, default=.25, help='Additional area removed AFTER common intersection')
    parser.add_argument('--crop-step', type=float, default=.02)
    parser.add_argument('--max-steps', type=int, default=80)
    parser.add_argument('--profiles', type=Path, help='JSON overriding height (at width 768), shoulder_y and label by profile')
    args = parser.parse_args()
    if args.settings:
        os.environ['CASE_SETTINGS'] = str(args.settings.resolve())
    profiles = copy.deepcopy(PROFILES)
    if args.profiles:
        values = json.loads(args.profiles.read_text(encoding='utf-8'))
        if not isinstance(values, dict) or set(values)-set(profiles):
            parser.error('unknown profile override')
        for key, value in values.items():
            if not isinstance(value, dict) or set(value)-{'height', 'shoulder_y', 'label'}:
                parser.error('invalid profile fields')
            profiles[key].update(value)
    config = Config(args.width, args.max_stretch, args.max_crop_loss, args.crop_step, args.max_steps)
    cv2.setNumThreads(4)
    run(args.input, args.out, args.audit, config, profiles, args.workers)
    verify(args.out)
    make_previews(args.out)


if __name__ == '__main__':
    main()

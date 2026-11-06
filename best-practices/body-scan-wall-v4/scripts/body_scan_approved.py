"""Approved v4 entry points: v2 refinement or v3 upgrade, always followed by the guard."""
import argparse
import json
from pathlib import Path

import cv2

from snapshot import verify_integrity
from scripts.body_scan.pipeline import save_json
from scripts.body_scan.preview import make_previews
from scripts.body_scan.refinement import run as refine
from scripts.body_scan_geometry_guard.pipeline import run as guard, digest

VERSION = 'body-scan-wall-v4'
FONT = Path('/root/autodl-fs/case-studio/fonts/NotoSansSC.ttf')


def ensure_new(*paths):
    if any(Path(path).exists() for path in paths):
        raise ValueError('output_directories_must_not_exist')


def finish(inputs, out, members=None, font=FONT, previous=None):
    """Keep the tested guard bytes unchanged; declare provenance and package previews here."""
    out = Path(out)
    ensure_new(out)
    integrity = verify_integrity()
    verification = guard(inputs, out, members)
    config = json.loads((out/'config.json').read_text(encoding='utf-8'))
    config.update({'experimental': False, 'best_practice_version': VERSION,
                   'snapshot_source_commit': integrity['source_commit'],
                   'snapshot_manifest_sha256': digest(Path(integrity['snapshot_root'])/'manifest.json')})
    save_json(out/'config.json', config)
    rows = json.loads((out/'summary.json').read_text(encoding='utf-8'))
    groups = json.loads((out/'groups.json').read_text(encoding='utf-8'))
    make_previews(out, rows, groups, font, previous, stage_label='标准化 v4 · 可靠几何检查与必要回退')
    return verification


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--baseline', type=Path, help='Existing v2 pinhole result, refine wall then guard')
    source.add_argument('--input', type=Path, nargs='+', help='Existing unguarded v3 result(s), guard only')
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--member', action='append', help='Exact 店名/会员名; only with --input')
    parser.add_argument('--group', nargs='+', help='Wall refinement subset; only with --baseline')
    parser.add_argument('--no-group-scale', action='store_true')
    parser.add_argument('--font', type=Path, default=FONT)
    parser.add_argument('--previous', type=Path)
    args = parser.parse_args()
    if args.baseline and args.member:
        parser.error('--member requires --input')
    if args.input and (args.group or args.no_group_scale):
        parser.error('--group and --no-group-scale require --baseline')
    wall_out = args.out.with_name(args.out.name+'-wall')
    ensure_new(args.out, *([wall_out] if args.baseline else []))
    verify_integrity(); cv2.setNumThreads(4)
    if args.baseline:
        refine(args.baseline, wall_out, group_ids=args.group, enable_group_scale=not args.no_group_scale)
        inputs = [wall_out]
    else:
        inputs = args.input
    print(json.dumps(finish(inputs, args.out, args.member, args.font, args.previous), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()

"""Approved cover entry: consume head-to-hip frames; never recrop display photos."""
import argparse
from pathlib import Path
from scripts.body_scan_contracts.io import read
from .pipeline import run


def main(argv=None):
    p = argparse.ArgumentParser(description='会员案例封面：已确认双图、报告文案与 HTML 展示')
    p.add_argument('--delivery', type=Path, required=True)
    p.add_argument('--cover-frames', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--config', type=Path, help='可选标题、正文、教练、地址及品牌覆盖配置')
    args = p.parse_args(argv)
    if read(args.cover_frames/'frames.json').get('version') != 'body-scan-cover-frames-v2':
        raise ValueError('approved_cover_requires_head_hip_frames_v2')
    result = run(args.delivery, args.out, args.config, args.cover_frames)
    print(result['counts'])
    return result


if __name__ == '__main__':
    main()

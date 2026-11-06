"""Approved scale calibration followed by one shared frame per person."""
import argparse
import json
import os
from collections import Counter
from dataclasses import asdict
from pathlib import Path

import cv2

from snapshot import verify_integrity
from scripts.body_scan.pipeline import save_json
from scripts.body_scan_person_scale.pipeline import run as calibrate, digest
from scripts.body_scan_person_scale.verify import verify as verify_scale
from scripts.body_scan_person_scale.report import run as comparison
from scripts.body_scan_group_display.pipeline import run as display
from scripts.body_scan_group_display.planning import Config
from scripts.body_scan_group_display.preview import make_previews
from scripts.body_scan_group_display.verify import verify as verify_display

VERSION = 'body-scan-group-display-v3'


def run(args):
    snapshot = verify_integrity()
    source = args.input.resolve(); out = args.out.resolve()
    if out.exists():
        raise ValueError('output_directory_already_exists')
    if source in out.parents or (args.baseline_display and args.baseline_display.resolve() in out.parents):
        raise ValueError('output_must_be_outside_input_directories')
    if args.visibility_settings:
        os.environ['CASE_SETTINGS'] = str(args.visibility_settings.resolve())
    config = Config(width=args.width, max_stretch=args.max_stretch)
    for path in (source/'config.json', source/'summary.json', args.settings):
        if not path.is_file():
            raise ValueError('missing_required_input_file')
    out.mkdir(parents=True)
    state = {'version': VERSION, 'status': 'running', 'stage': 'baseline_display',
             'input': str(source), 'snapshot': snapshot, 'display_parameters': asdict(config),
             'baseline_display_generated': args.baseline_display is None}
    save_json(out/'workflow.json', state)
    try:
        baseline = args.baseline_display.resolve() if args.baseline_display else out/'baseline-display'
        if args.baseline_display is None:
            display([source], baseline, config=config, workers=args.workers)
            verify_display(baseline)
            make_previews(baseline)
        state.update(stage='person_scale', baseline_display=str(baseline))
        save_json(out/'workflow.json', state)
        rows = calibrate(source, out/'standardized', args.settings, args.cache, baseline, args.workers)
        # Archive provenance only; frozen processing kernels and prompt versions stay unchanged.
        path = out/'standardized/config.json'
        metadata = json.loads(path.read_text())
        metadata.update(experimental=False, best_practice_version=VERSION,
                        snapshot_source_commit=snapshot['source_commit'],
                        snapshot_manifest_sha256=digest(Path(__file__).parent/'manifest.json'))
        save_json(path, metadata)
        scale_verification = verify_scale(out/'standardized')
        state.update(stage='final_display', calibration_counts=dict(Counter(
            r.get('person_scale', {}).get('status', r['status']) for r in rows)))
        save_json(out/'workflow.json', state)
        final_rows, _ = display([out/'standardized'], out/'display', config=config, workers=args.workers)
        display_verification = verify_display(out/'display')
        make_previews(out/'display')
        comparison(out/'standardized', baseline, out/'display', out/'comparison', args.font, args.focus)
        review_ids = [r['asset_id'] for r in rows if r.get('person_scale', {}).get('status') == 'retained_for_review']
        display_review_ids = [r['asset_id'] for r in final_rows if r['status'] != 'displayed']
        state.update(stage='finished', status='completed_with_review' if review_ids or display_review_ids else 'complete',
                     scale_review_asset_ids=review_ids, display_review_asset_ids=display_review_ids,
                     displayed=sum(r['status'] == 'displayed' for r in final_rows))
        save_json(out/'verification.json', {'scale': scale_verification, 'display': display_verification})
        save_json(out/'workflow.json', state)
        (out/'index.html').write_text('<!doctype html><meta charset="utf-8"><title>同组展示 v3</title>'
            '<style>body{font:18px system-ui;max-width:800px;margin:60px auto;padding:24px;line-height:1.8}</style>'
            '<h1>人物尺度校准与同组展示 v3</h1>'
            f'<p>已输出 {state["displayed"]} 张；尺度待复核 {len(review_ids)} 张；取景待复核 {len(display_review_ids)} 张。'
            '尺度待复核图片保留原尺度，不表示已校准成功。</p>'
            '<p><a href="comparison/index.html">查看新旧对比与尺度处理原因</a></p>'
            '<p><a href="display/index.html">查看全部成品</a> · '
            '<a href="display/body-scan-group-display-results.zip">下载成品包</a></p>'
            '<p><a href="workflow.json">流程记录</a> · <a href="verification.json">验证记录</a></p>', encoding='utf-8')
        return state
    except Exception as error:
        state.update(status='failed', error_type=type(error).__name__)
        save_json(out/'workflow.json', state)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True, help='Approved v4 standardized directory')
    parser.add_argument('--baseline-display', type=Path, help='Matching previous display; generated if omitted')
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--settings', type=Path, required=True, help='Private Qwen-compatible scale settings')
    parser.add_argument('--visibility-settings', type=Path, help='Optional separate settings for unchanged visibility node')
    parser.add_argument('--cache', type=Path, default=Path('/root/autodl-fs/case-studio/cache/body-scan-person-scale'))
    parser.add_argument('--workers', type=int, choices=(1, 2, 3), default=3)
    parser.add_argument('--width', type=int, default=768)
    parser.add_argument('--max-stretch', type=float, default=1.10)
    parser.add_argument('--font', type=Path, default=Path('/root/autodl-fs/case-studio/fonts/NotoSansSC.ttf'))
    parser.add_argument('--focus', nargs='+', help='Optional asset IDs for the comparison sheet only')
    args = parser.parse_args()
    cv2.setNumThreads(4)
    print(json.dumps(run(args), ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()

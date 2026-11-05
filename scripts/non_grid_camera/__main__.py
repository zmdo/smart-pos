"""Independent non-grid camera experiment: no common pipeline or pose framing calls."""
import argparse
import hashlib
import json
import re
import zipfile
from collections import Counter
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageOps

from .calibration import Calibrator, warnings, GEOCALIB_COMMIT
from .diagnostics import reference_lines, line_report, overlay
from .geometry import render


def save_json(path, value):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    temporary.replace(path)


def eligible(row):
    c = row.get('classification') or {}
    if c.get('kind') != 'body_scan':
        return 'not_body_scan'
    if c.get('phase') == 'both' or c.get('people') != 1:
        return 'comparison_or_multiple_people'
    if c.get('wall_background') is not True or c.get('body_scan_pose') is not True or c.get('training_activity'):
        return 'wall_and_static_pose_not_confirmed'
    if c.get('background') == 'grid_board':
        return 'grid_outside_this_experiment'
    return None


def assess_variants(record):
    """Expose incompatible camera estimates; no model output is auto-approved."""
    variants = record.get('variants', {})
    estimates = [variants.get(name, {}).get('calibration') for name in ('pinhole', 'radial')]
    record['automatic_adoption'] = False
    if not all(estimates):
        return
    first, second = estimates
    difference = {name: abs(first[name]-second[name]) for name in ('roll_deg', 'pitch_deg', 'vfov_deg')}
    record['model_difference'] = difference
    if difference['roll_deg'] > 2 or difference['pitch_deg'] > 5 or difference['vfov_deg'] > 15:
        for variant in variants.values():
            if 'camera_models_disagree' not in variant.setdefault('warnings', []):
                variant['warnings'].append('camera_models_disagree')


def comparison(dest, record, font):
    panels = [('original.png', '原图'), ('pinhole.png', '相机侧倾 / 俯仰校正'),
              ('radial.png', '相机校正 + 径向校正候选')]
    width, height = 400, 680
    thumbnails = {}
    for name, _ in panels:
        if (dest/name).exists():
            with Image.open(dest/name) as image:
                thumbnails[name] = ImageOps.contain(image.convert('RGB'), (width-20, height-35), Image.Resampling.LANCZOS)
    content_bottom = 90+max(im.height for im in thumbnails.values())
    canvas = Image.new('RGB', (width*3+40, content_bottom+105), '#eeeae3')
    draw = ImageDraw.Draw(canvas)
    draw.text((15, 10), record['member']+' / '+record['asset_id'], font=font, fill='#26352c')
    for index, (name, label) in enumerate(panels):
        x = 15+index*width
        draw.text((x, 50), label, font=font, fill='#26352c')
        if name in thumbnails:
            thumb = thumbnails[name]
            canvas.paste(thumb, (x+(width-20-thumb.width)//2, 90))
        else:
            draw.text((x, 100), '未生成：几何参数待复核', font=font, fill='#9d513d')
        if index:
            variant = record['variants'][('pinhole', 'radial')[index-1]]
            estimate = variant.get('calibration', {})
            if estimate:
                text = f"侧倾 {estimate['roll_deg']:.1f}°  俯仰 {estimate['pitch_deg']:.1f}°"
                draw.text((x, content_bottom+20), text, font=font, fill='#26352c')
                note = '模型分歧大，待复核' if 'camera_models_disagree' in variant.get('warnings', []) else ('候选待审阅' if not variant.get('warnings') else '有不确定性提示')
                draw.text((x, content_bottom+55), note, font=font, fill='#9d513d')
    canvas.save(dest/'comparison.jpg', quality=93)


def run(audit, baseline, out, weights, cache, asset_ids=None, font_path=None):
    rows = json.loads(audit.read_text(encoding='utf-8'))
    previous = {r['asset_id']: r for r in json.loads((baseline/'summary.json').read_text(encoding='utf-8'))}
    if asset_ids:
        if set(asset_ids)-{r['asset_id'] for r in rows}:
            raise ValueError('unknown_asset_ids')
        rows = [r for r in rows if r['asset_id'] in asset_ids]
    if any(not re.fullmatch('[A-Za-z0-9_-]+', r['asset_id']) for r in rows):
        raise ValueError('invalid_asset_id')
    out.mkdir(parents=True, exist_ok=False)
    models = {'pinhole': Calibrator(weights/'geocalib-pinhole.tar', cache),
              'radial': Calibrator(weights/'geocalib-distorted.tar', cache)}
    font = ImageFont.truetype(str(font_path), 19) if font_path and font_path.exists() else ImageFont.load_default()
    save_json(out/'config.json', {'geocalib_commit': GEOCALIB_COMMIT, 'audit': str(audit),
                                 'baseline': str(baseline), 'asset_ids': [r['asset_id'] for r in rows],
                                 'scope': 'geometry_only_experiment', 'pipeline_integration': False})
    records = []
    for row in rows:
        aid = row['asset_id']
        record = {**row, 'status': 'skipped'}
        reason = eligible(row)
        if reason:
            record['reason'] = reason
        else:
            try:
                path = Path(row['source'])
                if hashlib.sha256(path.read_bytes()).hexdigest() != row['source_sha256']:
                    raise ValueError('source_changed_after_classification')
                old = previous.get(aid, {})
                if old.get('source_sha256') != row['source_sha256'] or 'subject_box' not in old:
                    raise ValueError('verified_subject_box_unavailable')
                source = cv2.imread(str(path))
                if source is None:
                    raise ValueError('unreadable_image')
                dest = out/aid; dest.mkdir()
                cv2.imwrite(str(dest/'original.png'), source)
                lines = reference_lines(source, old['subject_box'])
                cv2.imwrite(str(dest/'references.jpg'), overlay(source, lines))
                record['variants'] = {}
                for name, model in models.items():
                    variant = {'status': 'needs_review'}
                    try:
                        estimate = model(source, 'pinhole' if name == 'pinhole' else 'simple_radial')
                        notes = warnings(estimate)
                        variant.update({'calibration': estimate, 'warnings': notes})
                        if 'large_camera_tilt' in notes or 'field_of_view_outside_expected_range' in notes:
                            raise ValueError('camera_estimate_outside_experiment_limits')
                        image, valid, mapping = render(source, old['subject_box'], estimate, radial=name == 'radial')
                        diagnostics = line_report(lines, estimate, mapping, name == 'radial')
                        variant.update({'status': 'candidate', 'mapping': mapping, 'line_diagnostics': diagnostics})
                        for filename, data in ((name+'.png', image), (name+'-valid.png', valid),
                                               (name+'-references.jpg', overlay(image, diagnostics, True))):
                            if not cv2.imwrite(str(dest/filename), data):
                                raise OSError('image_write_failed')
                    except (ValueError, RuntimeError, OSError) as error:
                        variant.update({'status': 'needs_review', 'reason': str(error)})
                    record['variants'][name] = variant
                record['status'] = 'candidate' if any(v['status'] == 'candidate' for v in record['variants'].values()) else 'needs_review'
                assess_variants(record)
                comparison(dest, record, font)
                save_json(dest/'report.json', record)
            except (ValueError, OSError) as error:
                record.update({'status': 'needs_review', 'reason': str(error)})
        records.append(record)
        save_json(out/'summary.json', records)
        print(aid, record['status'], record.get('reason', ''), flush=True)
    counts = dict(Counter(r['status'] for r in records)); save_json(out/'counts.json', counts)
    with zipfile.ZipFile(out/'camera-experiment.zip', 'w', zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(out.rglob('*')):
            if path.is_file() and path.suffix != '.zip':
                archive.write(path, path.relative_to(out))
    return records


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--audit', type=Path, required=True)
    parser.add_argument('--baseline', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--asset-id', nargs='+')
    parser.add_argument('--weights', type=Path, default=Path('/root/autodl-fs/case-studio/models/geocalib'))
    parser.add_argument('--cache', type=Path, default=Path('/root/autodl-fs/case-studio/cache/camera-calibration'))
    parser.add_argument('--font', type=Path, default=Path('/root/autodl-fs/case-studio/fonts/NotoSansSC.ttf'))
    args = parser.parse_args()
    cv2.setNumThreads(4)
    run(args.audit, args.baseline, args.out, args.weights, args.cache, args.asset_id, args.font)

"""Independent fixed-size, subject-centered variant of the saved v2.3 grid crop.

Read an existing grid-crop experiment. Never rerun inference or modify its files.
Default: 768x1280 (3:5). See docs/solutions/会员案例素材生产方案/13-人物居中标准框.md.
"""
import argparse
import hashlib
import json
import re
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path

import cv2
import numpy as np

from grid_crop import content_mask, project


class FrameUnavailable(ValueError):
    pass


@dataclass(frozen=True)
class FrameConfig:
    width: int = 768
    height: int = 1280
    subject_fill: float = .90

    def __post_init__(self):
        if not (64 <= self.width <= 4096 and 64 <= self.height <= 4096):
            raise FrameUnavailable('output_dimensions_must_be_between_64_and_4096')
        if not .5 <= self.width/self.height <= 1.:
            raise FrameUnavailable('output_aspect_must_be_between_1_to_2_and_1_to_1')
        if not .6 <= self.subject_fill <= .98:
            raise FrameUnavailable('subject_fill_must_be_between_0.60_and_0.98')


def corners(box):
    x1, y1, x2, y2 = box
    return np.array([[x1, y1], [x2, y1], [x2, y2], [x1, y2]], float)


def polygon_fraction(polygon, rectangle):
    p = np.asarray(polygon, np.float32)
    total = cv2.contourArea(p)
    if total <= 0:
        raise FrameUnavailable('empty_subject_polygon')
    intersection, _ = cv2.intersectConvexConvex(p, corners(rectangle).astype(np.float32))
    return float(np.clip(intersection/total, 0, 1))


def select_frame(bounds, subject_box, H, config):
    """Fixed aspect, adaptive source resolution, minimum necessary center shift.

    The old crop is the safe envelope, not the image to stretch to the new size.
    Visible headroom takes priority when the desired centered frame is too tall.
    """
    bounds, subject_box, H = np.asarray(bounds, float), np.asarray(subject_box, float), np.asarray(H, float)
    if bounds.shape != (4,) or subject_box.shape != (4,) or H.shape != (3, 3):
        raise FrameUnavailable('invalid_geometry_shape')
    if not all(np.isfinite(x).all() for x in (bounds, subject_box, H)):
        raise FrameUnavailable('nonfinite_geometry')
    if (bounds[2:] <= bounds[:2]).any() or (subject_box[2:] <= subject_box[:2]).any():
        raise FrameUnavailable('empty_geometry')
    polygon = project(corners(subject_box), H)
    center = project([(subject_box[:2]+subject_box[2:])/2], H)[0]
    if (center < bounds[:2]).any() or (center > bounds[2:]).any():
        raise FrameUnavailable('subject_center_outside_grid_envelope')
    low, high = polygon.min(axis=0), polygon.max(axis=0)
    aspect = config.width/config.height
    desired_height = max((high[1]-low[1])/config.subject_fill,
                         (high[0]-low[0])/(.84*aspect))
    available_height = min(bounds[3]-bounds[1], (bounds[2]-bounds[0])/aspect)
    height = min(desired_height, available_height)
    width = height*aspect
    if min(width, height) < 32:
        raise FrameUnavailable('standard_frame_too_small')
    left = float(np.clip(center[0]-width/2, bounds[0], bounds[2]-width))
    top = float(np.clip(center[1]-height/2, bounds[1], bounds[3]-height))
    # The previous image may already cut off the head: never invent that area.
    top = min(top, max(bounds[1], low[1]-.025*height))
    rect = [left, top, left+width, top+height]
    scale = config.width/width
    # Pixel-center convention, matching a crop followed by isotropic resizing.
    A = np.array([[scale, 0., scale*(.5-left)-.5],
                  [0., scale, scale*(.5-top)-.5], [0., 0., 1.]])
    head_box = subject_box.copy()
    head_box[3] = subject_box[1]+.2*(subject_box[3]-subject_box[1])
    visible_fraction = polygon_fraction(polygon, rect)
    head_fraction = polygon_fraction(project(corners(head_box), H), rect)
    offset = ((np.array([left+width/2, top+height/2])-center)/[width, height]).tolist()
    warnings = []
    if visible_fraction < .9:
        warnings.append('partial_subject_box_crop')
    if head_fraction < .95:
        warnings.append('partial_head_band_crop_or_source_truncation')
    if max(map(abs, offset)) > .08:
        warnings.append('center_shift_to_fit_available_image')
    if scale > 1.25:
        warnings.append('upscaled_from_limited_source_resolution')
    return rect, A, {
        'bounds_xyxy': rect, 'safe_envelope_xyxy': bounds.tolist(),
        'subject_center_corrected': center.tolist(), 'center_offset_fraction': offset,
        'subject_box_retained_fraction': visible_fraction,
        'head_band_box_retained_fraction': head_fraction,
        'target_subject_fill': config.subject_fill,
        'actual_box_height_fraction': float((high[1]-low[1])/height),
        'source_frame_size': [width, height], 'uniform_scale': float(scale),
        'output_size': [config.width, config.height],
        'H_corrected_to_standard': A.tolist(), 'H_source_to_standard': (A @ H).tolist(),
        'warnings': warnings,
    }


def save_preview(out, full, standardized, info):
    from PIL import Image, ImageDraw
    left = full.copy()
    for box, color in ((info['safe_envelope_xyxy'], (70, 170, 70)),
                       (info['bounds_xyxy'], (230, 140, 20))):
        x1, y1, x2, y2 = np.round(box).astype(int)
        cv2.rectangle(left, (x1, y1), (x2-1, y2-1), color, 3)
    center = tuple(np.round(info['subject_center_corrected']).astype(int))
    cv2.drawMarker(left, center, (30, 50, 220), cv2.MARKER_CROSS, 22, 3)
    images = [Image.fromarray(cv2.cvtColor(im, cv2.COLOR_BGR2RGB)) for im in (left, standardized)]
    images = [im.resize((round(im.width*760/im.height), 760), Image.Resampling.LANCZOS) for im in images]
    canvas = Image.new('RGB', (sum(im.width for im in images)+60, 820), '#eeeae3')
    draw = ImageDraw.Draw(canvas)
    x = 20
    labels = ['RECTIFIED / GREEN: GRID / BLUE: STANDARD', 'STANDARD '+str(info['output_size'])]
    for label, im in zip(labels, images):
        draw.text((x, 12), Path(out).name+'  '+label, fill='#26352c')
        canvas.paste(im, (x, 40))
        x += im.width+20
    canvas.save(Path(out)/'frame_preview.jpg', quality=94)


def process(input_dir, row, out, config):
    input_dir, out = Path(input_dir), Path(out)
    out.mkdir(parents=True, exist_ok=False)
    report = {'asset_id': row['asset_id'], 'method': 'subject-centered-standard-frame-v1',
              'source_report': str(input_dir/'report.json'), 'config': asdict(config),
              'status': 'skipped', 'new_model_requests': 0}
    classification = row.get('classification', {})
    if classification.get('phase') == 'both' or classification.get('people', 0) > 1:
        report['reason'] = 'comparison_or_multiple_people'
    elif (classification.get('people') != 1 or classification.get('kind') != 'body_scan'
          or classification.get('background') != 'grid_board'):
        report['reason'] = 'not_confirmed_single_grid_photo'
    elif row.get('status') != 'corrected' or row.get('crop', {}).get('status') != 'cropped':
        report.update(status='needs_review', reason='requires_accepted_v23_grid_crop')
    else:
        try:
            source = cv2.imread(str(input_dir/'original.png'))
            full = cv2.imread(str(input_dir/'corrected.png'))
            valid = cv2.imread(str(input_dir/'valid_mask.png'), cv2.IMREAD_GRAYSCALE)
            if source is None or full is None or valid is None:
                raise FrameUnavailable('missing_previous_image_or_mask')
            if valid.shape != full.shape[:2] or list(source.shape[1::-1]) != row['size']:
                raise FrameUnavailable('previous_image_dimensions_mismatch')
            H = np.asarray(row['H_source_to_output'], float)
            rect, A, info = select_frame(row['crop']['bounds_xyxy'], row['subject_box'], H, config)
            content, _ = content_mask(source)
            warped_content = cv2.warpPerspective(content, H, (full.shape[1], full.shape[0]), flags=cv2.INTER_NEAREST)
            safe = cv2.erode(((valid > 0) & (warped_content > 0)).astype(np.uint8),
                             np.ones((9, 9), np.uint8), borderType=cv2.BORDER_CONSTANT, borderValue=0)
            x1, y1 = np.floor(rect[:2]).astype(int)
            x2, y2 = np.ceil(rect[2:]).astype(int)
            if x1 < 0 or y1 < 0 or x2 > full.shape[1] or y2 > full.shape[0] or not safe[y1:y2, x1:x2].all():
                raise FrameUnavailable('standard_frame_contains_invalid_pixels')
            output_H = A @ H
            size = (config.width, config.height)
            output_valid = cv2.warpPerspective(content, output_H, size, flags=cv2.INTER_NEAREST)
            if not (output_valid == 255).all():
                raise FrameUnavailable('standard_output_contains_invalid_pixels')
            # Sample the saved original once with the SAME perspective matrix,
            # composed only with isotropic scale and translation. No second warp.
            image = cv2.warpPerspective(source, output_H, size, flags=cv2.INTER_CUBIC,
                                        borderMode=cv2.BORDER_CONSTANT, borderValue=(242, 242, 242))
            if not cv2.imwrite(str(out/'standardized.png'), image):
                raise FrameUnavailable('cannot_write_standard_output')
            save_preview(out, full, image, info)
            report.update(status='standardized', frame=info, valid_fraction=1.,
                          presentation_file='standardized.png', render='single_resample_of_saved_original',
                          source_sha256=hashlib.sha256((input_dir/'original.png').read_bytes()).hexdigest())
        except (FrameUnavailable, ValueError, KeyError) as error:
            report.update(status='needs_review', reason=str(error))
    (out/'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
    return report


def contact_sheet(out, rows):
    from PIL import Image, ImageDraw
    images = [r for r in rows if r['status'] == 'standardized']
    if not images:
        return
    canvas = Image.new('RGB', (240*4, 410*((len(images)+3)//4)), '#eeeae3')
    draw = ImageDraw.Draw(canvas)
    for i, r in enumerate(images):
        x, y = (i % 4)*240, (i//4)*410
        draw.text((x+12, y+10), r['asset_id']+'  '+str(r['frame']['output_size']), fill='#26352c')
        im = Image.open(Path(out)/r['asset_id']/'standardized.png').convert('RGB')
        im.thumbnail((216, 360), Image.Resampling.LANCZOS)
        canvas.paste(im, (x+(240-im.width)//2, y+36))
    canvas.save(Path(out)/'standard_frames_contact_sheet.jpg', quality=94)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True, help='Existing v2.3 experiment directory, read only')
    parser.add_argument('--out', type=Path, required=True, help='New separate output directory')
    parser.add_argument('--width', type=int, default=768)
    parser.add_argument('--height', type=int, default=1280)
    parser.add_argument('--subject-fill', type=float, default=.90)
    parser.add_argument('--asset-id', nargs='*')
    args = parser.parse_args()
    config = FrameConfig(args.width, args.height, args.subject_fill)
    if args.out.resolve().is_relative_to(args.input.resolve()):
        parser.error('--out must be separate from the saved input experiment')
    rows = json.loads((args.input/'summary.json').read_text())
    rows = [r for r in rows if not args.asset_id or r['asset_id'] in args.asset_id]
    if not rows or any(not re.fullmatch(r'[A-Za-z0-9_-]+', r['asset_id']) for r in rows):
        parser.error('No matching assets or invalid asset ID')
    if len({r['asset_id'] for r in rows}) != len(rows):
        parser.error('Duplicate asset IDs')
    args.out.mkdir(parents=True, exist_ok=False)
    (args.out/'frame_config.json').write_text(json.dumps(asdict(config), indent=2))
    cv2.setNumThreads(4)
    results = []
    for row in rows:
        r = process(args.input/row['asset_id'], row, args.out/row['asset_id'], config)
        results.append(r)
        (args.out/'summary.json').write_text(json.dumps(results, ensure_ascii=False, indent=2))
        print(r['asset_id'], r['status'], r.get('reason', ''), flush=True)
    contact_sheet(args.out, results)
    print(dict(Counter(r['status'] for r in results)), flush=True)


if __name__ == '__main__':
    main()

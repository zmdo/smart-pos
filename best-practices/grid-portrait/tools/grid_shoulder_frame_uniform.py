"""Fixed subject scale across all members, with explicit rectangular padding.

Reuse approved poses and grid calibration. Never increase the person's scale
to fill missing source pixels. No new model inference or background generation.
"""
import argparse
import json
import re
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path

import cv2
import numpy as np

from grid_crop import content_mask, project
from grid_shoulder_frame import annotate, group_previews, save_json
from grid_shoulder_frame_tall import expanded_envelope
from shoulder_alignment import AlignmentUnavailable


@dataclass(frozen=True)
class UniformConfig:
    width: int = 768
    height: int = 1792
    torso_fraction: float = .27
    shoulder_y: float = .23
    background_rgb: tuple = (238, 234, 227)

    def __post_init__(self):
        if not (64 <= self.width <= 4096 and 64 <= self.height <= 4096):
            raise AlignmentUnavailable('invalid_output_size')
        if not .3 <= self.width/self.height <= 1.:
            raise AlignmentUnavailable('invalid_portrait_aspect')
        if not .15 <= self.torso_fraction <= .45:
            raise AlignmentUnavailable('invalid_torso_fraction')
        if not .1 <= self.shoulder_y <= .4 or self.shoulder_y+self.torso_fraction >= .9:
            raise AlignmentUnavailable('invalid_shoulder_target')
        if len(self.background_rgb) != 3 or any(not isinstance(c, int) or not 0 <= c <= 255 for c in self.background_rgb):
            raise AlignmentUnavailable('invalid_background_color')


def uniform_plan(pose, config):
    """The same torso/frame ratio and shoulder location for every image."""
    anchor = np.asarray(pose['anchor'], float)
    length = float(pose['torso_length'])
    if anchor.shape != (2,) or not np.isfinite(anchor).all() or not np.isfinite(length) or length <= 0:
        raise AlignmentUnavailable('invalid_saved_pose')
    torso = config.height*config.torso_fraction
    scale = torso/length
    target = np.array([config.width/2-.5, config.height*config.shoulder_y-.5])
    A = np.array([[scale, 0., target[0]-scale*anchor[0]],
                  [0., scale, target[1]-scale*anchor[1]], [0., 0., 1.]])
    top_left = anchor+.5-np.array([config.width/2, config.height*config.shoulder_y])/scale
    return {'bounds_xyxy': [*top_left, *(top_left+np.array([config.width, config.height])/scale)],
            'uniform_scale': float(scale), 'H_corrected_to_aligned': A.tolist(),
            'shoulder_target_xy': target.tolist(), 'torso_target_pixels': float(torso),
            'torso_fraction': config.torso_fraction}


def content_rectangle(source_bounds, A, width, height):
    """Integer output pixels whose centers fall inside the safe source window."""
    x1, y1, x2, y2 = source_bounds
    if x2 <= x1 or y2 <= y1:
        raise AlignmentUnavailable('empty_source_window')
    p = project([[x1, y1], [x2-1, y2-1]], A)
    left, top = np.maximum(0, np.ceil(p[0]-1e-8)).astype(int)
    right, bottom = np.minimum([width, height], np.floor(p[1]+1e-8)+1).astype(int)
    if right <= left or bottom <= top:
        raise AlignmentUnavailable('source_window_outside_frame')
    return [int(left), int(top), int(right), int(bottom)]


def compose(source, source_valid, H, rect, config):
    """Sample original pixels once, paste the safe rectangle onto a flat mat."""
    width, height = config.width, config.height
    x1, y1, x2, y2 = rect
    mask = cv2.warpPerspective(source_valid, H, (width, height), flags=cv2.INTER_NEAREST)
    if not (mask[y1:y2, x1:x2] == 255).all():
        raise AlignmentUnavailable('content_rectangle_contains_invalid_source_pixels')
    sampled = cv2.warpPerspective(source, H, (width, height), flags=cv2.INTER_CUBIC)
    image = np.empty((height, width, 3), np.uint8)
    image[:] = config.background_rgb[::-1]
    image[y1:y2, x1:x2] = sampled[y1:y2, x1:x2]
    used = np.zeros((height, width), np.uint8)
    used[y1:y2, x1:x2] = 255
    return image, used


def render(source_dir, out, row, pose, config):
    source = cv2.imread(str(source_dir/'original.png'))
    valid = cv2.imread(str(source_dir/'valid_mask.png'), 0)
    full = cv2.imread(str(source_dir/'corrected.png'))
    if source is None or valid is None or full is None or valid.shape != full.shape[:2]:
        raise AlignmentUnavailable('missing_or_mismatched_previous_images')
    if list(source.shape[1::-1]) != row['size']:
        raise AlignmentUnavailable('source_size_mismatch')
    plan = uniform_plan(pose, config)
    A = np.asarray(plan['H_corrected_to_aligned']); H = np.asarray(row['H_source_to_output'])
    bounds = expanded_envelope(source_dir, row, pose)
    rect = content_rectangle(bounds, A, config.width, config.height)
    x1, y1, x2, y2 = rect
    selected = sorted({j for pair in pose['selected_pairs'] for j in pair})
    points = project(np.asarray(pose['keypoints_corrected'])[selected], A)
    if ((points < [x1, y1]) | (points > [x2-1, y2-1])).any():
        raise AlignmentUnavailable('shoulder_or_hip_outside_preserved_content')
    # The saved corrected mask must also support every retained output pixel.
    corrected_safe = cv2.warpPerspective(valid, A, (config.width, config.height), flags=cv2.INTER_NEAREST)
    if not (corrected_safe[y1:y2, x1:x2] == 255).all():
        raise AlignmentUnavailable('content_rectangle_outside_saved_valid_mask')
    source_valid, _ = content_mask(source)
    image, used = compose(source, source_valid, A@H, rect, config)
    anchor = project([pose['anchor']], A)[0]
    torso = pose['torso_length']*plan['uniform_scale']
    if np.linalg.norm(anchor-plan['shoulder_target_xy']) > 1e-5 or abs(torso-plan['torso_target_pixels']) > 1e-5:
        raise AlignmentUnavailable('fixed_subject_scale_geometry_failed')
    overlay = annotate(full, pose)
    bx1, by1, bx2, by2 = np.round(plan['bounds_xyxy']).astype(int)
    cv2.rectangle(overlay, (bx1, by1), (bx2, by2), (70, 180, 70), 3)
    outputs = {'aligned.png': image, 'content_mask.png': used,
               'alignment_guide.jpg': annotate(image, pose, A, anchor[1]), 'pose_overlay.jpg': overlay}
    for name, pixels in outputs.items():
        if not cv2.imwrite(str(out/name), pixels):
            raise AlignmentUnavailable('cannot_write_'+name)
    fraction = float((used > 0).mean())
    return {**plan, 'H_source_to_aligned': (A@H).tolist(),
            'shoulder_output_xy': anchor.tolist(), 'torso_output_pixels': float(torso),
            'source_window_corrected_xyxy': bounds, 'content_bounds_output_xyxy': rect,
            'padding_ltrb_pixels': [x1, y1, config.width-x2, config.height-y2],
            'source_content_fraction': fraction, 'padding_fraction': 1-fraction,
            'retained_source_valid_fraction': 1., 'scale_increased_to_fill': False}


def previews(out, previous, groups, config):
    from PIL import Image, ImageDraw, ImageFont
    font_path = Path('/root/autodl-fs/case-studio/fonts/NotoSansSC.ttf')
    font = ImageFont.truetype(str(font_path), 18) if font_path.exists() else ImageFont.load_default()
    contact = []
    for g in groups:
        ids = g['output_ids']
        if not ids:
            continue
        w = 210; h = round(w*config.height/config.width); slot = w+16
        sheet = Image.new('RGB', (slot*len(ids), 2*h+120), '#ffffff')
        d = ImageDraw.Draw(sheet)
        for row_index, root in enumerate((previous, out)):
            y = row_index*(h+60)
            label = '旧版：各组分别缩放' if row_index == 0 else f'新版：统一肩髋比例 {config.torso_fraction:.0%}'
            d.text((8, y+5), label+' / '+g['member'], font=font, fill='#26352c')
            for j, aid in enumerate(ids):
                path = root/aid/'aligned.png'
                if not path.exists():
                    continue
                im = Image.open(path).convert('RGB'); im.thumbnail((w, h), Image.Resampling.LANCZOS)
                sheet.paste(im, (j*slot+8, y+55)); d.text((j*slot+8, y+30), aid, fill='#26352c')
        folder = out/'groups'/g['group_id']; folder.mkdir(parents=True, exist_ok=True)
        sheet.save(folder/'uniform_comparison.jpg', quality=94)
        strip = Image.new('RGB', (slot*len(ids), h+60), '#ffffff')
        d = ImageDraw.Draw(strip); d.text((8, 5), g['store']+' / '+g['member'], font=font, fill='#26352c')
        for j, aid in enumerate(ids):
            im = Image.open(out/aid/'aligned.png').convert('RGB').resize((w, h), Image.Resampling.LANCZOS)
            strip.paste(im, (j*slot+8, 55)); d.text((j*slot+8, 30), aid, fill='#26352c')
        strip.save(folder/'clean_group.jpg', quality=94); contact.append(strip)
    if contact:
        sheet = Image.new('RGB', (max(p.width for p in contact), sum(p.height for p in contact)), '#ffffff')
        y = 0
        for strip in contact:
            sheet.paste(strip, (0, y)); y += strip.height
        sheet.save(out/'uniform_contact_sheet.jpg', quality=94)


def run(poses, rectified, previous, out, config):
    if any(out.resolve().is_relative_to(p.resolve()) for p in (poses, rectified, previous)):
        raise AlignmentUnavailable('output_must_be_separate_from_previous_experiments')
    old_rows = json.loads((poses/'summary.json').read_text())
    old_groups = json.loads((poses/'groups.json').read_text())
    base = {r['asset_id']: r for r in json.loads((rectified/'summary.json').read_text())}
    ids = [r['asset_id'] for r in old_rows]
    if len(set(ids)) != len(ids) or any(not re.fullmatch(r'[A-Za-z0-9_-]+', aid) for aid in ids):
        raise AlignmentUnavailable('invalid_or_duplicate_asset_ids')
    out.mkdir(parents=True, exist_ok=False)
    save_json(out/'config.json', asdict(config))
    records = {}
    for old in old_rows:
        aid = old['asset_id']; dest = out/aid; dest.mkdir()
        r = {'asset_id': aid, 'method': 'global-shoulder-scale-v3', 'status': old['status'],
             'pose_source_report': str(poses/aid/'report.json'), 'new_pose_inferences': 0, 'new_api_requests': 0}
        if old['status'] in ('aligned', 'standardized_single'):
            r['status'] = 'needs_review'
            try:
                row = base[aid]
                if not np.allclose(old['frame']['H_source_to_aligned'],
                                   np.asarray(old['frame']['H_corrected_to_aligned'])@np.asarray(row['H_source_to_output'])):
                    raise AlignmentUnavailable('previous_and_rectified_geometry_mismatch')
                pose = old['pose_localization']['pose']
                frame = render(rectified/aid, dest, row, pose, config)
                r.update(status='uniform', pose=pose, frame=frame, presentation_file='aligned.png')
            except (ValueError, KeyError) as error:
                r['reason'] = str(error)
        elif old.get('reason'):
            r['reason'] = old['reason']
        records[aid] = r
        print(aid, r['status'], r.get('reason', ''), flush=True)
    groups = []
    for old in old_groups:
        g = {k: old[k] for k in ('group_id', 'store', 'member', 'requested_asset_ids')}
        accepted = [aid for aid in g['requested_asset_ids'] if records[aid]['status'] == 'uniform']
        g.update(output_ids=accepted, excluded_asset_ids=[aid for aid in g['requested_asset_ids'] if aid not in accepted],
                 output_size=[config.width, config.height], torso_target_pixels=config.height*config.torso_fraction,
                 torso_fraction=config.torso_fraction,
                 shoulder_target_xy=[config.width/2-.5, config.height*config.shoulder_y-.5],
                 singleton=len(g['requested_asset_ids']) == 1)
        g['complete'] = not g['excluded_asset_ids']
        g['status'] = 'complete' if g['complete'] else ('partial' if accepted else 'needs_review')
        for aid in accepted:
            records[aid].update(group_id=g['group_id'], store=g['store'], member=g['member'])
        groups.append(g)
    for r in records.values():
        save_json(out/r['asset_id']/'report.json', r)
    save_json(out/'summary.json', list(records.values())); save_json(out/'groups.json', groups)
    group_previews(out, groups)
    previews(out, previous, groups, config)
    print(dict(Counter(r['status'] for r in records.values())), flush=True)
    return list(records.values()), groups


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('poses', 'rectified', 'previous', 'out'):
        parser.add_argument('--'+name, type=Path, required=True)
    parser.add_argument('--width', type=int, default=768)
    parser.add_argument('--height', type=int, default=1792)
    parser.add_argument('--torso-fraction', type=float, default=.27)
    parser.add_argument('--shoulder-y', type=float, default=.23)
    parser.add_argument('--background', type=int, nargs=3, metavar=('R', 'G', 'B'), default=(238, 234, 227))
    args = parser.parse_args(); cv2.setNumThreads(4)
    config = UniformConfig(args.width, args.height, args.torso_fraction, args.shoulder_y, tuple(args.background))
    run(args.poses, args.rectified, args.previous, args.out, config)


if __name__ == '__main__':
    main()

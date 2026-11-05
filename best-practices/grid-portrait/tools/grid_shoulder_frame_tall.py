"""Leg-priority, taller framing of an already shoulder-aligned experiment.

Read-only reuse of v1 poses/calibration. Extend into real pixels below the grid,
keep the previous upper framing, and solve the taller frame for the whole group.
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
from grid_shoulder_frame import group_previews, render, save_json
from grid_standard_frame import corners
from shoulder_alignment import AlignmentUnavailable


@dataclass(frozen=True)
class TallConfig:
    width: int = 768
    height: int = 1792
    max_torso_fraction: float = .75

    def __post_init__(self):
        if not (64 <= self.width <= 4096 and 64 <= self.height <= 4096):
            raise AlignmentUnavailable('invalid_output_size')
        if not .3 <= self.width/self.height <= 1.:
            raise AlignmentUnavailable('invalid_portrait_aspect')
        if not 0 < self.max_torso_fraction <= 1:
            raise AlignmentUnavailable('invalid_max_torso_fraction')


def extend_vertical_bounds(safe, old_bounds, anchor):
    """Expand along the grid's horizontal corridor, across valid floor if present.

    No color-based floor generation or extrapolation. A row must be valid over
    the entire corridor, and only the connected run containing the shoulder is
    allowed, so black bars, holes and warped edges remain outside the frame.
    """
    x1, _, x2, _ = np.asarray(old_bounds, int)
    y = int(round(anchor[1]))
    if x1 < 0 or x2 > safe.shape[1] or x2 <= x1 or not 0 <= y < safe.shape[0]:
        raise AlignmentUnavailable('invalid_grid_corridor')
    rows = safe[:, x1:x2].all(axis=1)
    if not rows[y]:
        raise AlignmentUnavailable('shoulder_corridor_not_valid')
    before = np.flatnonzero(~rows[:y])
    after = np.flatnonzero(~rows[y:])
    top = int(before[-1]+1) if len(before) else 0
    bottom = int(y+after[0]) if len(after) else len(rows)
    return [int(x1), top, int(x2), bottom]


def expanded_envelope(source_dir, row, pose):
    original = cv2.imread(str(source_dir/'original.png'))
    valid = cv2.imread(str(source_dir/'valid_mask.png'), 0)
    if original is None or valid is None:
        raise AlignmentUnavailable('missing_saved_source_or_mask')
    content, _ = content_mask(original)
    warped = cv2.warpPerspective(content, np.asarray(row['H_source_to_output']),
                                 (valid.shape[1], valid.shape[0]), flags=cv2.INTER_NEAREST)
    safe = cv2.erode(((valid > 0) & (warped > 0)).astype(np.uint8), np.ones((9, 9), np.uint8),
                     borderType=cv2.BORDER_CONSTANT, borderValue=0) > 0
    return extend_vertical_bounds(safe, row['crop']['bounds_xyxy'], pose['anchor'])


def plan_taller_group(items, previous_group, config):
    """Preserve prior upper content; spend extra available height on the legs.

    Same shoulder X/Y and torso size within a group. Single-image groups keep
    their previous horizontal composition instead of forcing shoulder centering.
    """
    if not items:
        raise AlignmentUnavailable('no_reusable_aligned_images')
    old_width, old_height = previous_group['output_size']
    if config.height/config.width < old_height/old_width-1e-9:
        raise AlignmentUnavailable('new_frame_must_not_be_shorter_in_aspect')
    target_x = (previous_group['shoulder_target_xy'][0]+.5)*config.width/old_width
    reference_torso = previous_group['torso_target_pixels']*config.width/old_width
    supports = []
    for item in items:
        x, y = np.asarray(item['pose']['anchor'])+.5
        length = item['pose']['torso_length']
        if not np.isfinite(length) or length <= 0:
            raise AlignmentUnavailable('invalid_torso_length')
        x1, y1, x2, y2 = item['bounds']
        support = np.array([x-x1, x2-x, y-y1, y2-y])/length
        if not np.isfinite(support).all() or (support <= 0).any():
            raise AlignmentUnavailable('shoulder_outside_extended_valid_frame')
        supports.append(support)
    left, right, above, below = np.min(supports, axis=0)
    torso = max(reference_torso, target_x/left, (config.width-target_x)/right,
                config.height/(above+below))*(1+1e-8)
    if torso > config.height*config.max_torso_fraction:
        raise AlignmentUnavailable('taller_frame_requires_excessive_zoom')
    low = max(0., config.height-torso*below)
    high = min(float(config.height), torso*above)
    # Keep every photo's previously retained upper edge. Head/hair is not used
    # as a scale reference; this protects existing content while favoring legs.
    keep_upper = max((i['pose']['anchor'][1]+.5-i['previous_bounds'][1]) * torso/i['pose']['torso_length'] for i in items)
    target_y = max(low, keep_upper)
    if target_y > high+1e-5:
        raise AlignmentUnavailable('cannot_keep_previous_upper_content')
    target_y = min(target_y, high)
    plans = {}
    for item in items:
        sx, sy = item['pose']['anchor']; scale = torso/item['pose']['torso_length']
        x1, y1 = sx+.5-target_x/scale, sy+.5-target_y/scale
        rect = [x1, y1, x1+config.width/scale, y1+config.height/scale]
        old = item['previous_bounds']
        if rect[1] > old[1]+1e-4 or rect[3] < old[3]-1e-4:
            raise AlignmentUnavailable('vertical_content_would_regress')
        A = np.array([[scale, 0., target_x-.5-scale*sx],
                      [0., scale, target_y-.5-scale*sy], [0., 0., 1.]])
        plans[item['asset_id']] = {'bounds_xyxy': rect, 'uniform_scale': float(scale),
                                  'H_corrected_to_aligned': A.tolist(),
                                  'previous_bounds_xyxy': old, 'extended_valid_bounds_xyxy': item['bounds'],
                                  'extra_below_corrected_px': max(0., rect[3]-old[3]),
                                  'extra_above_corrected_px': max(0., old[1]-rect[1])}
    return {'output_size': [config.width, config.height], 'mode': 'taller_shared_shoulder_frame',
            'shoulder_target_xy': [target_x-.5, target_y-.5], 'torso_target_pixels': float(torso),
            'previous_torso_target_pixels': previous_group['torso_target_pixels'],
            'plans': plans, 'singleton': len(items) == 1,
            'warnings': ['scale_increased_to_fit_available_source'] if torso > reference_torso*1.02 else []}


def leg_metrics(row, pose, rect):
    polygon = project(corners(row['subject_box']), np.asarray(row['H_source_to_output']))
    hip = pose['hip_anchor'][1]
    bottom = float(polygon[:, 1].max())
    span = max(1., bottom-hip)
    kept = max(0., min(bottom, rect[3])-max(hip, rect[1]))
    return {'visible_lower_body_vertical_retention': min(1., kept/span),
            'visible_subject_bottom_corrected_y': bottom,
            'bottom_margin_to_subject_px': float(rect[3]-bottom)}


def comparisons(out, previous, groups):
    from PIL import Image, ImageDraw
    for g in groups:
        ids = g['output_ids']
        if not ids:
            continue
        pairs = []
        for aid in ids:
            ims = [Image.open(root/aid/'aligned.png').convert('RGB') for root in (previous, out)]
            ims = [im.resize((240, round(im.height*240/im.width)), Image.Resampling.LANCZOS) for im in ims]
            pairs.append(ims)
        old_h = max(p[0].height for p in pairs); new_h = max(p[1].height for p in pairs)
        canvas = Image.new('RGB', (260*len(ids), old_h+new_h+110), '#eeeae3')
        draw = ImageDraw.Draw(canvas)
        draw.text((12, 10), g['group_id']+' PREVIOUS SHOULDER FRAME / SAME DISPLAY WIDTH', fill='#26352c')
        draw.text((12, old_h+65), 'TALLER FRAME / MORE LOWER-BODY CONTENT', fill='#26352c')
        for i, (aid, pair) in enumerate(zip(ids, pairs)):
            draw.text((i*260+10, 28), aid, fill='#26352c')
            canvas.paste(pair[0], (i*260+10, 45))
            canvas.paste(pair[1], (i*260+10, old_h+95))
        folder = out/'groups'/g['group_id']; folder.mkdir(parents=True, exist_ok=True)
        canvas.save(folder/'taller_comparison.jpg', quality=94)


def run(previous, rectified, out, config):
    if any(out.resolve().is_relative_to(p.resolve()) for p in (previous, rectified)):
        raise AlignmentUnavailable('output_must_be_separate_from_previous_experiments')
    old_rows = json.loads((previous/'summary.json').read_text())
    old_groups = json.loads((previous/'groups.json').read_text())
    base = {r['asset_id']: r for r in json.loads((rectified/'summary.json').read_text())}
    ids = [r['asset_id'] for r in old_rows]
    if any(not re.fullmatch(r'[A-Za-z0-9_-]+', aid) for aid in ids) or len(set(ids)) != len(ids):
        raise AlignmentUnavailable('invalid_or_duplicate_asset_ids')
    out.mkdir(parents=True, exist_ok=False)
    save_json(out/'config.json', asdict(config))
    originals = {r['asset_id']: r for r in old_rows}
    records = {}
    for old in old_rows:
        aid = old['asset_id']; (out/aid).mkdir()
        records[aid] = {'asset_id': aid, 'method': 'shoulder-frame-tall-v2',
                        'status': 'needs_review' if old['status'] in ('aligned', 'standardized_single') else old['status'],
                        'pose_source_report': str(previous/aid/'report.json'), 'new_pose_inferences': 0, 'new_api_requests': 0}
        if old.get('reason'):
            records[aid]['reason'] = old['reason']
    groups = []
    for old_group in old_groups:
        g = {k: old_group[k] for k in ('group_id', 'store', 'member', 'requested_asset_ids')}
        g.update(output_ids=[], aligned_ids=[], excluded_asset_ids=[])
        items = []
        for aid in old_group['output_ids']:
            try:
                old = originals[aid]; row = base[aid]
                H = np.asarray(row['H_source_to_output'])
                if not np.allclose(old['frame']['H_source_to_aligned'], np.asarray(old['frame']['H_corrected_to_aligned']) @ H):
                    raise AlignmentUnavailable('previous_and_rectified_geometry_mismatch')
                pose = old['pose_localization']['pose']
                bounds = expanded_envelope(rectified/aid, row, pose)
                items.append({'asset_id': aid, 'pose': pose, 'bounds': bounds,
                              'previous_bounds': old['frame']['bounds_xyxy']})
            except (ValueError, KeyError) as error:
                records[aid]['reason'] = str(error)
        try:
            target = plan_taller_group(items, old_group, config)
            g.update(target)
            g['singleton'] = len(old_group['requested_asset_ids']) == 1
            for item in items:
                aid = item['asset_id']; row = base[aid]
                try:
                    before = leg_metrics(row, item['pose'], item['previous_bounds'])
                    after = leg_metrics(row, item['pose'], target['plans'][aid]['bounds_xyxy'])
                    if after['visible_lower_body_vertical_retention'] < before['visible_lower_body_vertical_retention']-1e-6:
                        raise AlignmentUnavailable('lower_body_vertical_retention_regressed')
                    frame = render(rectified/aid, out/aid, row, item['pose'], target['plans'][aid], config, target)
                    records[aid].update(status='tall_aligned' if len(old_group['requested_asset_ids']) > 1 else 'tall_single',
                                        group_id=g['group_id'], pose=item['pose'], frame=frame,
                                        lower_body_before=before, lower_body_after=after, presentation_file='aligned.png')
                    g['output_ids'].append(aid)
                    if len(old_group['requested_asset_ids']) > 1:
                        g['aligned_ids'].append(aid)
                except ValueError as error:
                    records[aid]['reason'] = str(error)
        except ValueError as error:
            g['reason'] = str(error)
            for item in items:
                records[item['asset_id']]['reason'] = str(error)
        g['excluded_asset_ids'] = [aid for aid in g['requested_asset_ids'] if aid not in g['output_ids']]
        g['complete'] = not g['excluded_asset_ids']
        g['status'] = 'complete' if g['complete'] else ('partial' if g['output_ids'] else 'needs_review')
        groups.append(g)
    for r in records.values():
        save_json(out/r['asset_id']/'report.json', r)
        print(r['asset_id'], r['status'], r.get('reason', ''), flush=True)
    save_json(out/'summary.json', list(records.values())); save_json(out/'groups.json', groups)
    group_previews(out, groups)
    comparisons(out, previous, groups)
    print(dict(Counter(r['status'] for r in records.values())), flush=True)
    return list(records.values()), groups


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--previous', type=Path, required=True)
    parser.add_argument('--rectified', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--width', type=int, default=768)
    parser.add_argument('--height', type=int, default=1792)
    args = parser.parse_args(); cv2.setNumThreads(4)
    run(args.previous, args.rectified, args.out, TallConfig(args.width, args.height))


if __name__ == '__main__':
    main()

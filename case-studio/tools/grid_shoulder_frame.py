"""Independent group alignment: shoulder anchor + torso scale -> standard frame.

Uses the saved v2.3 rectification and job member metadata. Earlier scripts and
outputs remain read-only. See 14-同名会员肩部对齐.md for scope and limitations.
"""
import argparse
import json
import re
from collections import Counter, defaultdict
from dataclasses import asdict
from pathlib import Path

import cv2
import numpy as np

from grid_crop import content_mask, project
from grid_rectify_single import eligibility
from grid_standard_frame import FrameConfig, corners, polygon_fraction, select_frame
from shoulder_alignment import AlignmentUnavailable, GroupConfig, group_plan, member_key
from shoulder_pose import ShoulderPose


def save_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2))


def single_plan(row, pose, config):
    """One photo has no within-member comparison: retain the v1 standard frame."""
    rect, A, old = select_frame(row['crop']['bounds_xyxy'], row['subject_box'], row['H_source_to_output'],
                                FrameConfig(config.width, config.height))
    aid = row['asset_id']
    return {'mode': 'single_standard_frame', 'singleton': True, 'image_count': 1,
            'output_size': [config.width, config.height],
            'shoulder_target_xy': project([pose['anchor']], A)[0].tolist(),
            'torso_target_pixels': pose['torso_length']*old['uniform_scale'],
            'warnings': ['single_image_no_group_alignment'],
            'plans': {aid: {'bounds_xyxy': rect, 'uniform_scale': old['uniform_scale'],
                           'H_corrected_to_aligned': A.tolist()}}}


def annotate(image, pose, matrix=None, target_y=None):
    result = image.copy()
    points = np.asarray(pose['keypoints_corrected'])
    anchor = np.asarray(pose['anchor'])
    if matrix is not None:
        points = project(points, matrix)
        anchor = project([anchor], matrix)[0]
    for s, h in pose['selected_pairs']:
        a, b = tuple(np.round(points[s]).astype(int)), tuple(np.round(points[h]).astype(int))
        cv2.line(result, a, b, (220, 140, 20), 3, cv2.LINE_AA)
        cv2.circle(result, a, 9, (30, 70, 240), -1, cv2.LINE_AA)
        cv2.circle(result, b, 8, (70, 180, 70), -1, cv2.LINE_AA)
    if target_y is not None:
        y = int(round(target_y))
        cv2.line(result, (0, y), (image.shape[1]-1, y), (200, 190, 20), 2, cv2.LINE_AA)
    cv2.drawMarker(result, tuple(np.round(anchor).astype(int)), (0, 220, 255), cv2.MARKER_CROSS, 24, 4)
    return result


def render(source_dir, out, row, pose, plan, config, target):
    source = cv2.imread(str(source_dir/'original.png'))
    valid = cv2.imread(str(source_dir/'valid_mask.png'), 0)
    full = cv2.imread(str(source_dir/'corrected.png'))
    if source is None or valid is None or full is None or valid.shape != full.shape[:2]:
        raise AlignmentUnavailable('missing_or_mismatched_previous_images')
    if list(source.shape[1::-1]) != row['size']:
        raise AlignmentUnavailable('source_size_mismatch')
    H = np.asarray(row['H_source_to_output'])
    A = np.asarray(plan['H_corrected_to_aligned'])
    content, _ = content_mask(source)
    warped_content = cv2.warpPerspective(content, H, (full.shape[1], full.shape[0]), flags=cv2.INTER_NEAREST)
    safe = cv2.erode(((valid > 0) & (warped_content > 0)).astype(np.uint8), np.ones((9, 9), np.uint8),
                     borderType=cv2.BORDER_CONSTANT, borderValue=0)
    x1, y1 = np.floor(np.array(plan['bounds_xyxy'][:2])+1e-7).astype(int)
    x2, y2 = np.ceil(np.array(plan['bounds_xyxy'][2:])-1e-7).astype(int)
    if x1 < 0 or y1 < 0 or x2 > safe.shape[1] or y2 > safe.shape[0] or not safe[y1:y2, x1:x2].all():
        raise AlignmentUnavailable('shared_frame_contains_invalid_pixels')
    output_H = A @ H
    size = (config.width, config.height)
    output_valid = cv2.warpPerspective(content, output_H, size, flags=cv2.INTER_NEAREST)
    if not (output_valid == 255).all():
        raise AlignmentUnavailable('output_contains_invalid_pixels')
    aligned = cv2.warpPerspective(source, output_H, size, flags=cv2.INTER_CUBIC,
                                  borderMode=cv2.BORDER_CONSTANT, borderValue=(242, 242, 242))
    anchor = project([pose['anchor']], A)[0]
    measured_length = pose['torso_length']*plan['uniform_scale']
    if np.linalg.norm(anchor-target['shoulder_target_xy']) > 1e-5:
        raise AlignmentUnavailable('shoulder_alignment_geometry_failed')
    if abs(measured_length-target['torso_target_pixels']) > 1e-5:
        raise AlignmentUnavailable('torso_scale_geometry_failed')
    if not cv2.imwrite(str(out/'aligned.png'), aligned):
        raise AlignmentUnavailable('cannot_write_aligned_image')
    cv2.imwrite(str(out/'alignment_guide.jpg'), annotate(aligned, pose, A, anchor[1]))
    overlay = annotate(full, pose)
    cv2.rectangle(overlay, (x1, y1), (x2-1, y2-1), (70, 180, 70), 3)
    cv2.imwrite(str(out/'pose_overlay.jpg'), overlay)
    return {**plan, 'H_source_to_aligned': output_H.tolist(), 'shoulder_output_xy': anchor.tolist(),
            'torso_output_pixels': float(measured_length), 'valid_fraction': 1.,
            'subject_box_retained_fraction': polygon_fraction(project(corners(row['subject_box']), H), plan['bounds_xyxy'])}


def group_previews(out, groups, previous=None):
    from PIL import Image, ImageDraw, ImageFont
    font = ImageFont.load_default()
    for candidate in ('/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc',
                      '/root/autodl-fs/case-studio/fonts/NotoSansSC.ttf',
                      '/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc'):
        if Path(candidate).exists():
            font = ImageFont.truetype(candidate, 20)
            break
    overview = []
    for g in groups:
        ids = g['output_ids']
        if not ids:
            continue
        folder = out/'groups'/g['group_id']
        folder.mkdir(parents=True, exist_ok=True)
        strip = Image.new('RGB', (260*len(ids), 490), '#eeeae3')
        d = ImageDraw.Draw(strip)
        d.text((12, 5), g['store']+' / '+g['member'], fill='#26352c', font=font)
        for i, aid in enumerate(ids):
            im = Image.open(out/aid/'alignment_guide.jpg').convert('RGB')
            im.thumbnail((240, 400), Image.Resampling.LANCZOS)
            d.text((i*260+12, 40), aid, fill='#26352c')
            strip.paste(im, (i*260+(260-im.width)//2, 65))
        strip.save(folder/'aligned_group.jpg', quality=94)
        if previous and all((previous/aid/'standardized.png').exists() for aid in ids):
            comparison = Image.new('RGB', (strip.width, 980), '#eeeae3')
            draw = ImageDraw.Draw(comparison)
            draw.text((12, 8), 'PREVIOUS STANDARD FRAME', fill='#26352c')
            for i, aid in enumerate(ids):
                im = Image.open(previous/aid/'standardized.png').convert('RGB')
                im.thumbnail((240, 400), Image.Resampling.LANCZOS)
                draw.text((i*260+12, 40), aid, fill='#26352c')
                comparison.paste(im, (i*260+(260-im.width)//2, 65))
            comparison.paste(strip, (0, 490))
            comparison.save(folder/'comparison.jpg', quality=94)
        overview.append(strip)
    if overview:
        contact = Image.new('RGB', (max(im.width for im in overview), sum(im.height for im in overview)), '#eeeae3')
        y = 0
        for im in overview:
            contact.paste(im, (0, y))
            y += im.height
        contact.save(out/'shoulder_groups_contact_sheet.jpg', quality=94)


def run(input_dir, job_path, out, config, weights, cache_dir, previous=None):
    if out.resolve().is_relative_to(input_dir.resolve()) or (previous and out.resolve().is_relative_to(previous.resolve())):
        raise AlignmentUnavailable('output_must_be_separate_from_previous_experiments')
    rows = json.loads((input_dir/'summary.json').read_text())
    assets = {a['id']: a for a in json.loads(job_path.read_text())['assets']}
    if any(not re.fullmatch(r'[A-Za-z0-9_-]+', r['asset_id']) for r in rows) or len({r['asset_id'] for r in rows}) != len(rows):
        raise AlignmentUnavailable('invalid_or_duplicate_asset_ids')
    out.mkdir(parents=True, exist_ok=False)
    save_json(out/'config.json', asdict(config))
    records, members, requested = {}, defaultdict(list), defaultdict(list)
    detector = None
    source_rows = {r['asset_id']: r for r in rows}
    for row in rows:
        aid = row['asset_id']; destination = out/aid
        destination.mkdir()
        r = {'asset_id': aid, 'method': 'group-shoulder-torso-frame-v1', 'status': 'needs_review', 'new_api_requests': 0}
        records[aid] = r
        asset = assets.get(aid, {})
        reason = eligibility(row.get('classification')) or eligibility(asset.get('class'))
        if reason:
            r.update(status='skipped', reason=reason)
        elif row.get('status') != 'corrected' or row.get('crop', {}).get('status') != 'cropped':
            r['reason'] = 'requires_accepted_grid_rectification_and_crop'
        else:
            try:
                key = member_key(asset)
                if Path(row['source']).resolve() != (job_path.parent/'input'/asset['path']).resolve():
                    raise AlignmentUnavailable('job_asset_does_not_match_saved_source')
                r.update(store=key[0], member=key[1])
                requested[key].append(aid)
                original = cv2.imread(str(input_dir/aid/'original.png'))
                if original is None:
                    raise AlignmentUnavailable('missing_saved_original')
                if detector is None:
                    detector = ShoulderPose(weights, cache_dir)
                localization = detector.locate(original, row['subject_box'], row['H_source_to_output'], row['classification'].get('view'))
                r.update(store=key[0], member=key[1], pose_localization=localization, status='pose_ready')
                members[key].append({'asset_id': aid, 'pose': localization['pose'], 'bounds': row['crop']['bounds_xyxy']})
            except (ValueError, KeyError) as error:
                r['reason'] = str(error)
                if hasattr(error, 'attempts'):
                    r['pose_attempts'] = error.attempts
        save_json(destination/'report.json', r)
        print(aid, r['status'], r.get('reason', ''), flush=True)
    groups = []
    for index, key in enumerate(sorted(requested), 1):
        items = members[key]
        g = {'group_id': f'g{index:03}', 'store': key[0], 'member': key[1],
             'requested_asset_ids': requested[key], 'asset_ids': [i['asset_id'] for i in items],
             'aligned_ids': [], 'output_ids': [],
             'excluded_asset_ids': [aid for aid in requested[key] if aid not in {i['asset_id'] for i in items}]}
        try:
            singleton = len(requested[key]) == 1 and len(items) == 1
            target = (single_plan(source_rows[items[0]['asset_id']], items[0]['pose'], config)
                      if singleton else group_plan(items, config))
            g.update(target)
            g['singleton'] = len(requested[key]) == 1
            for item in items:
                aid = item['asset_id']; r = records[aid]
                try:
                    frame = render(input_dir/aid, out/aid, source_rows[aid], item['pose'], target['plans'][aid], config, target)
                    r.update(status='standardized_single' if singleton else 'aligned', group_id=g['group_id'],
                             frame=frame, presentation_file='aligned.png')
                    g['output_ids'].append(aid)
                    if not singleton:
                        g['aligned_ids'].append(aid)
                except ValueError as error:
                    r.update(status='needs_review', reason=str(error))
        except ValueError as error:
            g['reason'] = str(error)
            for item in items:
                records[item['asset_id']].update(status='needs_review', reason=str(error))
        g['complete'] = len(g['output_ids']) == len(g['requested_asset_ids'])
        g['status'] = ('standardized_single' if g.get('mode') == 'single_standard_frame' else 'aligned') if g['complete'] else ('partial' if g['output_ids'] else 'needs_review')
        groups.append(g)
    result = list(records.values())
    for r in result:
        save_json(out/r['asset_id']/'report.json', r)
    save_json(out/'summary.json', result)
    save_json(out/'groups.json', groups)
    group_previews(out, groups, previous)
    print(dict(Counter(r['status'] for r in result)), flush=True)
    return result, groups


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True, help='Saved v2.3 rectification directory')
    parser.add_argument('--job', type=Path, required=True, help='Matching job.json for store/member grouping')
    parser.add_argument('--out', type=Path, required=True, help='New output directory')
    parser.add_argument('--previous-standard', type=Path, help='Optional previous standard frames for comparison previews')
    parser.add_argument('--weights', type=Path, default='/root/autodl-fs/portrait-studio/models/yolo11m-pose.pt')
    parser.add_argument('--pose-cache', type=Path, default='/root/autodl-fs/case-studio/cache/shoulder-pose')
    parser.add_argument('--width', type=int, default=768)
    parser.add_argument('--height', type=int, default=1280)
    parser.add_argument('--shoulder-y', type=float, help='Optional normalized target; default preserves upper content jointly')
    parser.add_argument('--torso-fraction', type=float, default=.36)
    args = parser.parse_args()
    cv2.setNumThreads(4)
    config = GroupConfig(args.width, args.height, args.shoulder_y, args.torso_fraction)
    run(args.input, args.job, args.out, config, args.weights, args.pose_cache, args.previous_standard)


if __name__ == '__main__':
    main()

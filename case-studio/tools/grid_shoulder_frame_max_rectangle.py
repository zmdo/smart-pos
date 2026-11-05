"""Maximum axis-aligned real-photo rectangle inside a uniform portrait frame.

The saved full-source image is already corrected and scaled. Select pixels only;
keep the canvas, shoulders and subject scale unchanged. Do not warp again.
"""
import argparse
import json
import re
from collections import Counter
from pathlib import Path

import cv2
import numpy as np

from grid_crop import project
from grid_shoulder_frame import annotate, group_previews, save_json
from grid_shoulder_frame_uniform import UniformConfig
from shoulder_alignment import AlignmentUnavailable


def contains(outer, inner):
    return outer[0] <= inner[0] and outer[1] <= inner[1] and outer[2] >= inner[2] and outer[3] >= inner[3]


def largest_valid_rectangle(mask, required=None):
    """Exact largest all-valid pixel rectangle via O(height*width) histograms.

    Optional required bounds must be wholly contained. Maximal histogram spans
    dominate their subrectangles, including under this containment constraint.
    Equal-area solutions prefer more height, then more lower content, then left.
    """
    valid = np.asarray(mask) > 0
    if valid.ndim != 2 or not valid.size:
        raise AlignmentUnavailable('invalid_available_mask')
    height, width = valid.shape
    if required is not None:
        if (len(required) != 4 or any(int(n) != n for n in required) or
                not (0 <= required[0] < required[2] <= width and 0 <= required[1] < required[3] <= height)):
            raise AlignmentUnavailable('invalid_required_rectangle')
        x1, y1, x2, y2 = map(int, required)
        if not valid[y1:y2, x1:x2].all():
            raise AlignmentUnavailable('required_rectangle_not_available')
    heights = np.zeros(width+1, np.int32)
    best, best_key = None, None
    for y in range(height):
        heights[:width] = np.where(valid[y], heights[:width]+1, 0)
        stack = []
        for x in range(width+1):
            current = int(heights[x]); start = x
            while stack and stack[-1][1] > current:
                left, h = stack.pop(); start = left
                rect = [left, y+1-h, x, y+1]
                if required is not None and not contains(rect, required):
                    continue
                key = ((x-left)*h, h, y+1, -left)
                if best_key is None or key > best_key:
                    best, best_key = rect, key
            if current and (not stack or stack[-1][1] < current):
                stack.append((start, current))
    if best is None:
        raise AlignmentUnavailable('no_valid_rectangle')
    return best, int(best_key[0])


def select_rectangle(available, required):
    unconstrained, global_area = largest_valid_rectangle(available)
    if contains(unconstrained, required):
        rect, selected_area = unconstrained, global_area
    else:
        rect, selected_area = largest_valid_rectangle(available, required)
    return rect, {'selected_rectangle_area': selected_area, 'unconstrained_maximum_area': global_area,
                  'is_unconstrained_global_maximum': selected_area == global_area,
                  'required_subject_bounds_xyxy': list(required)}


def rectangular_image(image, available, rect, background_rgb):
    x1, y1, x2, y2 = rect
    if (image.shape[:2] != available.shape or not (0 <= x1 < x2 <= image.shape[1] and 0 <= y1 < y2 <= image.shape[0]) or
            not (available[y1:y2, x1:x2] > 0).all()):
        raise AlignmentUnavailable('rectangle_contains_unavailable_pixels')
    output = np.empty_like(image); output[:] = background_rgb[::-1]
    output[y1:y2, x1:x2] = image[y1:y2, x1:x2]
    used = np.zeros(available.shape, np.uint8); used[y1:y2, x1:x2] = 255
    return output, used


def required_subject_rectangle(pose, A, config):
    selected = sorted({j for pair in pose['selected_pairs'] for j in pair})
    points = project(np.asarray(pose['keypoints_corrected'])[selected], A)
    bounds = [*np.floor(points.min(axis=0)).astype(int), *(np.ceil(points.max(axis=0)).astype(int)+1)]
    if not contains([0, 0, config.width, config.height], bounds):
        raise AlignmentUnavailable('shoulders_or_hips_outside_frame')
    return [int(n) for n in bounds]


def render(previous, out, old, config):
    image = cv2.imread(str(previous/'aligned.png'))
    available = cv2.imread(str(previous/'content_mask.png'), 0)
    if image is None or available is None:
        raise AlignmentUnavailable('missing_full_source_images')
    if image.shape != (config.height, config.width, 3) or available.shape != image.shape[:2] or not np.isin(available, [0, 255]).all():
        raise AlignmentUnavailable('invalid_full_source_images')
    pose = old['pose']; frame = old['frame']; A = np.array(frame['H_corrected_to_aligned'])
    anchor = project([pose['anchor']], A)[0]
    if (A[0, 0] <= 0 or not np.allclose(A[:2, :2], np.eye(2)*A[0, 0]) or not np.allclose(A[2], [0, 0, 1]) or
            abs(A[0, 0]*pose['torso_length']/config.height-config.torso_fraction) > 1e-9 or
            np.linalg.norm(anchor-[config.width/2-.5, config.height*config.shoulder_y-.5]) > 1e-5):
        raise AlignmentUnavailable('previous_uniform_geometry_mismatch')
    rect, metrics = select_rectangle(available, required_subject_rectangle(pose, A, config))
    output, used = rectangular_image(image, available, rect, config.background_rgb)
    x1, y1, x2, y2 = rect
    discarded = ((available > 0) & (used == 0)).astype(np.uint8)*255
    preview = image.copy(); cv2.rectangle(preview, (x1, y1), (x2-1, y2-1), (60, 190, 60), 3)
    outputs = {'aligned.png': output, 'content_mask.png': used, 'available_mask.png': available,
               'discarded_mask.png': discarded, 'rectangle_preview.jpg': preview,
               'alignment_guide.jpg': annotate(output, pose, A, anchor[1])}
    for name, pixels in outputs.items():
        if not cv2.imwrite(str(out/name), pixels):
            raise AlignmentUnavailable('cannot_write_'+name)
    result = {k: frame[k] for k in ('bounds_xyxy', 'uniform_scale', 'H_corrected_to_aligned', 'H_source_to_aligned',
              'shoulder_target_xy', 'torso_target_pixels', 'torso_fraction', 'shoulder_output_xy', 'torso_output_pixels')}
    result.update(coverage_shape='maximum_axis_aligned_rectangle', content_bounds_output_xyxy=rect,
                  padding_ltrb_pixels=[x1, y1, config.width-x2, config.height-y2],
                  available_source_pixels=int(np.count_nonzero(available)), discarded_available_pixels=int(np.count_nonzero(discarded)),
                  unavailable_source_pixels=int(np.count_nonzero(available == 0)),
                  source_content_fraction=float((used > 0).mean()), padding_fraction=float((used == 0).mean()),
                  retained_pixels_unchanged=True, additional_resampling=False, **metrics)
    return result


def previews(out, previous, groups, config):
    from PIL import Image, ImageDraw, ImageFont
    path = Path('/root/autodl-fs/case-studio/fonts/NotoSansSC.ttf')
    font = ImageFont.truetype(str(path), 18) if path.exists() else ImageFont.load_default()
    strips = []
    for g in groups:
        ids = g['output_ids']
        if not ids:
            continue
        width = 210; height = round(width*config.height/config.width); slot = width+16
        sheet = Image.new('RGB', (slot*len(ids), (height+60)*2), '#ffffff'); draw = ImageDraw.Draw(sheet)
        for index, root in enumerate((previous, out)):
            top = index*(height+60)
            draw.text((8, top+5), ('旧版 / ' if index == 0 else '新版 / ')+g['member'], font=font, fill='#26352c')
            for j, aid in enumerate(ids):
                im = Image.open(root/aid/'aligned.png').convert('RGB').resize((width, height), Image.Resampling.LANCZOS)
                sheet.paste(im, (j*slot+8, top+55)); draw.text((j*slot+8, top+32), aid, fill='#26352c')
        folder = out/'groups'/g['group_id']; folder.mkdir(parents=True, exist_ok=True)
        sheet.save(folder/'maximum_rectangle_comparison.jpg', quality=94)
        clean = sheet.crop((0, height+60, sheet.width, sheet.height))
        clean.save(folder/'clean_group.jpg', quality=94); strips.append(clean)
    if strips:
        sheet = Image.new('RGB', (max(im.width for im in strips), sum(im.height for im in strips)), '#ffffff')
        top = 0
        for im in strips:
            sheet.paste(im, (0, top)); top += im.height
        sheet.save(out/'maximum_rectangle_contact_sheet.jpg', quality=94)


def run(previous, out):
    if out.resolve().is_relative_to(previous.resolve()):
        raise AlignmentUnavailable('output_must_be_separate_from_previous_experiment')
    config_data = json.loads((previous/'config.json').read_text()); config = UniformConfig(**config_data)
    old_rows = json.loads((previous/'summary.json').read_text()); groups = json.loads((previous/'groups.json').read_text())
    ids = [r['asset_id'] for r in old_rows]
    if len(set(ids)) != len(ids) or any(not re.fullmatch(r'[A-Za-z0-9_-]+', aid) for aid in ids):
        raise AlignmentUnavailable('invalid_or_duplicate_asset_ids')
    if any(r.get('status') not in ('full_source', 'skipped', 'needs_review') for r in old_rows):
        raise AlignmentUnavailable('requires_full_source_v4_report')
    out.mkdir(parents=True, exist_ok=False); save_json(out/'config.json', config_data)
    records = {}
    for old in old_rows:
        aid = old['asset_id']; dest = out/aid; dest.mkdir()
        r = {k: old[k] for k in ('asset_id', 'status', 'group_id', 'store', 'member', 'reason') if k in old}
        r.update(method='uniform-maximum-rectangle-v5', previous_report=str(previous/aid/'report.json'),
                 new_pose_inferences=0, new_api_requests=0)
        if old['status'] == 'full_source':
            r['status'] = 'needs_review'
            try:
                frame = render(previous/aid, dest, old, config)
                r.update(status='rectangular', frame=frame, pose=old['pose'], presentation_file='aligned.png')
            except (ValueError, KeyError) as error:
                r['reason'] = str(error)
        records[aid] = r; save_json(dest/'report.json', r)
        print(aid, r['status'], r.get('reason', ''), flush=True)
    for g in groups:
        g['output_ids'] = [aid for aid in g['requested_asset_ids'] if records[aid]['status'] == 'rectangular']
        g['excluded_asset_ids'] = [aid for aid in g['requested_asset_ids'] if aid not in g['output_ids']]
        g['complete'] = not g['excluded_asset_ids']; g['status'] = 'complete' if g['complete'] else ('partial' if g['output_ids'] else 'needs_review')
    save_json(out/'summary.json', list(records.values())); save_json(out/'groups.json', groups)
    group_previews(out, groups); previews(out, previous, groups, config)
    print(dict(Counter(r['status'] for r in records.values())), flush=True)
    return list(records.values()), groups


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--previous', type=Path, required=True); parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args(); cv2.setNumThreads(4); run(args.previous, args.out)


if __name__ == '__main__':
    main()

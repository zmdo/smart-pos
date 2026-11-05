"""Use every available source pixel inside the approved uniform portrait frame.

Keep v3 geometry exactly. The canvas is rectangular; its real-photo footprint
need not be. Only original black bands and pixels outside the source stay blank.
"""
import argparse
import json
import re
from collections import Counter
from pathlib import Path

import cv2
import numpy as np

from grid_crop import content_mask, project
from grid_shoulder_frame import annotate, group_previews, save_json
from grid_shoulder_frame_uniform import UniformConfig
from shoulder_alignment import AlignmentUnavailable


def compose_full_source(source, H, config):
    """One resampling pass, using the entire source footprint, not an inset box.

    Extend boundary samples for cubic interpolation only. The separately warped
    mask always prevents those extrapolated pixels from filling missing areas.
    Original black letterbox bands are excluded, interior dark clothing is not.
    """
    source_mask, bounds = content_mask(source)
    x1, y1, x2, y2 = bounds
    crop = source[y1:y2, x1:x2]
    if crop.size == 0:
        raise AlignmentUnavailable('empty_original_content')
    sampling_source = cv2.copyMakeBorder(crop, y1, source.shape[0]-y2, x1, source.shape[1]-x2,
                                         cv2.BORDER_REPLICATE)
    size = (config.width, config.height)
    used = cv2.warpPerspective(source_mask, H, size, flags=cv2.INTER_NEAREST,
                               borderMode=cv2.BORDER_CONSTANT, borderValue=0)
    if not used.any():
        raise AlignmentUnavailable('source_outside_frame')
    sampled = cv2.warpPerspective(sampling_source, H, size, flags=cv2.INTER_CUBIC,
                                  borderMode=cv2.BORDER_REPLICATE)
    image = np.empty_like(sampled); image[:] = config.background_rgb[::-1]
    image[used > 0] = sampled[used > 0]
    original_footprint = cv2.warpPerspective(np.full(source.shape[:2], 255, np.uint8), H, size,
                                             flags=cv2.INTER_NEAREST)
    return image, used, {'source_content_bounds_xyxy': bounds,
                        'missing_outside_original_pixels': int(np.count_nonzero(original_footprint == 0)),
                        'missing_original_black_band_pixels': int(np.count_nonzero((original_footprint > 0) & (used == 0)))}


def coverage_gain(previous_used, used):
    if previous_used.shape != used.shape or not np.isin(previous_used, [0, 255]).all():
        raise AlignmentUnavailable('invalid_previous_content_mask')
    if ((previous_used > 0) & (used == 0)).any():
        raise AlignmentUnavailable('previous_real_content_would_be_lost')
    return ((used > 0) & (previous_used == 0)).astype(np.uint8)*255


def render(source_dir, previous_dir, out, row, old, config):
    source = cv2.imread(str(source_dir/'original.png'))
    previous_image = cv2.imread(str(previous_dir/'aligned.png'))
    previous_used = cv2.imread(str(previous_dir/'content_mask.png'), 0)
    if source is None or previous_image is None or previous_used is None:
        raise AlignmentUnavailable('missing_previous_images')
    shape = (config.height, config.width)
    if list(source.shape[1::-1]) != row['size'] or previous_image.shape[:2] != shape or previous_used.shape != shape:
        raise AlignmentUnavailable('source_or_previous_size_mismatch')
    old_frame = old['frame']; A = np.asarray(old_frame['H_corrected_to_aligned'])
    H = np.asarray(old_frame['H_source_to_aligned'])
    if not np.allclose(H, A@np.asarray(row['H_source_to_output']), rtol=1e-10, atol=1e-8):
        raise AlignmentUnavailable('previous_and_rectified_geometry_mismatch')
    np_pose = old['pose']; anchor = project([np_pose['anchor']], A)[0]
    if (A[0, 0] <= 0 or not np.allclose(A[:2, :2], np.eye(2)*A[0, 0]) or
            not np.allclose(A[2], [0, 0, 1]) or
            abs(A[0, 0]*np_pose['torso_length']/config.height-config.torso_fraction) > 1e-9 or
            np.linalg.norm(anchor-[config.width/2-.5, config.height*config.shoulder_y-.5]) > 1e-5):
        raise AlignmentUnavailable('previous_uniform_geometry_mismatch')
    image, used, missing = compose_full_source(source, H, config)
    recovered = coverage_gain(previous_used, used)
    if not np.array_equal(image[previous_used > 0], previous_image[previous_used > 0]):
        raise AlignmentUnavailable('previous_real_pixels_changed')
    selected = sorted({j for pair in np_pose['selected_pairs'] for j in pair})
    points = np.rint(project(np.asarray(np_pose['keypoints_corrected'])[selected], A)).astype(int)
    if ((points < 0).any() or (points >= [config.width, config.height]).any() or
            not (used[points[:, 1], points[:, 0]] > 0).all()):
        raise AlignmentUnavailable('shoulder_or_hip_outside_source')
    outputs = {'aligned.png': image, 'content_mask.png': used, 'recovered_mask.png': recovered,
               'alignment_guide.jpg': annotate(image, np_pose, A, anchor[1])}
    for name, pixels in outputs.items():
        if not cv2.imwrite(str(out/name), pixels):
            raise AlignmentUnavailable('cannot_write_'+name)
    # Old rectangular content bounds and four-edge padding fields no longer
    # describe the footprint, so retain only the approved geometry fields.
    frame = {k: old_frame[k] for k in ('bounds_xyxy', 'uniform_scale', 'H_corrected_to_aligned',
             'H_source_to_aligned', 'shoulder_target_xy', 'torso_target_pixels', 'torso_fraction',
             'shoulder_output_xy', 'torso_output_pixels')}
    frame.update(coverage_shape='projected_original_content', source_content_fraction=float((used > 0).mean()),
                 padding_fraction=float((used == 0).mean()), previous_padding_fraction=float((previous_used == 0).mean()),
                 recovered_pixels=int(np.count_nonzero(recovered)),
                 recovered_fraction_of_previous_padding=float(np.count_nonzero(recovered)/max(1, np.count_nonzero(previous_used == 0))),
                 previous_real_pixels_unchanged=True, retained_source_valid_fraction=1., scale_increased_to_fill=False,
                 **missing)
    return frame


def previews(out, previous, groups, config):
    from PIL import Image, ImageDraw, ImageFont
    path = Path('/root/autodl-fs/case-studio/fonts/NotoSansSC.ttf')
    font = ImageFont.truetype(str(path), 18) if path.exists() else ImageFont.load_default()
    contact = []
    for g in groups:
        ids = g['output_ids']
        if not ids:
            continue
        width = 210; height = round(width*config.height/config.width); slot = width+16
        sheet = Image.new('RGB', (slot*len(ids), (height+60)*2), '#ffffff'); draw = ImageDraw.Draw(sheet)
        for index, root in enumerate((previous, out)):
            top = index*(height+60)
            label = '旧版 / ' if index == 0 else '新版 / '
            draw.text((8, top+5), label+g['member'], font=font, fill='#26352c')
            for j, aid in enumerate(ids):
                im = Image.open(root/aid/'aligned.png').convert('RGB').resize((width, height), Image.Resampling.LANCZOS)
                sheet.paste(im, (j*slot+8, top+55)); draw.text((j*slot+8, top+32), aid, fill='#26352c')
        folder = out/'groups'/g['group_id']; folder.mkdir(parents=True, exist_ok=True)
        sheet.save(folder/'source_recovery_comparison.jpg', quality=94)
        clean = sheet.crop((0, height+60, sheet.width, sheet.height))
        clean.save(folder/'clean_group.jpg', quality=94); contact.append(clean)
    if contact:
        sheet = Image.new('RGB', (max(im.width for im in contact), sum(im.height for im in contact)), '#ffffff')
        top = 0
        for im in contact:
            sheet.paste(im, (0, top)); top += im.height
        sheet.save(out/'full_source_contact_sheet.jpg', quality=94)


def run(previous, rectified, out):
    if any(out.resolve().is_relative_to(p.resolve()) for p in (previous, rectified)):
        raise AlignmentUnavailable('output_must_be_separate_from_previous_experiments')
    config_data = json.loads((previous/'config.json').read_text())
    config = UniformConfig(**config_data)
    old_rows = json.loads((previous/'summary.json').read_text())
    groups = json.loads((previous/'groups.json').read_text())
    base = {r['asset_id']: r for r in json.loads((rectified/'summary.json').read_text())}
    ids = [r['asset_id'] for r in old_rows]
    if len(set(ids)) != len(ids) or any(not re.fullmatch(r'[A-Za-z0-9_-]+', aid) for aid in ids):
        raise AlignmentUnavailable('invalid_or_duplicate_asset_ids')
    if any(r.get('status') not in ('uniform', 'skipped', 'needs_review') for r in old_rows):
        raise AlignmentUnavailable('requires_uniform_v3_report')
    out.mkdir(parents=True, exist_ok=False); save_json(out/'config.json', config_data)
    records = {}
    for old in old_rows:
        aid = old['asset_id']; dest = out/aid; dest.mkdir()
        r = {k: old[k] for k in ('asset_id', 'status', 'group_id', 'store', 'member', 'reason') if k in old}
        r.update(method='uniform-full-source-v4', previous_report=str(previous/aid/'report.json'),
                 new_pose_inferences=0, new_api_requests=0)
        if old['status'] == 'uniform':
            r['status'] = 'needs_review'
            try:
                frame = render(rectified/aid, previous/aid, dest, base[aid], old, config)
                r.update(status='full_source', pose=old['pose'], frame=frame, presentation_file='aligned.png')
            except (ValueError, KeyError) as error:
                r['reason'] = str(error)
        records[aid] = r; save_json(dest/'report.json', r)
        print(aid, r['status'], r.get('reason', ''), flush=True)
    for g in groups:
        g['output_ids'] = [aid for aid in g['requested_asset_ids'] if records[aid]['status'] == 'full_source']
        g['excluded_asset_ids'] = [aid for aid in g['requested_asset_ids'] if aid not in g['output_ids']]
        g['complete'] = not g['excluded_asset_ids']
        g['status'] = 'complete' if g['complete'] else ('partial' if g['output_ids'] else 'needs_review')
    save_json(out/'summary.json', list(records.values())); save_json(out/'groups.json', groups)
    group_previews(out, groups); previews(out, previous, groups, config)
    print(dict(Counter(r['status'] for r in records.values())), flush=True)
    return list(records.values()), groups


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('previous', 'rectified', 'out'):
        parser.add_argument('--'+name, type=Path, required=True)
    args = parser.parse_args(); cv2.setNumThreads(4)
    run(args.previous, args.rectified, args.out)


if __name__ == '__main__':
    main()

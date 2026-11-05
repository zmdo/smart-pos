"""Original composite → verified pixel crops → independently classified child job."""
import hashlib
import json
import os
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from scripts.body_scan.localization import (YoloDetector, clean_candidates, merge_duplicates,
                                           overlap, expanded_roi, map_roi_candidates, mask_quality)
from scripts.body_scan.segmentation import SamSegmenter
from scripts.body_scan.pipeline import save_json

from . import VERSION
from .boundaries import (hard_candidates, rectangles, slice_image,
                         translation, check_subjects, overlay)
from .evidence import PairEvidence


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_source(path):
    with Image.open(path) as header:
        if header.width*header.height > 60_000_000:
            raise ValueError('source_pixel_limit_exceeded')
    image = cv2.imread(str(path))  # OpenCV applies JPEG EXIF orientation; crops are EXIF-free PNG.
    if image is None or min(image.shape[:2]) < 128:
        raise ValueError('unreadable_or_too_small_source')
    return image


def write_image(path, image):
    if not cv2.imwrite(str(path), image):
        raise OSError('image_write_failed')


class PairSubjects:
    """YOLO boxes refined per semantic subject, SAM only verifies occupied pixels."""
    def __init__(self, detector=None, segmenter=None):
        self.detector = detector or YoloDetector()
        self.segmenter = segmenter or SamSegmenter()

    def locate(self, image, layout):
        h, w = image.shape[:2]
        hints = [(np.asarray(p['subject_bbox'])*[w, h, w, h]).tolist() for p in layout['panels']]
        attempts = []; boxes = []
        candidates = []
        for size in (1024, 1280):
            found = clean_candidates(self.detector(image, size, .25), image.shape)
            candidates.extend(found)
            attempts.append({'stage': 'full', 'size': size, 'candidates': found})
        candidates = merge_duplicates(candidates)
        for hint in hints:
            def matches(rows):
                selected = []
                for row in rows:
                    box = row['box']; iou, contained = overlap(hint, box)
                    if (iou >= .35 and contained >= .6 and box[3]-box[1] >= .88*(hint[3]-hint[1])
                            and hint[0] <= (box[0]+box[2])/2 <= hint[2]):
                        selected.append((iou, row))
                return sorted(selected, key=lambda p: p[0], reverse=True)
            found = matches(candidates)
            if not found:
                roi = expanded_roi(hint, image.shape, .15)
                crop = image[roi[1]:roi[3], roi[0]:roi[2]]
                found_rows = map_roi_candidates(clean_candidates(self.detector(crop, 1024, .2), crop.shape), roi)
                attempts.append({'stage': 'roi', 'roi': roi, 'candidates': found_rows})
                found = matches(merge_duplicates(found_rows))
            boxes.append(found[0][1]['box'] if found else hint)
            attempts.append({'stage': 'selected', 'box': boxes[-1], 'method': 'yolo' if found else 'vlm_sam'})
        if overlap(*boxes)[0] > .1:
            raise ValueError('pair_subjects_not_separate')
        masks = self.segmenter(image, boxes)
        if getattr(self.segmenter, 'last_fallback', None) or len(masks) != 2:
            raise ValueError('pair_boundary_requires_real_segmentation')
        for mask, box, hint in zip(masks, boxes, hints):
            reason = mask_quality(mask, box, image.shape, strict=True)
            if reason:
                raise ValueError('pair_' + reason)
            ys = np.nonzero(mask)[0]
            if np.ptp(ys)+1 < .85*(hint[3]-hint[1]):
                raise ValueError('pair_mask_does_not_cover_visible_subject_height')
        return boxes, masks, {'attempts': attempts}


def split_asset(asset, input_dir, out, evidence, subjects):
    aid = asset['id']; dest = out/'splits'/aid
    dest.mkdir(parents=True)
    record = {'asset_id': aid, 'store': asset.get('store'), 'member': asset.get('member'),
              'status': 'needs_review', 'children': [], 'attempts': []}
    accepted_assets = []
    try:
        source = (input_dir/asset['path']).resolve()
        if not source.is_relative_to(input_dir.resolve()):
            raise ValueError('source_outside_input_directory')
        record.update({'source': str(source), 'source_sha256': sha(source)})
        image = read_source(source)
        record['decoded_size'] = [image.shape[1], image.shape[0]]
        record['coordinate_system'] = 'OpenCV EXIF-oriented decoded image; integer half-open pixel rectangles'
        layout, record['layout_evidence'] = evidence.layout(image)
        record['layout'] = layout
        if layout['seam']['kind'] != 'hard':
            record.update({'status': 'skipped',
                'reason': ('feathered_composite_not_supported' if layout['seam']['kind'] == 'feather'
                           else 'non_hard_join_not_supported'),
                'reason_zh': ('渐变拼接：接缝处的两张照片已混合，无法无损分离，不符合仅处理硬拼接的规则。'
                              if layout['seam']['kind'] == 'feather' else '存在分隔带，本版仅处理直接硬拼接。')})
            save_json(dest/'report.json', record)
            return record, []
        boxes, masks, record['subject_evidence'] = subjects.locate(image, layout)
        candidates = hard_candidates(image, layout)
        selected = None
        for index, candidate in enumerate(candidates, 1):
            attempt = {'candidate': candidate}; record['attempts'].append(attempt)
            try:
                rects = rectangles(image, layout, candidate)
                attempt['rectangles_parent_xyxy'] = rects
                attempt['subject_checks'] = check_subjects(rects, boxes, masks, image.shape)
                crops = [slice_image(image, rect) for rect in rects]
                annotated = overlay(image, rects, candidate, layout['axis'])
                write_image(dest/f'candidate-{index:02d}.jpg', annotated)
                passed, attempt['review'] = evidence.review_split([image, annotated, *crops])
                attempt['accepted'] = passed
                if attempt['review']['result'].get('residual_blend') is True:
                    record.update({'status': 'skipped', 'reason': 'feathered_composite_not_supported',
                        'reason_zh': '拆分复核发现渐变混合，按仅处理硬拼接的规则淘汰，不输出子图。'})
                    save_json(dest/'report.json', record)
                    return record, []
                if passed:
                    selected = (candidate, rects, crops, annotated)
                    break
                attempt['reason'] = 'split_visual_review_rejected'
            except ValueError as error:
                attempt.update({'accepted': False, 'reason': str(error)})
        if selected is None:
            raise ValueError('no_accepted_split_candidate')
        candidate, rects, crops, annotated = selected
        write_image(dest/'boundaries.jpg', annotated)
        record.update({'status': 'split_ready', 'selected_candidate': candidate,
                       'rectangles_parent_xyxy': rects})
        for i, (rect, crop, panel) in enumerate(zip(rects, crops, layout['panels']), 1):
            child_id = f'{aid}__p{i:02d}'
            path = out/'dataset/input'/(child_id+'.png')
            write_image(path, crop)
            child = {'asset_id': child_id, 'parent_asset_id': aid, 'panel_index': i,
                     'source': str(path), 'source_sha256': sha(path), 'crop_parent_xyxy': rect,
                     'H_parent_to_child': translation(rect).tolist(),
                     'H_child_to_parent': np.linalg.inv(translation(rect)).tolist(),
                     'phase': panel['phase'], 'label_text': panel['label_text'],
                     'status': 'needs_review'}
            record['children'].append(child)
            try:
                classification, child['classification_evidence'] = evidence.classify(crop)
                classification['phase'] = panel['phase']
                child.update({'status': 'ready', 'classification': classification})
                accepted_assets.append({'id': child_id, 'path': child_id+'.png',
                    'store': asset.get('store'), 'member': asset.get('member'), 'class': classification,
                    'classification_evidence': {'source': 'independent_pair_child_vlm',
                        'source_sha256': child['source_sha256'], 'prompt_version': 'pair-child-class-v1'},
                    'pair_source': {k: child[k] for k in ('parent_asset_id', 'panel_index', 'crop_parent_xyxy',
                                                        'H_parent_to_child', 'label_text')}})
            except (ValueError, OSError) as error:
                child['reason'] = str(error)
        if len(accepted_assets) != 2:
            record['status'] = 'split_with_child_review'
    except (ValueError, OSError) as error:
        record['reason'] = str(error)
        if hasattr(error, 'evidence'):
            record['layout_evidence'] = error.evidence
        if str(error) == 'seam_detail_uncertain':
            record['reason_zh'] = '整图与接缝局部判断不一致，未能确认硬拼接，已拦截待复核。'
        elif str(error) == 'no_reliable_hard_seam_evidence':
            record['reason_zh'] = '未检测到跨多个位置一致的清晰硬接缝，已拦截待复核。'
        if str(error) == 'not_confirmed_independent_pair':
            record['status'] = 'skipped'
    save_json(dest/'report.json', record)
    return record, accepted_assets


def prepare(job, out, ids=None, evidence=None, subjects=None):
    job, out = Path(job).resolve(), Path(out).resolve()
    assets = json.loads(job.read_text(encoding='utf-8'))['assets']
    all_ids = [a['id'] for a in assets]
    if len(set(all_ids)) != len(all_ids) or any(not re.fullmatch(r'[A-Za-z0-9_-]+', n) for n in all_ids):
        raise ValueError('invalid_or_duplicate_asset_ids')
    if ids and set(ids)-set(all_ids):
        raise ValueError('unknown_asset_ids')
    if ids:
        assets = [a for a in assets if a['id'] in ids]
    else:
        assets = [a for a in assets if (a.get('class') or {}).get('phase') == 'both'
                  or (a.get('class') or {}).get('is_comparison') is True]
    if not assets:
        raise ValueError('no_comparison_candidates')
    out.mkdir(parents=True, exist_ok=False)
    (out/'dataset/input').mkdir(parents=True)
    evidence = evidence or PairEvidence('/root/autodl-fs/case-studio/cache/body-scan-pairs')
    subjects = subjects or PairSubjects()
    save_json(out/'config.json', {'version': VERSION, 'job': str(job), 'job_sha256': sha(job),
        'asset_ids': [a['id'] for a in assets], 'subject_loss_limit': .002,
        'policy': 'hard_joins_only; reject_feather_before_inference; lossless_crops; independent_child_classification'})
    rows = []; children = []
    for asset in assets:
        record, accepted = split_asset(asset, job.parent/'input', out, evidence, subjects)
        rows.append(record); children.extend(accepted)
        save_json(out/'summary.json', rows)
        save_json(out/'dataset/job.json', {'version': VERSION, 'parent_job': str(job), 'assets': children})
        print(asset['id'], record['status'], record.get('reason', ''), flush=True)
    save_json(out/'counts.json', {'pairs': dict(Counter(r['status'] for r in rows)),
                                'ready_children': len(children)})
    return rows


def align(out):
    """Run the frozen approved pipeline in its own process/import namespace."""
    out = Path(out).resolve()
    archive = Path(__file__).resolve().parents[3]/'body-scan-wall'
    if not json.loads((out/'dataset/job.json').read_text(encoding='utf-8'))['assets']:
        save_json(out/'alignment.json', {'status': 'no_eligible_children'})
        return
    manifest = archive/'manifest.json'
    audit = {'status': 'running', 'archive': str(archive), 'manifest_sha256': sha(manifest)}
    save_json(out/'alignment.json', audit)
    environment = dict(os.environ)
    environment.pop('PYTHONPATH', None)
    # verify_snapshot also verifies import isolation, before any downstream inference.
    for name, command in (
        ('snapshot-check.log', [sys.executable, str(archive/'verify_snapshot.py')]),
        ('alignment.log', [sys.executable, '-u', '-m', 'scripts.body_scan', '--refine-background',
                           '--job', str(out/'dataset/job.json'), '--out', str(out/'aligned')])):
        with (out/name).open('w', encoding='utf-8') as log:
            result = subprocess.run(command, cwd=archive, env=environment, stdout=log,
                                    stderr=subprocess.STDOUT, check=False)
        if result.returncode:
            audit.update({'status': 'failed', 'log': name, 'returncode': result.returncode})
            save_json(out/'alignment.json', audit)
            raise ValueError('approved_pipeline_failed: '+name)
    rows = json.loads((out/'aligned/summary.json').read_text(encoding='utf-8'))
    children = {c['asset_id']: c for r in json.loads((out/'summary.json').read_text(encoding='utf-8')) for c in r['children']}
    mapping = []
    for row in rows:
        child = children[row['asset_id']]
        entry = {'asset_id': row['asset_id'], 'parent_asset_id': child['parent_asset_id'],
                 'crop_parent_xyxy': child['crop_parent_xyxy'], 'status': row['status']}
        if row['status'] == 'rectangular':
            H = np.asarray(row['frame']['H_source_to_aligned']) @ np.asarray(child['H_parent_to_child'])
            entry.update({'H_parent_to_aligned': H.tolist(), 'H_aligned_to_parent': np.linalg.inv(H).tolist(),
                          'valid_only_within_parent_crop': True})
        else:
            entry['reason'] = row.get('reason')
        mapping.append(entry)
    save_json(out/'parent-coordinate-mapping.json', mapping)
    audit.update({'status': 'complete', 'counts': dict(Counter(r['status'] for r in rows))})
    save_json(out/'alignment.json', audit)

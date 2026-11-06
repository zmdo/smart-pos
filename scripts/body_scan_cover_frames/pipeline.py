"""Data-only node: selected assets and inherited phases → cover-specific photos."""
import copy
import hashlib
import json
import re
from pathlib import Path
import cv2
import numpy as np
from . import VERSION
from .geometry import plan_pair, project


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def save(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n')


def checked(ref, bindings):
    path = Path(ref['path']).resolve()
    if sha(path) != ref['sha256']:
        raise ValueError('cover_bound_input_changed: '+path.name)
    bindings[str(path)] = ref['sha256']
    return path


def render(meta, plan):
    source = cv2.imread(meta['source'])
    if source is None or list(source.shape[1::-1]) != meta['upstream_report']['size']:
        raise ValueError('cover_original_size_mismatch')
    width, height = plan['output_size']; H = np.asarray(plan['H_source_to_cover'])
    l, t, r, b = map(int, plan['source_content_bounds_xyxy'])
    # Verify all output support corners, not just a small collection of landmarks.
    footprint = project([[-.5, -.5], [width-.5, -.5], [width-.5, height-.5], [-.5, height-.5]], np.linalg.inv(H))
    if not (np.all(footprint >= [l+2.99, t+2.99]) and np.all(footprint <= [r-3.99, b-3.99])):
        raise ValueError('cover_sampling_would_leave_real_source')
    mask = np.zeros(source.shape[:2], np.uint8); mask[t:b, l:r] = 255
    valid = cv2.warpPerspective(mask, H, (width, height), flags=cv2.INTER_NEAREST, borderMode=cv2.BORDER_CONSTANT)
    if not np.all(valid == 255):
        raise ValueError('cover_has_missing_original_pixels')
    # Crop first so interpolation cannot read any neighbouring comparison panel.
    C = np.array([[1, 0, l], [0, 1, t], [0, 0, 1]])
    image = cv2.warpPerspective(source[t:b, l:r], H @ C, (width, height), flags=cv2.INTER_CUBIC,
                                borderMode=cv2.BORDER_CONSTANT)
    return image, valid


def run(request_path, out, target=(500, 478), max_torso_heights=2.8):
    request_path = Path(request_path).resolve(); out = Path(out).resolve()
    if out.exists():
        raise FileExistsError(out)
    request = read(request_path)
    if request.get('version') != 'cover-frame-request-v1':
        raise ValueError('unsupported_cover_frame_request')
    bindings = {str(request_path): sha(request_path)}
    phase_path = checked(request['phase_result'], bindings); phase = read(phase_path)
    phase_rows = {r['asset_id']: r for r in phase['items']}
    out.mkdir(parents=True); cases = []; gaps = copy.deepcopy(request['gaps']); seen = set(); cache = {}
    for pair in request['pairs']:
        gid = pair['group_id']
        if not re.fullmatch(r'g[0-9]+', gid) or gid in seen:
            raise ValueError('invalid_or_duplicate_cover_group')
        seen.add(gid)
        try:
            assets = pair['assets']
            if len(assets) != 2 or [a['stage']['phase'] for a in assets] != ['before', 'after']:
                raise ValueError('cover_requires_before_after_pair')
            metadata = []
            for asset in assets:
                stage = asset['stage']; aid = stage['asset_id']
                if stage != phase_rows[aid] or stage['view'] != 'front':
                    raise ValueError('cover_phase_snapshot_mismatch')
                if any(stage[k] != pair[k] for k in ('group_id', 'store', 'member')):
                    raise ValueError('cover_pair_member_mismatch')
                summary = checked(asset['display_summary'], bindings)
                if summary not in cache:
                    cache[summary] = {r['asset_id']: r for r in read(summary)}
                meta = cache[summary][aid]
                if meta['status'] != 'displayed' or any(meta[k] != stage[k] for k in ('store', 'member', 'source_sha256')):
                    raise ValueError('cover_geometry_identity_mismatch')
                checked({'path': meta['source'], 'sha256': meta['source_sha256']}, bindings)
                metadata.append(meta)
            if metadata[0]['source_sha256'] == metadata[1]['source_sha256']:
                raise ValueError('cover_requires_distinct_originals')
            plans = plan_pair(metadata, target, max_torso_heights)
            rendered = [render(m, p) for m, p in zip(metadata, plans)]
            dest = out/gid; dest.mkdir(); frames = []
            for asset, meta, plan, (image, valid) in zip(assets, metadata, plans, rendered):
                name = asset['stage']['phase']; path = dest/(name+'.png'); mask_path = dest/(name+'-valid.png')
                if not cv2.imwrite(str(path), image) or not cv2.imwrite(str(mask_path), valid):
                    raise OSError('cover_frame_write_failed')
                frames.append({'asset_id': meta['asset_id'], 'file': path.relative_to(out).as_posix(),
                               'sha256': sha(path), 'source_sha256': meta['source_sha256'],
                               'stage': asset['stage'], 'plan': plan, 'valid_pixels': int(valid.size),
                               'invalid_pixels': 0, 'mask_sha256': sha(mask_path)})
            pair_path = dest/'pair.png'
            if not cv2.imwrite(str(pair_path), np.concatenate([r[0] for r in rendered], axis=1)):
                raise OSError('cover_pair_write_failed')
            cases.append({k: pair[k] for k in ('group_id', 'store', 'member')} |
                         {'frames': frames, 'pair_file': pair_path.relative_to(out).as_posix(),
                          'pair_sha256': sha(pair_path), 'requires_review': any(a['stage']['requires_review'] for a in assets),
                          'framing_requires_review': any(p['review_reasons'] for p in plans)})
            print(gid, 'cover_frames_generated', flush=True)
        except (ValueError, KeyError, OSError) as error:
            gaps.append({k: pair[k] for k in ('group_id', 'store', 'member')} | {'reason': str(error)})
    if any(sha(p) != h for p, h in bindings.items()):
        raise ValueError('cover_inputs_changed_during_render')
    result = {'version': VERSION, 'phase_result_sha256': request['phase_result']['sha256'],
              'request_sha256': sha(request_path), 'review_target': request['review_target'],
              'cases': cases, 'gaps': gaps, 'output_size': list(target), 'max_torso_heights': max_torso_heights,
              'model_requests': 0, 'phase_policy': 'inherit_exact_rows_by_asset_id',
              'sampling_policy': 'original_pixels_with_approved_geometry_no_group_display_stretch'}
    save(out/'frames.json', result); save(out/'private-inputs.json', {'bindings': bindings})
    return result

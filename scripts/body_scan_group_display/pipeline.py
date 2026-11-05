"""Approved outputs → one frame per person → separate reference/display derivatives."""
import copy
import json
import shutil
from collections import Counter, defaultdict
from dataclasses import asdict
from pathlib import Path

import cv2
import numpy as np

from scripts.body_scan.landmarks import member_key
from scripts.body_scan.pipeline import save_json, VIEW_ORDER
from . import VERSION
from .audit import run as classify
from .inputs import digest, load_inputs
from .planning import Config, PROFILES, PlanUnavailable, plan_person
from .visibility import profile_name


def reuse_audit(inputs, audit):
    items, excluded, sources = load_inputs(inputs)
    audit = Path(audit).resolve()
    previous = json.loads((audit/'sources.json').read_text(encoding='utf-8'))
    if sources != previous:
        raise ValueError('visibility_audit_input_sources_changed')
    rows = json.loads((audit/'items.json').read_text(encoding='utf-8'))
    if len({r['asset_id'] for r in rows}) != len(rows):
        raise ValueError('duplicate_visibility_audit_asset')
    lookup = {r['asset_id']: r for r in rows}
    if set(lookup) != {r['asset_id'] for r in items}:
        raise ValueError('visibility_audit_asset_mismatch')
    for item in items:
        cached = lookup[item['asset_id']]
        for key in ('source_sha256', 'approved_image_sha256', 'approved_mask_sha256',
                    'normalized_bounds', 'H_source_to_normalized', 'required_core'):
            if cached[key] != item[key]:
                raise ValueError('visibility_audit_source_changed: '+item['asset_id'])
        for key in ('visibility', 'visibility_evidence', 'profile', 'visible_bounds_normalized',
                    'boundary_guard', 'status', 'reason'):
            if key in cached:
                item[key] = cached[key]
        if item['status'] not in ('classified', 'needs_review'):
            raise ValueError('invalid_visibility_audit_status')
        if item['status'] == 'classified':
            if item['profile'] != profile_name(item['visibility']):
                raise ValueError('visibility_profile_mismatch')
            needs_guard = (item['visibility_evidence']['result'].get('lower_extent') == 'feet_complete'
                           or (item['visibility_evidence']['result'].get('head') == 'complete'
                               and item['visibility_evidence']['result']['visible_bbox'][1] <= .012))
            if needs_guard and 'boundary_guard' not in item:
                raise ValueError('visibility_audit_missing_boundary_guard')
            guard = item.get('boundary_guard', {})
            if needs_guard and guard.get('version') != 2:
                raise ValueError('visibility_audit_requires_prompted_boundary_masks')
            if 'feet_override' in guard or 'head_override' in guard:
                raise ValueError('visibility_audit_requires_semantic_edge_review')
            if guard.get('strategy') in ('sam_contact_then_vlm_edge_review', 'vlm_edge_review') and 'edge_evidence' not in guard:
                raise ValueError('visibility_audit_missing_edge_review')
    return items, excluded, sources


def render(item, plan, dest):
    source = cv2.imread(item['source'])
    if source is None or digest(item['source']) != item['source_sha256']:
        raise ValueError('original_source_changed_during_render')
    original = item['upstream_report']
    x1, y1, x2, y2 = original['frame']['source_content_bounds_xyxy']
    cropped = source[y1:y2, x1:x2]
    sampling = cv2.copyMakeBorder(cropped, y1, source.shape[0]-y2, x1, source.shape[1]-x2, cv2.BORDER_REPLICATE)
    width, height = plan['output_size']; output_size = (width, height)
    normalized = np.asarray(item['H_source_to_normalized'])
    old_to_normalized = np.asarray(item['H_aligned_to_normalized'])
    old_mask = cv2.imread(str(Path(item['input_directory'])/item['asset_id']/'content_mask.png'), 0)
    outputs = {}; matrices = {}
    for name in ('uniform', 'display'):
        adjustment = np.asarray(plan['H_normalized_to_'+name])
        H = adjustment @ normalized
        image = cv2.warpPerspective(sampling, H, output_size, flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)
        valid = cv2.warpPerspective(old_mask, adjustment@old_to_normalized, output_size,
                                    flags=cv2.INTER_NEAREST, borderMode=cv2.BORDER_CONSTANT)
        if name == 'display':
            if not (valid == 255).all():
                raise ValueError('display_would_use_pixels_outside_approved_photo')
        else:
            l, t, r, b = plan['uniform_content_edges']
            xx, yy = np.arange(width)[None, :], np.arange(height)[:, None]
            use = (xx >= l) & (xx < r) & (yy >= t) & (yy < b)
            if not (valid[use] == 255).all():
                raise ValueError('uniform_reference_outside_approved_photo')
            image[~use] = (227, 234, 238)
        outputs[name] = image
        matrices['H_source_to_'+name] = H.tolist()
        matrices['H_aligned_to_'+name] = (adjustment@old_to_normalized).tolist()
    dest.mkdir(parents=True, exist_ok=False)
    shutil.copy2(item['approved_image'], dest/'baseline.png')
    for name, image in outputs.items():
        if not cv2.imwrite(str(dest/(name+'.png')), image):
            raise OSError('group_display_image_write_failed')
    return {**matrices, 'display_sha256': digest(dest/'display.png'),
            'uniform_sha256': digest(dest/'uniform.png'),
            'retained_fraction_of_approved_photo': float(
                (plan['crop_rectangle'][2]-plan['crop_rectangle'][0])*(plan['crop_rectangle'][3]-plan['crop_rectangle'][1]) /
                ((item['normalized_bounds'][2]-item['normalized_bounds'][0])*(item['normalized_bounds'][3]-item['normalized_bounds'][1])))}


def run(inputs, out, audit=None, config=None, profiles=None, workers=3):
    out = Path(out).resolve()
    if out.exists():
        raise ValueError('output_directory_already_exists')
    config = config or Config(); profiles = profiles or copy.deepcopy(PROFILES)
    if audit:
        items, excluded, sources = reuse_audit(inputs, audit)
        out.mkdir(parents=True)
    else:
        out.mkdir(parents=True)
        items, excluded, sources = classify(inputs, out/'visibility', workers)
        audit = out/'visibility'
    save_json(out/'config.json', {'version': VERSION, **asdict(config), 'profiles': profiles, 'inputs': sources,
        'visibility_audit': str(Path(audit).resolve()), 'audit_items_sha256': digest(Path(audit)/'items.json'),
        'group_policy': 'one_frame_per_store_member', 'presentation_only': True,
        'resampling': 'compose approved geometry with display matrix, sample original once',
        'threshold_meaning': 'vertical_scale / horizontal_scale; not absolute pixel enlargement'})
    grouped = defaultdict(list)
    for item in items:
        grouped[member_key(item)].append(item)
    groups = []
    for number, ((store, member), members) in enumerate(sorted(grouped.items()), 1):
        gid = f'g{number:03d}'
        group = {'group_id': gid, 'store': store, 'member': member, 'cohorts': []}
        groups.append(group)
        cohort = []
        for item in members:
            item['group_id'] = gid
            if item['status'] == 'classified':
                cohort.append(item)
        if cohort:
            cohort.sort(key=lambda r: (VIEW_ORDER.get(r['upstream_report']['classification'].get('view'), 5), r['asset_id']))
            cid = gid+'__shared'
            row = {'cohort_id': cid, 'asset_ids': [r['asset_id'] for r in cohort]}
            group['cohorts'].append(row)
            for item in cohort:
                item['cohort_id'] = cid
            try:
                plan = plan_person(cohort, config, profiles)
                row.update({'status': 'planned', 'profile': plan['profile'], 'plan': plan})
                group.update({'output_size': plan['output_size'], 'display_profile': plan['profile']})
                for item in cohort:
                    item['display_profile'] = plan['profile']
                    try:
                        item['output'] = render(item, plan, out/'images'/item['asset_id'])
                        item.update({'status': 'displayed', 'group_plan': plan})
                    except (ValueError, OSError) as error:
                        item.update({'status': 'needs_review', 'reason': str(error)})
                row['status'] = 'complete' if all(r['status'] == 'displayed' for r in cohort) else 'partial'
            except (ValueError, OSError) as error:
                row.update({'status': 'needs_review', 'reason': str(error)})
                if isinstance(error, PlanUnavailable):
                    row['diagnostic'] = error.detail
                for item in cohort:
                    item.update({'status': 'needs_review', 'reason': str(error)})
            print(cid, row['status'], row.get('reason', ''), flush=True)
        group['needs_review_asset_ids'] = [r['asset_id'] for r in members if r['status'] != 'displayed']
        save_json(out/'groups.json', groups)
        save_json(out/'summary.json', items)
    # Empty upstream runs are a valid no-op and still need a complete report.
    save_json(out/'groups.json', groups)
    save_json(out/'summary.json', items)
    save_json(out/'upstream-excluded.json', excluded)
    for item in items:
        dest = out/'reports'; dest.mkdir(exist_ok=True)
        save_json(dest/(item['asset_id']+'.json'), item)
    save_json(out/'counts.json', {'items': dict(Counter(r['status'] for r in items)),
        'coverage_profiles': dict(Counter(r.get('profile', 'uncertain') for r in items)), 'groups': len(groups),
        'group_policy': 'one_frame_per_store_member',
        'cohorts': sum(len(g['cohorts']) for g in groups), 'upstream_excluded': len(excluded)})
    return items, groups

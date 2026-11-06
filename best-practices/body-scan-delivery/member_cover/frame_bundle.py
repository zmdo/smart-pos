"""Consume upstream photos and exact inherited stage rows; never relabel them."""
from pathlib import Path
from PIL import Image
from scripts.body_scan_contracts.io import read, sha, bind


def load_frames(root, result_sha, bindings):
    root = Path(root).resolve(); data = read(bind(root/'frames.json', bindings))
    if data.get('version') not in ('body-scan-cover-frames-v1', 'body-scan-cover-frames-v2') or data['phase_result_sha256'] != result_sha:
        raise ValueError('cover_frames_belong_to_another_phase_revision')
    if data['output_size'] != [500, 478]:
        raise ValueError('cover_frame_size_does_not_match_template')
    provenance = read(bind(root/'private-inputs.json', bindings))
    for path, expected in provenance['bindings'].items():
        if sha(bind(path, bindings)) != expected:
            raise ValueError('cover_frame_upstream_geometry_or_source_changed')
    cases = {c['group_id']: c for c in data['cases']}
    if len(cases) != len(data['cases']):
        raise ValueError('duplicate_cover_frame_group')
    return root, cases, data


def consume_frames(bundle, pair, identity, bindings):
    root, cases, _ = bundle; case = cases.get(identity['group_id'])
    if case is None:
        raise ValueError('封面双图节点没有可用结果，请检查 frames.json 的未生成原因')
    if any(case[k] != identity[k] for k in ('group_id', 'store', 'member')):
        raise ValueError('cover_frame_member_mismatch')
    if [f['stage'] for f in case['frames']] != list(pair):
        raise ValueError('cover_frame_stage_or_selected_pair_changed')
    images = []
    for frame in case['frames']:
        path = (root/frame['file']).resolve()
        if not path.is_relative_to(root) or sha(bind(path, bindings)) != frame['sha256']:
            raise ValueError('cover_frame_pixels_changed')
        with Image.open(path) as im:
            if list(im.size) != [500, 478]:
                raise ValueError('cover_frame_canvas_mismatch')
            images.append(im.convert('RGB').copy())
    return images, [f['plan'] for f in case['frames']], case

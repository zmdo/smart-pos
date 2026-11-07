"""Evaluate UVDoc geometry on existing, source-bound report classifications."""
import argparse
import hashlib
import html
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import time

import cv2
import numpy as np
from PIL import Image, ImageOps
import torch
import torch.nn.functional as F

VERSION = 'report-photo-dewarp-experiment-v1'
UVDOC_COMMIT = '4c9b82b537057aff2526e6dd118a847cdd072e82'
KINDS = {'body_report': '体测报告', 'training_report': '训练报告'}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def grid_checks(grid):
    """Check backward-grid validity, not semantic/document correctness."""
    if (grid.ndim != 3 or grid.shape[0] != 2 or min(grid.shape[1:]) < 2
            or not np.isfinite(grid).all()):
        raise ValueError('invalid_model_grid')
    dx = grid[:, :-1, 1:] - grid[:, :-1, :-1]
    dy = grid[:, 1:, :-1] - grid[:, :-1, :-1]
    det = dx[0] * dy[1] - dx[1] * dy[0]
    return {'fold_fraction': float(np.mean(det <= 0)),
            'outside_control_points_fraction': float(np.mean(np.any(np.abs(grid) > 1, axis=0)))}


def select_rows(audit, input_root, ids):
    rows, seen = [], set()
    for row in audit:
        aid = row['asset_id']
        kind = row.get('qwen', {}).get('kind')
        if kind not in KINDS or (ids and aid not in ids):
            continue
        relative = row['source'].split('/私教会员案例项目/', 1)[-1]
        parts = Path(relative).parts
        if not parts or not parts[0].endswith('店') or parts[0] != row['store']:
            raise ValueError('not_store_material: ' + aid)
        source = (input_root / relative).resolve()
        if not source.is_relative_to(input_root.resolve()):
            raise ValueError('source_outside_input_root')
        if not re.fullmatch(r'a[0-9]+', aid) or aid in seen:
            raise ValueError('invalid_or_duplicate_asset_id')
        if sha(source) != row['source_sha256']:
            raise ValueError('source_hash_mismatch: ' + aid)
        seen.add(aid)
        rows.append((row, kind, source))
    if ids and ids != seen:
        raise ValueError('requested_report_ids_missing: ' + str(sorted(ids - seen)))
    if not rows:
        raise ValueError('no_reports_selected')
    return sorted(rows, key=lambda x: (x[0]['store'], x[0]['member'], x[0]['asset_id']))


def gallery(out, rows):
    cards = []
    for row in rows:
        aid = row['asset_id']
        panels = []
        for name, label in [('original', '原图'), ('unwarped', '展平候选 · 待审核')]:
            panels.append(f'<figure><figcaption>{label}</figcaption><a href="{aid}/{name}.png" '
                          f'target="_blank"><img loading="lazy" src="{aid}/{name}-preview.jpg" '
                          f'alt="{label}"></a></figure>')
        label = html.escape(f"{row['store']} / {row['member']} · {aid} · {KINDS[row['kind']]}")
        flags = '；'.join(row['review_reasons'])
        cards.append(f'<section id="{aid}"><h2>{label}</h2><p>{html.escape(flags)}</p>'
                     f'<div class="pair">{"".join(panels)}</div></section>')
    page = '''<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>报告照片展平试验</title>
<style>body{margin:0;background:#f3f1ed;color:#263831;font:16px system-ui,sans-serif}
main{max-width:1550px;margin:auto;padding:28px}h1{font-size:30px}h2{font-size:20px}
section{background:white;padding:22px;margin:24px 0;border-radius:16px}p{line-height:1.7;color:#65716b}
.pair{display:grid;grid-template-columns:1fr 1fr;gap:18px}figure{margin:0;min-width:0}
figcaption{padding:10px 0;font-weight:600}img{display:block;width:100%;height:auto}
a{color:#246249}@media(max-width:600px){main{padding:10px}section{padding:12px}.pair{gap:8px}}
</style><main><h1>报告照片 · 曲面展平试验</h1>
<p>左原图，右展平候选；点击可查看完整 PNG。仅变换原图像素，不重写文字、数字或手写批注。
没有重新判断训练前后，也没有修改现有成品。所有结果需逐张审核，网格合法不代表内容完整。
遮挡、反光及原图缺失仍可能存在；保留原始阴影，本轮不做去阴影、美白或锐化。</p>
'''
    (out / 'index.html').write_text(page + ''.join(cards) + '</main></html>', encoding='utf-8')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--audit', type=Path, required=True)
    p.add_argument('--input-root', type=Path, required=True)
    p.add_argument('--uvdoc', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--ids', nargs='*')
    args = p.parse_args()
    if args.out.exists():
        raise ValueError('output_must_be_new')
    if not torch.cuda.is_available():
        raise RuntimeError('run_on_remote_cuda_server')
    revision = subprocess.check_output(['git', '-C', str(args.uvdoc), 'rev-parse', 'HEAD'], text=True).strip()
    if revision != UVDOC_COMMIT:
        raise ValueError('unexpected_uvdoc_revision')
    status = subprocess.check_output(['git', '-C', str(args.uvdoc), 'status', '--porcelain', '--untracked-files=no'], text=True)
    if status.strip():
        raise ValueError('modified_uvdoc_checkout')
    selected = select_rows(json.loads(args.audit.read_text()), args.input_root, set(args.ids or []))
    spec = importlib.util.spec_from_file_location('report_dewarp_uvdoc_model', args.uvdoc / 'model.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    model = module.UVDocnet(num_filter=32, kernel_size=5)
    weights = args.uvdoc / 'model/best_model.pkl'
    state = torch.load(weights, map_location='cpu', weights_only=True)
    model.load_state_dict(state['model_state'])
    model = model.eval().to('cuda')
    args.out.mkdir(parents=True)
    rows = []
    started = time.monotonic()
    with torch.inference_mode():
        for row, kind, source in selected:
            t = time.monotonic()
            aid = row['asset_id']
            dest = args.out / aid
            dest.mkdir()
            with Image.open(source) as raw:
                original = ImageOps.exif_transpose(raw).convert('RGB')
            array = np.asarray(original).astype(np.float32) / 255
            # Match the author's RGB preprocessing and align_corners conventions.
            small = cv2.resize(array, (488, 712))
            inp = torch.from_numpy(small.transpose(2, 0, 1)).unsqueeze(0).to('cuda')
            points, _ = model(inp)
            grid = points[0].cpu().numpy()
            checks = grid_checks(grid)
            np.save(dest / 'backward-grid.npy', grid)
            if checks['fold_fraction'] > 0:
                raise ValueError('folded_grid: ' + aid)
            full_grid = F.interpolate(points, size=array.shape[:2], mode='bilinear', align_corners=True)
            full_grid = full_grid.permute(0, 2, 3, 1)
            src = torch.from_numpy(array.transpose(2, 0, 1)).unsqueeze(0).to('cuda')
            warped = F.grid_sample(src, full_grid, align_corners=True)
            mask = F.grid_sample(torch.ones_like(src[:, :1]), full_grid, align_corners=True)
            # Out-of-source support is white and explicitly audited; no invented content.
            warped += 1 - mask
            checks['outside_sample_fraction'] = float((mask < .999).float().mean().cpu())
            result = Image.fromarray((warped[0].permute(1, 2, 0).cpu().numpy().clip(0, 1) * 255).round().astype(np.uint8))
            for name, image in [('original', original), ('unwarped', result)]:
                image.save(dest / (name + '.png'))
                preview = image.copy()
                preview.thumbnail((1100, 1800), Image.Resampling.LANCZOS)
                preview.save(dest / (name + '-preview.jpg'), quality=92)
            flags = ['待审核：核对纸张边缘、表格线及文字数字完整性']
            if checks['outside_sample_fraction'] > 0:
                flags.append('模型采样超出原图区域，已留白；没有补画内容')
            rows.append({'asset_id': aid, 'store': row['store'], 'member': row['member'],
                         'kind': kind, 'source_sha256': row['source_sha256'],
                         'source_filename': source.name, 'size': list(original.size),
                         'status': 'candidate_requires_review', 'review_reasons': flags,
                         'grid_checks': checks, 'seconds': round(time.monotonic() - t, 3),
                         'output_sha256': sha(dest / 'unwarped.png')})
            print(aid, kind, checks, flush=True)
            del src, full_grid, warped, mask, inp, points
    manifest = {'version': VERSION, 'model_repository': 'https://github.com/tanguymagne/UVDoc',
                'model_commit': revision, 'weights_sha256': sha(weights), 'audit_sha256': sha(args.audit),
                'model_input_size': [488, 712], 'output_size_policy': 'preserve_exif_oriented_source_size',
                'phase_classification_calls': 0, 'adopted_results': 0,
                'gpu_peak_allocated_bytes': torch.cuda.max_memory_allocated(),
                'seconds': round(time.monotonic() - started, 3), 'rows': rows}
    (args.out / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
    gallery(args.out, rows)
    print(json.dumps({'completed': len(rows), 'seconds': manifest['seconds'],
                      'gpu_peak_allocated_bytes': manifest['gpu_peak_allocated_bytes']}), flush=True)


if __name__ == '__main__':
    main()

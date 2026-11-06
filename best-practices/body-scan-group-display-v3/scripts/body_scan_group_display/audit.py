"""Classify visible body coverage independently of group crop planning."""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

from scripts.body_scan.pipeline import save_json
from .inputs import load_inputs, effective_image, visible_bounds
from .visibility import VisibilityEvidence, profile_name
from .boundary import BoundarySegmenter, mark_touching_edges


def boundary_guards(items, evidence, workers=3):
    """SAM contact triggers semantic edge review; posters must not become body cuts."""
    segmenter = BoundarySegmenter()
    review = []
    for item in items:
        if item['status'] != 'classified':
            continue
        value = item['visibility']
        check_feet = value['lower_extent'] == 'feet_complete'
        check_head = value['head'] == 'complete' and value['visible_bbox'][1] <= .012
        if not (check_feet or check_head):
            continue
        image = effective_image(item); h, w = image.shape[:2]
        box = (np.asarray(value['visible_bbox'])*[w, h, w, h]).tolist()
        mask, segmentation = segmenter(image, box, item)
        if mask is None:
            item['boundary_guard'] = {'segmentation': segmentation, 'strategy': 'vlm_edge_review', 'version': 2}
            review.append(item)
            continue
        guard = {'model_head': value['head'], 'model_lower_extent': value['lower_extent'], 'strategy': 'sam_boundary_contact',
                 'segmentation': segmentation, 'version': 2}
        bottom = int(np.count_nonzero(mask[-2:]))
        guard['bottom_contact_pixels'] = bottom
        if check_feet and bottom >= max(4, int(.01*w)):
            guard['feet_contact_requires_review'] = True
        if check_head:
            rect = item['approved_content_rectangle']
            anchor = item['upstream_report']['frame']['shoulder_target_xy'][0]-rect[0]
            radius = .4*item['upstream_report']['frame']['torso_target_pixels']
            x1, x2 = max(0, int(anchor-radius)), min(w, int(anchor+radius))
            top = int(np.count_nonzero(mask[:2, x1:x2]))
            guard['head_zone_top_contact_pixels'] = top
            if top >= max(4, int(.01*w)):
                guard['head_contact_requires_review'] = True
        item['boundary_guard'] = guard
        if guard.get('feet_contact_requires_review') or guard.get('head_contact_requires_review'):
            guard['strategy'] = 'sam_contact_then_vlm_edge_review'
            review.append(item)

    def inspect(item):
        try:
            reviewed, trace = evidence.inspect_edges(effective_image(item))
            reviewed = mark_touching_edges(reviewed, item['boundary_guard'])
            item.update({'visibility': reviewed, 'profile': profile_name(reviewed),
                         'visible_bounds_normalized': visible_bounds(item, reviewed)})
            item['boundary_guard']['edge_evidence'] = trace
        except (ValueError, OSError) as failure:
            item.update({'status': 'needs_review', 'reason': 'visibility_edge_review_unavailable: '+str(failure)})
            if hasattr(failure, 'evidence'):
                item['boundary_guard']['edge_evidence'] = failure.evidence
        print(item['asset_id'], 'edge_review', item['status'], item.get('profile'), flush=True)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(inspect, review))
    return items


def run(inputs, out, workers=3, cache=None):
    out = Path(out).resolve()
    items, excluded, sources = load_inputs(inputs)
    out.mkdir(parents=True, exist_ok=False)
    evidence = VisibilityEvidence(cache or '/root/autodl-fs/case-studio/cache/body-scan-group-visibility')

    def classify(item):
        try:
            value, trace = evidence.inspect(effective_image(item))
            item.update({'visibility': value, 'visibility_evidence': trace, 'profile': profile_name(value),
                         'visible_bounds_normalized': visible_bounds(item, value), 'status': 'classified'})
        except (ValueError, OSError) as error:
            item.update({'status': 'needs_review', 'reason': str(error)})
            if hasattr(error, 'evidence'):
                item['visibility_evidence'] = error.evidence
        print(item['asset_id'], item['status'], item.get('profile', item.get('reason')), flush=True)
        return item

    results = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for result in pool.map(classify, items):
            results.append(result)
            save_json(out/'items.json', results)
    boundary_guards(results, evidence, workers)
    save_json(out/'items.json', results)
    save_json(out/'sources.json', sources)
    save_json(out/'upstream-excluded.json', excluded)
    save_json(out/'counts.json', {'status': dict(Counter(r['status'] for r in results)),
                                'profiles': dict(Counter(r.get('profile') for r in results)),
                                'upstream_excluded': len(excluded)})
    return results, excluded, sources


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', nargs='+', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--workers', type=int, choices=range(1, 5), default=3)
    args = parser.parse_args()
    run(args.input, args.out, args.workers)

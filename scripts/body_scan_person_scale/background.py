"""Independent physical-background scale measurements in corrected coordinates."""
import numpy as np
import cv2

from scripts.body_scan.grid import detect_segments, lattice
from scripts.body_scan.group_scale import features, registration
from scripts.body_scan.wall_geometry import scene_valid


def extract(source, row, person):
    H = np.asarray(row['geometry']['H_source_to_corrected'])
    result = {'grid_pitch': None, 'features': None, 'notes': []}
    if row['route'] == 'grid':
        try:
            # Measure real detected lines through the already-approved geometry; no new warp.
            exclude = cv2.dilate(person.astype(np.uint8), np.ones((25, 25), np.uint8)) > 0
            vertical, horizontal = detect_segments(source, exclude)
            px, _, vx = lattice(vertical, H, 'v', max(source.shape[:2]))
            py, _, hy = lattice(horizontal, H, 'h', max(source.shape[:2]))
            if max(px, py)/min(px, py) > 1.05 or max(vx['spacing_error_fraction'], hy['spacing_error_fraction']) > .07:
                raise ValueError('grid_pitch_disagrees')
            result['grid_pitch'] = float(np.sqrt(px*py))
            result['grid_measurement'] = {'vertical': vx, 'horizontal': hy}
        except ValueError as error:
            result['notes'].append(str(error))
    else:
        scene = row.get('refinement', {}).get('scene', {})
        if not scene:
            scene = (row.get('geometry_guard', {}).get('previous_refinement') or {}).get('scene', {})
        if scene_valid(scene):
            result['features'] = features(source, scene, person)
        else:
            result['notes'].append('no_reliable_wall_region')
    return result


def relative(ref, target):
    a, b = ref['semantic'], target['semantic']
    if (a['background_group'] != b['background_group'] or not a['near_wall'] or not b['near_wall']
            or min(a['confidence'], b['confidence']) < .8):
        raise ValueError('background_not_shared_and_nearby')
    r, t = ref['row'], target['row']
    ga, gb = ref['background']['grid_pitch'], target['background']['grid_pitch']
    if r['route'] == t['route'] == 'grid' and ga and gb:
        return gb/ga, {'method': 'measured_same_board_pitch', 'reference_pitch': ga, 'target_pitch': gb}
    if r['route'] == t['route'] == 'non_grid':
        fa, fb = ref['background']['features'], target['background']['features']
        if fa is not None and fb is not None:
            scale, proof = registration(fa, fb, np.asarray(r['geometry']['H_source_to_corrected']),
                np.asarray(t['geometry']['H_source_to_corrected']), ref['source'].shape,
                target['source'].shape, r['pose']['anchor'])
            return scale, {'method': 'registered_physical_wall', **proof}
    raise ValueError('no_measured_background_scale')

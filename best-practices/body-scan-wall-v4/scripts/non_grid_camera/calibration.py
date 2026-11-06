"""Local GPU inference adapter for the official GeoCalib checkpoints."""
import hashlib
import json
from pathlib import Path

import cv2
import numpy as np

from scripts.body_scan.geometry import content_mask


GEOCALIB_COMMIT = '1dedb29f94fc11b896c5f572005978aeebccd67f'


class Calibrator:
    def __init__(self, weights, cache):
        self.weights = Path(weights)
        self.cache = Path(cache)
        self.digest = hashlib.sha256(self.weights.read_bytes()).hexdigest()
        self.model = None

    def __call__(self, source, camera_model):
        import torch
        _, bounds = content_mask(source)
        x1, y1, x2, y2 = bounds
        image = source[y1:y2, x1:x2]
        signature = {'version': 'camera-calibration-v1', 'code_commit': GEOCALIB_COMMIT,
                     'weights_sha256': self.digest, 'camera_model': camera_model, 'bounds': bounds}
        key = hashlib.sha256(image.tobytes()+json.dumps(signature, sort_keys=True).encode()).hexdigest()
        path = self.cache/(key+'.json')
        if path.exists():
            return {**json.loads(path.read_text(encoding='utf-8')), 'cached': True}
        if self.model is None:
            from geocalib import GeoCalib
            self.model = GeoCalib(weights=str(self.weights)).cuda().eval()
        tensor = torch.from_numpy(cv2.cvtColor(image, cv2.COLOR_BGR2RGB)).permute(2, 0, 1).float().cuda()/255
        result = self.model.calibrate(tensor, camera_model=camera_model)
        camera, gravity = result['camera'], result['gravity']
        K = camera.K[0].cpu().numpy().astype(float)
        K[:2, 2] += [x1, y1]
        estimate = {**signature, 'K': K.tolist(), 'R': gravity.R[0].cpu().numpy().tolist(),
                    'roll_deg': float(torch.rad2deg(gravity.roll)[0]),
                    'pitch_deg': float(torch.rad2deg(gravity.pitch)[0]),
                    'vfov_deg': float(torch.rad2deg(camera.vfov)[0]),
                    'k1': float(camera.k1[0]) if hasattr(camera, 'k1') else 0.,
                    'cached': False}
        for name in ('roll_uncertainty', 'pitch_uncertainty', 'vfov_uncertainty'):
            estimate[name+'_deg'] = float(torch.rad2deg(result[name]).flatten()[0])
        estimate['focal_relative_uncertainty'] = float(result['focal_uncertainty'].flatten()[0]/camera.f[0, 1])
        if not np.isfinite([estimate[k] for k in ('roll_deg', 'pitch_deg', 'vfov_deg', 'k1')]).all():
            raise ValueError('non_finite_calibration')
        self.cache.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(estimate, indent=2)+'\n', encoding='utf-8')
        return estimate


def warnings(estimate):
    notes = []
    if estimate['roll_uncertainty_deg'] > 1.5 or estimate['pitch_uncertainty_deg'] > 3.:
        notes.append('camera_angle_uncertain')
    if estimate['vfov_uncertainty_deg'] > 10 or estimate['focal_relative_uncertainty'] > .2:
        notes.append('focal_length_uncertain')
    if abs(estimate['roll_deg']) > 15 or abs(estimate['pitch_deg']) > 25:
        notes.append('large_camera_tilt')
    if not 20 < estimate['vfov_deg'] < 100:
        notes.append('field_of_view_outside_expected_range')
    return notes

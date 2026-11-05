"""Approved pinhole camera correction, returning a matrix for shared framing."""
from pathlib import Path

import numpy as np

DEFAULT_WEIGHTS = Path('/root/autodl-fs/case-studio/models/geocalib/geocalib-pinhole.tar')
DEFAULT_CACHE = Path('/root/autodl-fs/case-studio/cache/camera-calibration')


class CameraCorrectionUnavailable(ValueError):
    def __init__(self, reason, geometry=None):
        super().__init__(reason)
        self.geometry = geometry or {}


def identity_transform(image, subject=None):
    """Explicit baseline mode, never an automatic fallback after failed calibration."""
    return np.eye(3), {'method': 'non-grid-identity-v1', 'action': 'identity',
                      'correction_applied': False, 'output_size': [image.shape[1], image.shape[0]],
                      'warnings': []}


class NonGridTransform:
    def __init__(self, weights=DEFAULT_WEIGHTS, cache=DEFAULT_CACHE, mode='pinhole', calibrator=None):
        if mode not in ('pinhole', 'identity'):
            raise ValueError('unsupported_non_grid_transform')
        self.weights, self.cache, self.mode = Path(weights), Path(cache), mode
        self.calibrator = calibrator

    def __call__(self, image, subject):
        if self.mode == 'identity':
            return identity_transform(image, subject)
        metadata = {'method': 'non-grid-pinhole-v2', 'action': 'camera_pinhole',
                    'correction_applied': False, 'applied_k1': 0.,
                    'policy': 'user-approved-pinhole-with-experiment-guards',
                    'approved_experiment_commit': 'e77b68708d66d96cfc6025ad4c7a27e259fe4193'}
        try:
            from scripts.non_grid_camera.calibration import Calibrator, warnings
            from scripts.non_grid_camera.geometry import canvas_plan
            if subject is None:
                raise ValueError('camera_correction_requires_subject_box')
            if self.calibrator is None:
                self.calibrator = Calibrator(self.weights, self.cache)
            estimate = self.calibrator(image, 'pinhole')
            metadata['calibration'] = estimate
            K, R = np.asarray(estimate['K'], float), np.asarray(estimate['R'], float)
            if (estimate.get('camera_model') != 'pinhole' or estimate.get('k1', 0) != 0
                    or K.shape != (3, 3) or R.shape != (3, 3)
                    or not np.isfinite(K).all() or not np.isfinite(R).all()
                    or min(K[0, 0], K[1, 1]) <= 0 or not np.allclose(K[2], [0, 0, 1])
                    or not np.allclose(R.T @ R, np.eye(3), atol=1e-5)
                    or not np.isclose(np.linalg.det(R), 1, atol=1e-5)):
                raise ValueError('invalid_pinhole_calibration')
            scalar_keys = ('roll_deg', 'pitch_deg', 'vfov_deg', 'roll_uncertainty_deg',
                           'pitch_uncertainty_deg', 'vfov_uncertainty_deg', 'focal_relative_uncertainty')
            if not np.isfinite([estimate[k] for k in scalar_keys]).all():
                raise ValueError('non_finite_calibration')
            notes = warnings(estimate)
            metadata['warnings'] = notes
            if 'large_camera_tilt' in notes or 'field_of_view_outside_expected_range' in notes:
                raise ValueError('camera_estimate_outside_experiment_limits')
            M, size, guard = canvas_plan(image.shape, subject.box, K, R, 0.)
            H = M @ K @ R.T @ np.linalg.inv(K)
            metadata.update({'correction_applied': True, 'output_size': list(size),
                             'canvas_matrix': M.tolist(), 'guard': guard,
                             'mapping': 'camera_rotation_homography'})
            return H, metadata
        except (ValueError, KeyError, TypeError, OSError, RuntimeError, ImportError) as error:
            reason = str(error) if isinstance(error, ValueError) else 'camera_calibration_' + type(error).__name__
            raise CameraCorrectionUnavailable(reason, metadata) from error


def normal_transform(image, subject=None, *, calibrator=None):
    """Single-image convenience entry; batch callers retain one NonGridTransform."""
    return NonGridTransform(calibrator=calibrator)(image, subject)

"""Extension point for future non-grid camera correction."""
import numpy as np


def normal_transform(image, subject=None):
    """Identity by default: no rotation, perspective, lens correction or resampling.

    Transforms return a matrix rather than a rendered intermediate image. The
    shared compositor later samples the original once for uniform framing.
    """
    return np.eye(3), {
        'method': 'non-grid-identity-v1',
        'action': 'identity',
        'correction_applied': False,
        'output_size': [image.shape[1], image.shape[0]],
        'warnings': [],
    }

"""Projection and real-source content masks, copied from the approved baseline."""
import cv2
import numpy as np

class CropUnavailable(ValueError):
    pass


def project(points, H):
    points = np.asarray(points, float).reshape(-1, 2)
    q = np.c_[points, np.ones(len(points))] @ np.asarray(H).T
    if not np.isfinite(q).all() or np.any(np.abs(q[:, 2]) < 1e-8):
        raise CropUnavailable('invalid_grid_projection')
    return q[:, :2] / q[:, 2:]


def content_mask(image):
    """Exclude substantial, nearly black full-edge letterbox bands only.

    Interior dark clothes never become holes in the valid image. Small dark
    edges or an almost entirely black image are not treated as letterboxing.
    """
    h, w = image.shape[:2]
    dark = image.max(axis=2) <= 20
    bounds = [0, 0, w, h]
    for axis, start_index, end_index in ((1, 1, 3), (0, 0, 2)):
        uniform = dark.mean(axis=axis) >= .995
        n = len(uniform)
        for reverse in (False, True):
            scan = uniform[::-1] if reverse else uniform
            count = int(np.argmin(scan)) if not scan.all() else n
            if max(5, int(n * .015)) <= count <= n * .3:
                bounds[end_index if reverse else start_index] = n-count if reverse else count
    mask = np.zeros((h, w), np.uint8)
    x1, y1, x2, y2 = bounds
    mask[y1:y2, x1:x2] = 255
    return mask, bounds

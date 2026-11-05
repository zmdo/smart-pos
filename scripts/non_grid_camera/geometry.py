"""Camera ray reprojection; no body-shape fitting or image generation.

R maps a level camera's rays into the photographed camera (GeoCalib convention).
The inverse correction maps distorted source pixels to a level pinhole camera.
"""
import cv2
import numpy as np

from scripts.body_scan.geometry import content_mask


def rotation(roll, pitch):
    """World/level → photographed camera, angles in radians."""
    cr, sr, cp, sp = np.cos(roll), np.sin(roll), np.cos(pitch), np.sin(pitch)
    return np.array([[cr, sr, 0], [-sr, cr, 0], [0, 0, 1.]]) @ np.array([[1., 0, 0], [0, cp, sp], [0, -sp, cp]])


def undistort(points, k):
    """Invert rd = ru * (1 + k*ru²) with Newton iteration, not a first-order guess."""
    p = np.asarray(points, float)
    rd = np.linalg.norm(p, axis=-1)
    ru = rd.copy()
    for _ in range(30):
        derivative = 1 + 3*k*ru**2
        if np.any(derivative <= .15):
            raise ValueError('non_monotonic_radial_model')
        step = (ru*(1+k*ru**2)-rd)/derivative
        ru -= step
        if np.max(np.abs(step), initial=0) < 1e-11:
            break
    if not np.isfinite(ru).all() or np.any(ru < 0) or np.max(np.abs(ru*(1+k*ru**2)-rd), initial=0) > 1e-7:
        raise ValueError('radial_inverse_did_not_converge')
    return p * np.divide(ru, rd, out=np.ones_like(rd), where=rd > 1e-12)[..., None]


def forward(points, K, R, k=0.):
    points = np.asarray(points, float).reshape(-1, 2)
    normalized = (points - K[:2, 2])/np.diag(K)[:2]
    undistorted = undistort(normalized, k)
    rays = np.c_[undistorted, np.ones(len(points))] @ R
    if np.any(rays[:, 2] <= .15):
        raise ValueError('camera_correction_crosses_horizon')
    return rays[:, :2]/rays[:, 2:] * np.diag(K)[:2] + K[:2, 2]


def inverse(points, K, R, k=0.):
    points = np.asarray(points, float).reshape(-1, 2)
    normalized = (points-K[:2, 2])/np.diag(K)[:2]
    rays = np.c_[normalized, np.ones(len(points))] @ R.T
    valid = rays[:, 2] > .15
    p = rays[:, :2]/np.maximum(rays[:, 2:], .15)
    radius2 = np.sum(p*p, axis=-1)
    valid &= (1+3*k*radius2 > .15) & (1+k*radius2 > .3)
    distorted = p * (1+k*radius2)[:, None]
    return distorted*np.diag(K)[:2]+K[:2, 2], valid


def jacobian(point, K, R, k):
    point = np.asarray(point, float)
    mapped = forward([point, point+[.1, 0], point+[0, .1]], K, R, k)
    return np.stack([(mapped[1]-mapped[0])/.1, (mapped[2]-mapped[0])/.1], axis=1)


def canvas_plan(shape, box, K, R, k):
    h, w = shape[:2]
    # Sample all four boundaries: a nonlinear warp cannot be bounded by four corners.
    x = np.linspace(0, w-1, 129); y = np.linspace(0, h-1, 129)
    border = np.concatenate([np.c_[x, x*0], np.c_[x, x*0+h-1], np.c_[y*0, y], np.c_[y*0+w-1, y]])
    center = (np.asarray(box[:2])+box[2:])/2
    determinant = np.linalg.det(jacobian(center, K, R, k))
    if determinant <= 0:
        raise ValueError('flipped_camera_transform')
    scale = 1/np.sqrt(determinant)
    mapped = forward(border, K, R, k)*scale
    low = np.floor(mapped.min(axis=0))-2
    high = np.ceil(mapped.max(axis=0))+2
    size = (high-low+1).astype(int)
    if np.any(size > 6000) or np.prod(size) > w*h*2.5:
        raise ValueError('excessive_camera_canvas')
    singular = []
    for x in np.linspace(box[0], box[2], 3):
        for y in np.linspace(box[1], box[3], 3):
            singular.append(np.linalg.svd(jacobian([x, y], K, R, k)*scale, compute_uv=False))
    singular = np.array(singular)
    metrics = {'max_local_anisotropy': float(np.max(singular[:, 0]/singular[:, 1])),
               'local_scale_variation': float(singular.max()/singular.min()),
               'center_area_scale': 1., 'uniform_scale': float(scale)}
    if metrics['max_local_anisotropy'] > 1.65 or metrics['local_scale_variation'] > 2.:
        raise ValueError('excessive_subject_deformation')
    M = np.array([[scale, 0, -low[0]], [0, scale, -low[1]], [0, 0, 1.]])
    return M, tuple(map(int, size)), metrics


def transform_points(points, K, R, k, M):
    p = forward(points, K, R, k)
    return p*M[0, 0]+M[:2, 2]


def render(source, box, calibration, radial=False):
    K = np.asarray(calibration['K'], float)
    R = np.asarray(calibration['R'], float)
    k = float(calibration.get('k1', 0)) if radial else 0.
    M, size, metrics = canvas_plan(source.shape, box, K, R, k)
    source_mask, bounds = content_mask(source)
    map_x = np.empty((size[1], size[0]), np.float32)
    map_y = np.empty_like(map_x)
    # Chunk the inverse mapping so large images have bounded temporary memory.
    for y0 in range(0, size[1], 128):
        yy, xx = np.mgrid[y0:min(y0+128, size[1]), :size[0]]
        p = np.c_[xx.ravel(), yy.ravel()]
        p = (p-M[:2, 2])/M[0, 0]
        q, valid = inverse(p, K, R, k)
        q[~valid] = -100
        map_x[y0:y0+len(yy)] = q[:, 0].reshape(xx.shape)
        map_y[y0:y0+len(yy)] = q[:, 1].reshape(xx.shape)
    x1, y1, x2, y2 = bounds
    sampled = cv2.copyMakeBorder(source[y1:y2, x1:x2], y1, source.shape[0]-y2,
                                 x1, source.shape[1]-x2, cv2.BORDER_REPLICATE)
    image = cv2.remap(sampled, map_x, map_y, cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)
    valid = cv2.remap(source_mask, map_x, map_y, cv2.INTER_NEAREST, borderMode=cv2.BORDER_CONSTANT)
    image[valid == 0] = (227, 234, 238)
    report = {**metrics, 'canvas_matrix': M.tolist(), 'output_size': list(size),
              'mapping': 'radial_inverse_then_camera_rotation' if radial else 'camera_rotation_homography',
              'source_content_bounds': bounds, 'valid_fraction': float(np.mean(valid > 0)),
              'applied_k1': k}
    if not radial:
        report['H_source_to_output'] = (M @ K @ R.T @ np.linalg.inv(K)).tolist()
    return image, valid, report

"""Long background-edge diagnostics; candidates require visual review."""
import cv2
import numpy as np

from .geometry import transform_points


def reference_lines(image, box):
    """Long line candidates outside the person; not proof of a shared wall plane."""
    h, w = image.shape[:2]
    edges = cv2.Canny(cv2.cvtColor(image, cv2.COLOR_BGR2GRAY), 60, 140)
    x1, y1, x2, y2 = np.asarray(box, int)
    pad = max(8, round(min(w, h)*.015))
    edges[max(0, y1-pad):min(h, y2+pad), max(0, x1-pad):min(w, x2+pad)] = 0
    edges[:5] = 0; edges[-5:] = 0; edges[:, :5] = 0; edges[:, -5:] = 0
    detected = cv2.HoughLinesP(edges, 1, np.pi/1440, 60,
                              minLineLength=max(60, int(min(w, h)*.2)), maxLineGap=12)
    if detected is None:
        return []
    candidates = []
    for line in sorted(detected[:, 0].astype(float), key=lambda p: -np.linalg.norm(p[2:]-p[:2])):
        dx, dy = line[2:]-line[:2]
        if abs(dx) < .3*abs(dy):
            axis = 'v'
        elif abs(dy) < .3*abs(dx):
            axis = 'h'
        else:
            continue
        center = (line[:2]+line[2:])/2
        duplicate = any(c['axis'] == axis and np.linalg.norm(center-np.mean(np.array(c['points']), axis=0)) < min(w, h)*.07 for c in candidates)
        if not duplicate:
            candidates.append({'axis': axis, 'points': line.reshape(2, 2).tolist()})
        if len(candidates) >= 24:
            break
    return candidates


def line_report(lines, calibration, mapping, radial):
    K, R = np.asarray(calibration['K']), np.asarray(calibration['R'])
    k = calibration['k1'] if radial else 0.
    M = np.asarray(mapping['canvas_matrix'])
    result = []
    for line in lines:
        p = np.asarray(line['points'])
        q = transform_points(p, K, R, k, M)
        def angle(points):
            dx, dy = points[1]-points[0]
            value = np.degrees(np.arctan2(dx, dy) if line['axis'] == 'v' else np.arctan2(dy, dx))
            return float((value+90) % 180-90)
        curve = transform_points(np.linspace(p[0], p[1], 33), K, R, k, M)
        result.append({**line, 'corrected_points': q.tolist(), 'corrected_polyline': curve.tolist(),
                       'before_deg': angle(p), 'after_deg': angle(q)})
    return result


def overlay(image, lines, corrected=False):
    canvas = image.copy()
    for index, line in enumerate(lines):
        points = np.asarray(line.get('corrected_polyline', line['corrected_points']) if corrected else line['points']).round().astype(int)
        color = (50, 150, 240) if line['axis'] == 'v' else (230, 150, 30)
        cv2.polylines(canvas, [points], False, color, 2, cv2.LINE_AA)
        cv2.putText(canvas, str(index+1), tuple(points[0]), cv2.FONT_HERSHEY_SIMPLEX, .5, color, 1)
    return canvas

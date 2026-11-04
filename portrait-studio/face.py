"""YuNet (OpenCV DNN) face detector: fast CPU pre-pass that proposes face boxes.

The vision model stays the fallback for faces this detector cannot see (heavy
profile, occlusion). Boxes are returned in source-image pixels, xyxy.
"""
import threading

import cv2
import numpy as np

DEFAULT_THRESHOLD = 0.75


class FaceDetector:
    def __init__(self, model_path, score_threshold=0.5, nms_threshold=0.3, top_k=5000):
        self._lock = threading.Lock()
        self._detector = cv2.FaceDetectorYN.create(
            str(model_path), "", (320, 320), score_threshold, nms_threshold, top_k)

    def detect(self, rgb, max_side=1600):
        image = np.ascontiguousarray(rgb)
        height, width = image.shape[:2]
        scale = 1.0
        if max(height, width) > max_side:
            scale = max_side / max(height, width)
            image = cv2.resize(image, (int(width * scale), int(height * scale)),
                interpolation=cv2.INTER_AREA)
        bgr = np.ascontiguousarray(image[:, :, ::-1])
        with self._lock:
            self._detector.setInputSize((bgr.shape[1], bgr.shape[0]))
            _, faces = self._detector.detect(bgr)
        results = []
        if faces is None:
            return results
        for face in faces:
            x, y, w, h = (float(v) for v in face[:4])
            landmarks = np.asarray(face[4:14], dtype=np.float32).reshape(5, 2)
            results.append({
                "box": [x/scale, y/scale, (x+w)/scale, (y+h)/scale],
                "score": float(face[-1]),
                "landmarks": (landmarks/scale).round(1).tolist(),
            })
        return results

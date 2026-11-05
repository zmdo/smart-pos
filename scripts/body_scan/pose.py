"""Cached YOLO11 pose with subject matching and cross-context agreement."""
import hashlib
import json
import os
from pathlib import Path

import numpy as np

from .landmarks import AlignmentUnavailable, compatible, landmarks
from .localization import expanded_roi, overlap

VERSION = 'shoulder-pose-v1'


class ShoulderPose:
    def __init__(self, weights=None, cache_dir=None, detector=None):
        self.weights = Path(weights) if weights else None
        self.cache_dir = Path(cache_dir) if cache_dir else None
        self.detector = detector
        self.model = None
        if detector is None and (self.weights is None or not self.weights.is_file()):
            raise AlignmentUnavailable('pose_weights_not_installed')
        self.model_hash = hashlib.sha256(self.weights.read_bytes()).hexdigest() if self.weights else 'injected-test-model'

    def _detect(self, image, size):
        if self.detector is not None:
            return self.detector(image, size)
        if self.model is None:
            from ultralytics import YOLO
            self.model = YOLO(str(self.weights))
        result = self.model.predict(image, imgsz=size, conf=.25, device=0, verbose=False)[0]
        return [{'box': b[:4].tolist(), 'confidence': float(b[4]), 'keypoints': k.tolist()}
                for b, k in zip(result.boxes.data.cpu().numpy(), result.keypoints.data.cpu().numpy())]

    def locate(self, image, box, H, view):
        parameters = {'version': VERSION, 'model_sha256': self.model_hash, 'shape': image.shape,
                      'box': list(box), 'H': np.asarray(H).tolist(), 'view': view}
        digest = hashlib.sha256(image.tobytes()+json.dumps(parameters, sort_keys=True).encode()).hexdigest()
        path = self.cache_dir/digest[:2]/(digest+'.json') if self.cache_dir else None
        if path and path.exists():
            try:
                cached = json.loads(path.read_text())
                measured = landmarks(cached['pose']['keypoints_source'], H, box, view)
                return {**cached, 'pose': measured, 'cached': True, 'new_inferences': 0}
            except (ValueError, KeyError):
                pass
        roi = expanded_roi(box, image.shape, .20)
        choices, attempts = [], []
        for mode, size in [('full', 640), ('roi', 640), ('roi', 1024), ('full', 1024)]:
            offset = [0, 0] if mode == 'full' else roi[:2]
            patch = image if mode == 'full' else image[roi[1]:roi[3], roi[0]:roi[2]]
            attempt = {'mode': mode, 'imgsz': size, 'roi': roi if mode == 'roi' else None, 'candidates': []}
            attempts.append(attempt)
            try:
                detected = self._detect(patch, size)
            except Exception as e:
                attempt['reason'] = 'pose_detector_'+type(e).__name__
                continue
            for candidate in detected:
                try:
                    b = np.asarray(candidate['box'], float)+[*offset, *offset]
                    kp = np.asarray(candidate['keypoints'], float).copy()
                    kp[:, :2] += offset
                    iou, containment = overlap(b, box)
                    if iou < .35 or containment < .65:
                        continue
                    pose = landmarks(kp, H, box, view)
                    item = {'pose': pose, 'attempt': len(attempts)-1,
                            'score': pose['confidence']+.15*iou, 'box': b.tolist()}
                    choices.append(item)
                    attempt['candidates'].append({'box': b.tolist(), 'confidence': pose['confidence'],
                                                  'anchor': pose['anchor'], 'torso_length': pose['torso_length']})
                except (ValueError, KeyError):
                    continue
            agreed = []
            for a in choices:
                supporters = [b for b in choices if b['attempt'] != a['attempt'] and compatible(a['pose'], b['pose'])]
                if supporters:
                    agreed.append((a, max(supporters, key=lambda b: b['score'])))
            if agreed:
                selected, corroborating = max(agreed, key=lambda pair: (pair[0]['score']+pair[1]['score'], pair[0]['score']))
                a, b = selected['pose'], corroborating['pose']
                result = {'pose': a, 'cached': False, 'new_inferences': len(attempts),
                          'version': VERSION, 'model_sha256': self.model_hash, 'attempts': attempts,
                          'selected_attempt': selected['attempt'], 'corroborating_attempt': corroborating['attempt'],
                          'agreement': {'torso_relative_difference': abs(a['torso_length']-b['torso_length'])/min(a['torso_length'], b['torso_length']),
                                        'anchor_distance_fraction': float(np.linalg.norm(np.asarray(a['anchor'])-b['anchor'])/min(a['torso_length'], b['torso_length']))}}
                if path:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    tmp = path.with_suffix('.'+str(os.getpid())+'.tmp')
                    tmp.write_text(json.dumps(result, ensure_ascii=False, indent=2))
                    tmp.replace(path)
                return result
        error = AlignmentUnavailable('shoulder_pose_not_reliable_across_contexts')
        error.attempts = attempts
        raise error

"""Lazy SAM2 adapter, detached from the old experimental rendering script."""
import os

import cv2
import numpy as np


class SamSegmenter:
    def __init__(self):
        self.model = None
        self.last_fallback = None

    def __call__(self, image, boxes):
        self.last_fallback = None
        try:
            import torch
            if self.model is None:
                from sam2.build_sam import build_sam2
                from sam2.sam2_image_predictor import SAM2ImagePredictor
                checkpoint = os.environ.get('CASE_SAM', '/root/autodl-fs/portrait-studio/models/sam2.1_hiera_base_plus.pt')
                config = os.environ.get('CASE_SAM_CONFIG', 'configs/sam2.1/sam2.1_hiera_b+.yaml')
                self.model = SAM2ImagePredictor(build_sam2(config, checkpoint, device='cuda'))
            masks = []
            with torch.inference_mode():
                self.model.set_image(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))
                for box in boxes:
                    candidates, _, _ = self.model.predict(box=np.array(box, dtype=np.float32), multimask_output=True)
                    mask = candidates[int(np.argmax([c.sum() for c in candidates]))]
                    masks.append(cv2.morphologyEx(mask.astype(np.uint8), cv2.MORPH_CLOSE,
                                                 np.ones((7, 7), np.uint8)).astype(bool))
            return masks
        except Exception as error:
            # Preserve the approved conservative YOLO exclusion fallback. The
            # localizer rejects rectangular masks on VLM-only / strict routes.
            self.last_fallback = type(error).__name__
            masks = []
            for x1, y1, x2, y2 in boxes:
                mask = np.zeros(image.shape[:2], bool)
                mask[max(0, int(y1)):min(image.shape[0], int(y2)),
                     max(0, int(x1)):min(image.shape[1], int(x2))] = True
                masks.append(mask)
            return masks

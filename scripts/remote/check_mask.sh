#!/bin/bash
set -uo pipefail
cd /root/apps/portrait-studio
echo '=== segmentation png size ==='
.venv/bin/python -c "
from PIL import Image
im = Image.open('/root/autodl-fs/portrait-studio/jobs/3ed065998c7dd3c2bab4f1aa/output/segmentation-0001.png')
print('mask size', im.size, im.mode)
"
echo '=== sam2 predictor postprocess ==='
sed -n '1,80p' vendor/sam2/sam2/sam2_image_predictor.py 2>/dev/null || find vendor -name 'sam2_image_predictor.py' | head
echo '=== apply_postprocessing refs ==='
grep -rn "apply_postprocessing" vendor/sam2/sam2/*.py | head -20

#!/bin/bash
set -uo pipefail
D=/root/autodl-fs/portrait-studio/models
cd "$D"
try() {
  name=$1; url=$2
  code=$(timeout 40 curl -sL -o "$name.tmp" -w '%{http_code}' "$url")
  size=$(stat -c%s "$name.tmp" 2>/dev/null || echo 0)
  echo "$name -> HTTP $code size=$size src=$url"
  if [ "$code" = "200" ] && [ "$size" -gt 50000 ]; then mv "$name.tmp" "$name"; else rm -f "$name.tmp"; fi
}
try yunet.onnx "https://ghproxy.net/https://raw.githubusercontent.com/opencv/opencv_zoo/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx"
try yunet2.onnx "https://raw.githubusercontent.com/opencv/opencv_zoo/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx"
try yunet3.onnx "https://hf-mirror.com/opencv/face_detection_yunet/resolve/main/face_detection_yunet_2023mar.onnx"
try yunet4.onnx "https://huggingface.co/spaces/opencv/face_detection_yunet/resolve/main/face_detection_yunet_2023mar.onnx"
ls -la "$D"
echo '--- pip index candidates ---'
timeout 20 curl -s -o /dev/null -w 'aliyun pypi %{http_code}\n' https://mirrors.aliyun.com/pypi/simple/mediapipe/

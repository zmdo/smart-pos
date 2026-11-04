#!/bin/bash
set -uo pipefail
V=/root/apps/portrait-studio/.venv/bin
"$V/python" - <<'PY'
import importlib
for m in ("docx", "pypdf", "pillow_heif", "cv2", "numpy", "PIL", "httpx", "fastapi"):
    try:
        mod = importlib.import_module(m)
        print("OK  ", m, getattr(mod, "__version__", ""))
    except Exception as e:
        print("FAIL", m, e)
PY

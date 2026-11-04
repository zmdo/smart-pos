#!/bin/bash
set -uo pipefail
V=/root/apps/portrait-studio/.venv/bin
"$V/python" -V
echo '--- packages ---'
"$V/pip" list 2>/dev/null | grep -Ei 'fastapi|uvicorn|pillow|numpy|opencv|httpx|docx|pypdf|heif|torch|multipart|pymupdf|fitz|imagehash'
echo '--- apps ---'
ls /root/apps
echo '--- supervisor init ---'
ps aux | grep -c '[u]vicorn'

#!/bin/bash
set -uo pipefail
rm -rf /tmp/std_flat && mkdir -p /tmp/std_flat
for d in /tmp/std/a0*; do
  base=$(basename "$d")
  id=${base%%_*}
  cp "$d/sheet.jpg"  "/tmp/std_flat/${id}_sheet.jpg"  2>/dev/null || true
  cp "$d/before.jpg" "/tmp/std_flat/${id}_before.jpg" 2>/dev/null || true
  cp "$d/after.jpg"  "/tmp/std_flat/${id}_after.jpg"  2>/dev/null || true
  cp "$d/meta.json"  "/tmp/std_flat/${id}_meta.json"  2>/dev/null || true
done
ls -la /tmp/std_flat

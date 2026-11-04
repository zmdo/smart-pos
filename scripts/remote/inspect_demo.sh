#!/bin/bash
set -uo pipefail
cd /root/autodl-fs/qa/demo-cases || exit 1
echo '=== top ==='
ls -la
echo '=== dirs (depth 3) ==='
find . -maxdepth 3 -type d -not -path '*/__MACOSX*' | sort
echo '=== per-dir file counts ==='
find . -maxdepth 3 -type d -not -path '*/__MACOSX*' -not -path '.' | while read -r d; do
  n=$(find "$d" -maxdepth 1 -type f | wc -l)
  [ "$n" -gt 0 ] && printf '%4d %s\n' "$n" "$d"
done
echo '=== by extension ==='
find . -type f -not -path '*/__MACOSX*' | sed 's/.*\.//' | tr 'A-Z' 'a-z' | sort | uniq -c | sort -rn

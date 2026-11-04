#!/bin/bash
set -uo pipefail
: > /tmp/mem.log
for i in $(seq 1 150); do
  line=$(nvidia-smi --query-gpu=memory.used,utilization.gpu --format=csv,noheader,nounits | tr -d ' ')
  echo "$(date +%s),$line" >> /tmp/mem.log
  sleep 1
done

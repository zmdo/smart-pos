#!/bin/bash
set -euo pipefail
# Default is the single-person back view used to compare the old/new algorithm.
bash "$(dirname "$0")/run_grid.sh" "${1:-a0015}"

#!/bin/bash
set -euo pipefail
exec "$(dirname "${BASH_SOURCE[0]}")/../run.sh" cover-compare "$@"

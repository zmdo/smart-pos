#!/usr/bin/env bash
set -euo pipefail
cd /root/apps/case-studio
mkdir -p run /root/autodl-fs/case-studio/logs
export PATH="/root/apps/portrait-studio/.venv/bin:$PATH"
if supervisorctl -c supervisord.conf status >/dev/null 2>&1; then
  supervisorctl -c supervisord.conf restart case-studio
else
  supervisord -c supervisord.conf
fi

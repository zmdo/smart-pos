#!/usr/bin/env bash
set -euo pipefail
cd /root/apps/portrait-studio
mkdir -p run /root/autodl-fs/portrait-studio/logs
export PATH="/root/apps/portrait-studio/.venv/bin:$PATH"
if supervisorctl -c supervisord.conf status >/dev/null 2>&1; then
  supervisorctl -c supervisord.conf restart portrait-studio
else
  supervisord -c supervisord.conf
fi


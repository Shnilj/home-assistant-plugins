#!/usr/bin/env bash
set -euo pipefail

OPTIONS="/data/options.json"

if [ -f "${OPTIONS}" ]; then
    export LOG_LEVEL="$(jq -r '.log_level // "info"' "${OPTIONS}")"
fi

export PORT="${PORT:-8096}"
export PYTHONPATH="/opt/stash"
export PYTHONUNBUFFERED=1

cd /opt/stash
exec python3 -m app.main

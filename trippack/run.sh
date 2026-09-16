#!/usr/bin/env bash
set -euo pipefail

OPTIONS="/data/options.json"

if [ -f "${OPTIONS}" ]; then
    export LOG_LEVEL="$(jq -r '.log_level // "info"' "${OPTIONS}")"
fi

export PORT="${PORT:-8097}"
export PYTHONPATH="/opt/trippack"
export PYTHONUNBUFFERED=1

cd /opt/trippack
exec python3 -m app.main

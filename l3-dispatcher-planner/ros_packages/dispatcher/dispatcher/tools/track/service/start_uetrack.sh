#!/usr/bin/env bash
set -euo pipefail
cd /opt/tracking
if [[ -n "${LX_TRACK_CPUS:-}" ]]; then
  exec taskset -c "$LX_TRACK_CPUS" python -m uvicorn uetrack_api:app --host 127.0.0.1 --port 2250 --workers 1
fi
exec python -m uvicorn uetrack_api:app --host 127.0.0.1 --port 2250 --workers 1

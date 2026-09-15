#!/bin/bash
# Entity: devel — launch the l3 telemetry-bridge container and verify the
# zenoh telemetry plane end-to-end (agent-station-channels.spec.md v8).
# Usage: bash tests/telemetry-bridge/run_telemetry_test.sh   (from the l3 project root)
set -euo pipefail

IMG="l3-dispatcher-planner-real/amd64-ubuntu20.04-cuda0.0.0:latest"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ROS_MASTER_PORT="${ROS_MASTER_PORT:-29511}"

if [[ -n "$(ss -H -ltn "sport = :$ROS_MASTER_PORT")" ]]; then
  printf 'ROS master port %s is already in use\n' "$ROS_MASTER_PORT" >&2
  exit 1
fi

exec docker run --rm --network host \
  -e "ROS_MASTER_PORT=$ROS_MASTER_PORT" \
  -e "ROS_MASTER_URI=http://127.0.0.1:$ROS_MASTER_PORT" \
  -e ROS_HOSTNAME=127.0.0.1 \
  -e "ZENOH_ROUTER=${ZENOH_ROUTER:-tcp/public_zenohd_router:7447}" \
  -v "$ROOT/ros_packages:/workspace/src/ros_packages:ro" \
  -v "$ROOT/bringup:/workspace/src/bringup:ro" \
  -v "$ROOT/tests:/workspace/src/tests:ro" \
  -v "$ROOT/.artifacts/devel:/workspace/devel:ro" \
  -v "$ROOT/.artifacts/bench-workdir:/tmp/telemetry-bridge:rw" \
  --entrypoint bash "$IMG" -c '
    source /opt/ros/noetic/setup.bash
    source /workspace/devel/setup.bash
    export ROS_PACKAGE_PATH=/workspace/src:$ROS_PACKAGE_PATH
    python3 -u /workspace/src/tests/telemetry-bridge/verify_telemetry.py
  '

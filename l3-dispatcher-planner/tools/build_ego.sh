#!/usr/bin/env bash
set -euo pipefail
repo_root="$(cd "$(dirname "$0")/.." && pwd)"
build_root="${1:?usage: build_ego.sh external_build_directory}"
shift
mkdir -p "$build_root/src"
build_root="$(cd "$build_root" && pwd)"
case "$build_root/" in "$repo_root/"*) echo 'Build outside the source tree.' >&2; exit 2;; esac
for package in quadrotor_msgs traj_utils vis_utils; do
  ln -sfn "$repo_root/ros_packages/utils/$package" "$build_root/src/$package"
done
ln -sfn "$repo_root/ros_packages/planner/ego_planner/plan_manage" "$build_root/src/ego_planner"
ln -sfn "$repo_root/ros_packages/dispatcher" "$build_root/src/dispatcher"
exec catkin_make -C "$build_root" -j2 -DPYTHON_EXECUTABLE=/usr/bin/python3 -DCMAKE_BUILD_TYPE=Release "$@"

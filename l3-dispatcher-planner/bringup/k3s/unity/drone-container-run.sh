#!/usr/bin/env bash
# Entity: drone-container
# Invoked: k3s Unity deployment command
# 常驻进程与 stdout 心跳同生共死；保留信号和真实退出码。
set -u
"$@" &
child=$!
heartbeat() {
  while kill -0 "$child" 2>/dev/null; do
    printf '[%s] heartbeat\n' "${SIM_COMPONENT:-sim}"
    sleep 10
  done
}
heartbeat &
pulse=$!
stop() {
  kill -TERM "$child" "$pulse" 2>/dev/null || true
  wait "$child" 2>/dev/null || true
  exit 143
}
trap stop TERM INT
wait "$child"
code=$?
kill -TERM "$pulse" 2>/dev/null || true
wait "$pulse" 2>/dev/null || true
exit "$code"

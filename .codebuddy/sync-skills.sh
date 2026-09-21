#!/usr/bin/env bash
# Entity: station-host
# Invoked: directly by the operator
#
# sync-skills — 把本仓库 .trae/skills 的技能同步进 CodeBuddy 用户级技能目录。
#
# 用途：CodeBuddy 只从 ~/.codebuddy/skills/ 加载用户级技能；本仓库的技能
# 维护在 .trae/skills/（以及预留的 .agent/skills/）。本脚本幂等复制，重复
# 运行即完成同步（源更新后重跑一次即可）。
#
# 用法：bash .codebuddy/sync-skills.sh
# 覆盖目标目录：CODEBUDDY_SKILLS_DIR=<dir> bash .codebuddy/sync-skills.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="${CODEBUDDY_SKILLS_DIR:-${HOME}/.codebuddy/skills}"

SOURCES=(
  "${ROOT}/.trae/skills"   # 项目级（本仓库）
  "${ROOT}/.agent/skills"  # 项目级（预留）
)

mkdir -p "${DEST}"
count=0
for src in "${SOURCES[@]}"; do
  [[ -d "${src}" ]] || continue
  for skill in "${src}"/*/; do
    [[ -f "${skill}SKILL.md" ]] || continue
    name="$(basename "${skill}")"
    rm -rf "${DEST:?}/${name}"
    cp -r "${skill}" "${DEST}/${name}"
    echo "synced: ${name}  <-  ${skill}"
    count=$((count + 1))
  done
done

echo "total: ${count} skill(s) synced to ${DEST}"

# Unity 编译资源隔离方案

> 摘要：修复编译 Job 沿用业务 Pod 资源限制导致的 OOM 退出。

## 0. 元信息

- 日期：2026-10-14
- 目标路径：`l3-dispatcher-planner/tools/station-host-sim.py`、`bringup/k3s/unity/`
- 状态：编译资源修改已随后续完整 prepare 构建通过，未运行业务验收
- 关联文档：`design-unity-startup-config.md`

## 1. 背景与动机

用户执行 prepare 失败。已有 Pod 终态记录为 OOMKilled、退出码 137，编译容器限制为 4Gi；日志停止在 EGO 编译阶段。

## 2. 现状事实（问题清单）

- `l3-dispatcher-planner/tools/station-host-sim.py:309`：通用 pod 装配使用业务资源默认值。
- `l3-dispatcher-planner/tools/station-host-sim.py:382`：compile_manifest 未单独定义编译资源。
- `l3-dispatcher-planner/tools/build_ego.sh:23`：默认并行度为二，可经 L3_BUILD_JOBS 控制。

## 3. 目标与约束

为编译独立分配资源并降低峰值；保留构建缓存及失败日志。业务 Pod 资源不变，不启动服务，不重跑构建或验收；不新增转接器或兼容接口。

## 4. 方案决策

沿用 tools 和 bringup 目录架构及 station-host 命名规范。新增 SIM_BUILD_MEMORY_MIB、SIM_BUILD_JOBS，默认 8192 MiB、单任务；正整数校验。compile_manifest 显式设置资源，L3 编译用已有 L3_BUILD_JOBS 接口，Unity catkin 使用同源并行度。失败提示附各编译容器 termination reason 和退出码。

## 5. 迁移映射

编译沿用业务资源 → 独立编译资源：重写。L3/Unity 固定默认并行度 → 同源编译配置：统一。

## 6. 删除清单

移除 Unity 编译命令固定 -j2；编译 Job 不再继承业务 Pod 的 4Gi 上限。

## 7. 实施步骤

P0 落盘方案；P1 配置与 Job 装配；P2 失败诊断和说明。保持失败 Job 及缓存，回退仅撤销本方案改动。

## 8. 验收标准

按 AGENTS.md 统一声明，不运行测试、门禁、构建或验证性验收。后续获准后覆盖配置拒绝、编译 Job 资源及 OOM 提示，再由实际 prepare 确认构建结果。

## 9. 风险与对策

增大限制不保证主机有足够空闲内存；默认单任务降低峰值，可通过本地配置调整。不得把本次资源修复描述成编译已经成功。

## 10. 修改点清单汇总

- tools/station-host-sim.py：配置检查、编译专用资源、失败终态提示。
- bringup/k3s/unity/runtime.defaults.env：编译默认内存及并行度。
- bringup/k3s/unity/README.md：资源调整与失败排查说明。

后续用户明确授权构建验证；完整结果见 [Python 兼容修复方案](design-unity-python38-build.md)。单任务、8192 MiB 配置下完整 prepare 已成功退出。

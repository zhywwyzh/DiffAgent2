# 旧库 VLA 变动向新库收敛的交付决策

Status: implemented

日期：2026-09-26

本记录登记本轮两个决策：① 补注册 `navigation.vla_rotate`（旧库站端重扫腿的机上解析）；
② 对象导航终态语义按 DiffAgent2 旧版 2026-09-24 裁决同步进新库契约。
评估与方案全文（过程材料）见
[旧库 VLA 变动评估](../../../doc/l3-dispatcher-planner/iteration/design-dispatcher-vla-old-repo-drift.md) 与
[旧库 VLA 变动向新库迁移方案](../../../doc/l3-dispatcher-planner/iteration/design-dispatcher-old-repo-vla-convergence.md)。

## 决策 1：`navigation.vla_rotate` 补注册（候选 B）

**背景**：站端在目标 `visible=false` 时下发 `navigation.vla_rotate`（`yaw_delta_deg`）作为
有界重扫腿；DiffAgent2 旧版机上以同一 `FlightSkill` 实例双名注册（`flight.rotate` +
`navigation.vla_rotate`，`engine._skills`），而新库此前未注册该名（工具面仅 7 项），
站端重扫腿在新库会 `tool_not_registered`。

**决策**：取**候选 B**——在本库补注册，而非要求站端改用 `basic_flight.rotate`（候选 A）。
理由：① 站端现状即发该名，候选 B 不改跨仓接口；② 该名是 VLA 家族名，语义为
「站端编排的搜索旋转腿」，独立于基础飞行的 `basic_flight.rotate`；③ 保留旧库的
`(-360, 360]` 范围约束（`basic_flight.rotate` 无范围）。被替代的候选 A 记录在方案 §4.3。

**落地**：`tools/vla/catalog.py::vla_specs()` 增 `navigation.vla_rotate` ToolSpec；
`execution/composition.py::install_flight` 以同一 `RotateSkill` 实例双名注册；
`l3-tool-plane` §1 现行集合 7 → 8 项并重算 `revision`。

## 决策 2：对象导航终态语义同步

**背景**：DiffAgent2 旧版 2026-09-24 把对象导航终态由「对象质心 + `orientation_xyzw` 偏航」
改为「停靠对象所挂拓扑节点 + 节点→对象水平 bearing」（`orientation_xyzw` 仅对象自身朝向，
水平重合时作兜底锚点）。

**决策**：新库 `l3-scenegraph`（proposed）§2.1/§2.3/§5/G37 与 `l3-skill-contract` §11 按此
改写；**不改 `scene_nav` 家族实现**（归[场景图迁移方案](../../../doc/l3-dispatcher-planner/iteration/design-dispatcher-scenegraph-migration.md)
P1–P3）。

**落地**：`specs/proposed/inner/l3-scenegraph.spec.md`、`specs/implemented/inner/l3-skill-contract.spec.md`；
台账 `rest/dispatcher-deferred-dependencies.md` R09 与收口表、`rest/README.md` 索引同步。

## 验收证据（2026-09-26，经使用者许可）

- **运行时**：`python3 -m pytest l3-dispatcher-planner/tests`（排除 4 个 zenoh 收集失败基线：
  `ros/test_ego_cmd.py`、`tool-registry/test_connection_lease.py`、
  `tool-registry/test_control_plane_lifecycle.py`、`tool-registry/test_l4_rpc_contract.py`）
  → **168 passed / 1 failed**；唯一失败
  `test_core_boundary.py::test_import_closure_has_no_domain_or_ros` 为**既有基线**
  （`core/skill_router.py` 的 `dispatcher.tool_plane.model` import 与禁用前缀冲突，
  `core/` 未被本轮触碰），与 [2026-09-20 归档](2026-09-20-vla-waypoint-executor.md) 登记的
  同名失败一致。
- **静态**：`revision` = `sha256:32b34a601073402fdef66c6f097bc4073f7fb1ad595beeea296305b05cde1228`
  与 `l3-tool-plane` §1 记录一致；`navigation.vla_rotate` 与 `basic_flight.rotate` 指向同一实例；
  `py_compile` 通过；删除/旧表述零残留。

**已知边界**：站端重扫腿端到端验收待真机/仿真（`l4-agent` 为独立嵌套仓库，非本库跟踪物）。

# 旧库 VLA 变动向新库迁移 方案

> 摘要：依据[旧库 VLA 变动评估](design-dispatcher-vla-old-repo-drift.md) §4 的可承接项，按本库规范
> （`l3-migration-protocol` §2 归属裁决、`l3-package-layout` 命名/依赖、`l3-skill-contract`、
> `l3-tool-plane`、`specs/README.md` 生命周期）把下列内容承接进本库被跟踪物：
> ① 对象导航终态语义（旧库 2026-09-24）同步进 `l3-scenegraph`（proposed）与 `l3-skill-contract` §11；
> ② `navigation.vla_rotate` 归属裁决与处置；③ `l3-tool-plane` §1 描述注记；④ `rest` 台账 R05/R09。
> **站端（`l4-agent`）实现已在同版本**（且 `l4-agent/` 是父仓库忽略的独立嵌套仓库），
> **`mission_executive` 禁迁**（`l3-execution-seam` §1 / G10），均不在本方案范围。本方案为过程材料，非权威。

## 0. 元信息

| 项 | 值 |
|----|----|
| 日期 | 2026-09-26 |
| 目标路径 | `specs/proposed/inner/`、`specs/implemented/inner/`、`l3-dispatcher-planner/ros_packages/dispatcher/dispatcher/`、`doc/l3-dispatcher-planner/rest/` |
| 状态 | done（2026-09-26：P0/P1/P2 落地、测试同步、决策记录归档） |
| 关联文档 | 评估 [旧库 VLA 变动评估](design-dispatcher-vla-old-repo-drift.md)；[场景图迁移方案](design-dispatcher-scenegraph-migration.md)；`l3-migration-protocol`、`l3-package-layout`、`l3-skill-contract`、`l3-tool-plane`、`specs/README.md` |

### 0.1 范围裁定

1. **来源**：评估文档 §4 的「需同步 / 需裁决 / 描述性过期」三类项。
2. **边界**：只动本库被跟踪物（`l3-dispatcher-planner/`、`specs/`、`doc/`）；**不动 `l4-agent/`**
   （独立嵌套仓库，父仓库 `.gitignore` 的 `/l*/` 已忽略，`CODEBUDDY.md` §1 亦声明其为独立仓库）。
3. **硬约束**：契约先行（`l3-migration-protocol` §1）；无转接器；过期必删；不引入任务编号
   （`l3-core-boundary` B2/B7/B8）；工具名/参数改动登记为有意变更。

### 0.2 前置事实更正（对评估 §4.5）

- [x] 本库根下 `l4-agent/` 是**独立嵌套 git 仓库**（远程为内部 GitLab），父仓库 `.gitignore`
  第 3 行 `/l*/` 已忽略它（`git check-ignore -v l4-agent` 命中），**不被父仓库跟踪**。
- [x] 其 HEAD = `bac15a8`（分支 `station-inf`），与旧库子模块 `station_projects/l4-agent`
  **同一提交**；站端 VLA 实现（`vla/geometry.py` 含 VLA-Diff 云链、`vla/infer.py` 模型 I/O 审计、
  `vla/model_io_logging.py`、`flight/service.py` 重扫序列）**已在本库工作区**。
- [x] 站端 not-visible 重扫仍下发 `navigation.vla_rotate`
  （`l4-agent/src/copaw/station_sidecar/flight/service.py`）。
- [x] 结论：评估 §4.5「站端归外部仓库、本库 `l4-agent` 非最新」**不准确**，据实更正为
  「站端实现已同版本在库内工作区，但归独立仓库，非本方案改动对象」。

## 1. 背景与动机

评估确认：旧库机上 dispatcher 的 VLA 实现自 2026-09-19 起未再变（新库机上迁移未过期），
但旧库在**站端实现细节**与**对象导航终态**上继续演进。站端已在同版本（§0.2），无需再迁；
真正需要本库承接的是：**对象导航终态语义**（契约）、**`navigation.vla_rotate`**（机上缺口）、
以及**描述与台账**。本方案给出按本库规范的承接路径。

## 2. 现状事实（问题清单）

- [ ] `specs/proposed/inner/l3-scenegraph.spec.md` §2.1/§5/G37 与旧库 09-24 对象导航终态**直接冲突**
  （现文：终点=对象 `pos`、偏航由 `orientation_xyzw` 推出、多面体中心非航点；旧库现状：终点=所挂
  拓扑节点、偏航=节点→对象 bearing、`orientation_xyzw` 仅水平重合兜底）。详见评估 §4.1。
- [ ] `specs/implemented/inner/l3-skill-contract.spec.md` §11 的 `scene.navigate`「到达判据
  （位置 + 终端偏航双条件）」与终态偏航来源同冲突。
- [ ] `navigation.vla_rotate` 在本库全树 **0 命中**：`l3-tool-plane` §1 现行集合仅 7 项（六
  `basic_flight.*` + `navigation.vla_nav`），未注册该名，也未在台账登记；而站端仍下发该名
  （§0.2），故站端重扫腿在本库会 `tool_not_registered`（`l3-tool-plane` §2）。
- [ ] `specs/implemented/inner/l3-tool-plane.spec.md` §1 对 `navigation.vla_nav` 的站端几何描述
  未含 left/right 换 VLA-Diff 云链与意图参数 `{object, bearing}`。
- [ ] `doc/l3-dispatcher-planner/rest/dispatcher-deferred-dependencies.md` 的 R05/R09 未含
  09-24/09-25 的终态语义变更。

## 3. 目标与约束

- **目标**：
  1. 把 09-24 对象导航终态语义落进 `l3-scenegraph`（proposed）与 `l3-skill-contract` §11，
     作为[场景图迁移方案](design-dispatcher-scenegraph-migration.md) P0 的**前置修订**；
  2. 裁决 `navigation.vla_rotate` 归属并落地（补注册 / 站端改名 / 退役登记，三选一）；
  3. 补齐 `l3-tool-plane` §1 描述注记；
  4. 同步 `rest` 台账 R05/R09 与 `rest/README.md` 索引。
- **Non-Goals**：
  - 不改 `l4-agent/`（独立仓库；跨仓命名收敛由站端在其仓内完成）；
  - 不迁 `mission_executive`（`l3-execution-seam` §1 / G10）；不迁 uss_planner 后端；
  - **不实现 `scene_nav` 家族**（`scene.map_search`/`scene.navigate`/`scene_nav.graph.*` 的代码落地
    归[场景图迁移方案](design-dispatcher-scenegraph-migration.md) P1–P3，本方案只修订其 P0 契约）；
  - 不改 `navigation.vla_nav` 的 wire schema 与 `revision`（评估 §4.4）。
- **硬边界**：
  - 契约先行（`l3-migration-protocol` §1、G18）；无调用方不迁（§1）；
  - 禁止转接器 / 遗留垫片 / 注释桩（§4）；过期必删；
  - 工具名与参数改动登记为有意变更并给出兼容处置（§3、G21）。

## 4. 方案决策

### 4.1 归属裁决（`l3-migration-protocol` §2 顺序，命中即止）

| # | 待承接单元 | 命中条款 | 裁决 | 落点 |
|---|-----------|----------|------|------|
| 1 | 对象导航终态语义（停靠所挂拓扑节点 + 面向对象 bearing） | 属「下游执行/几何能力」的行为契约，当前无实现 | **契约同步**（不建桩） | `l3-scenegraph` §2.1/§5/G37、`l3-skill-contract` §11 |
| 2 | `navigation.vla_rotate`（站端重扫腿） | §2-② 只在 VLA 搜索流程中被调用 → 技能；但本库已有等价能力 `basic_flight.rotate` | **待裁决**：A 不恢复别名（站端改用 `basic_flight.rotate`）/ B 在 VLA 家族补注册 | 见 §4.3 |
| 3 | `l3-tool-plane` §1 站端几何描述 | 描述性 | **注记补齐** | `l3-tool-plane` §1 |
| 4 | `rest` 台账 R05/R09 | 迁移登记 | **台账同步** | `rest/` |

> 裁决 2 是唯一开放项。按 `l3-migration-protocol` §2「裁决不明时补契约，不得凭当轮执行者的判断
> 默认放行」，须由使用者确认候选 A/B 后再动代码。

### 4.2 命名与目录（`l3-package-layout`）

- **对象导航终态**：无新增文件，只改 `specs/`（`l3-scenegraph` 为 `proposed` 叶，
  `l3-skill-contract` 为 `implemented` 叶）。
- **`navigation.vla_rotate`（若走候选 B）**：
  - 发现面元数据落 `tools/vla/catalog.py` 的 `vla_specs()`（家族基础设施模块，不带家族前缀，
    `l3-package-layout` §2）；`tool_plane/registry.py::ToolRegistry.default()` 汇入顺序保持
    `flight_specs()` + `vla_specs()`。
  - 技能实现**不新增文件**：复用 `basic_flight.rotate` 已用的旋转技能实例（旧库同为
    `"navigation.vla_rotate": flight_skill` 同一实例双名注册）；不新增 `vla_rotate_skill.py`。
- **配置参数**：本方案**不新增参数**（`navigation.vla_rotate` 无参数；对象导航终态语义的参数
  已由 `l3-skill-contract` §11 的 `~scene_nav/*` 表承载）。

### 4.3 接口形态（裁决 2 的两个候选）

| 候选 | 形态 | 与本库规范的符合度 | 代价 |
|------|------|--------------------|------|
| **A（推荐）不恢复别名** | 站端重扫腿改用 `basic_flight.rotate`（`yaw_delta_deg`，required，无范围）；本库 `l3-tool-plane` §1 集合与 `revision` **不变** | 符合 `l3-migration-protocol` §4「禁止遗留垫片」与 `l3-tool-plane` §1「旧 wire 别名不恢复」先例（`navigation.scene_graph_nav`） | 需站端（`l4-agent`）改一处工具名（跨仓） |
| **B 补注册 VLA 家族名** | 在 `tools/vla/catalog.py` 增 `navigation.vla_rotate`：`yaw_delta_deg` `number`，`exclusiveMinimum -360`、`maximum 360`（与旧库 `tools/registry.py` 一致）；`completion=action_result`、`requires_perception=false`；`l3-tool-plane` §1 集合 → 8 项并重算 `revision` | 需使用者显式许可，否则违反「不恢复旧别名」先例 | 本库双名承载同一能力，长期冗余 |

- **候选 A 的兼容处置**：登记为有意变更——「`navigation.vla_rotate` 不恢复，站端改
  `basic_flight.rotate`」；本库未注册名一律 `tool_not_registered`（`l3-tool-plane` §2），
  站端改名完成前该腿 fail-closed，不静默成功（符合「禁止假成功」）。
- **候选 B 若获准**：`l3-tool-plane` §1 现行集合与 `revision` 必须同批更新（G24），
  且须说明「VLA 家族名」与「`basic_flight.rotate`」的关系（不得表述为旧别名转接）。

> **裁决（2026-09-26，使用者）**：取**候选 B**，已落地：
> `tools/vla/catalog.py::vla_specs()` 增 `navigation.vla_rotate` ToolSpec
> （`yaw_delta_deg` 限 `(-360, 360]`，`completion=action_result`、`requires_perception=false`）；
> `execution/composition.py::install_flight` 以同一 `RotateSkill` 实例双名注册
> （`basic_flight.rotate` + `navigation.vla_rotate`，对齐旧库 `engine._skills`）；
> `l3-tool-plane` §1 集合改 8 项、`revision` 重算为
> `sha256:32b34a601073402fdef66c6f097bc4073f7fb1ad595beeea296305b05cde1228`。
> 候选 A 未采纳。

### 4.4 需先改的契约（P0）

1. `specs/proposed/inner/l3-scenegraph.spec.md`：§2.1「多面体中心是内部图连接件，不是可下发的
   航点」→ 改为「所挂多面体中心是对象导航的终态航点」；§5「取对象路径」→ 终点 = 所挂拓扑节点、
   目标偏航 = 节点→对象水平 bearing、`orientation_xyzw` 仅水平重合兜底；G37 反向改写。
2. `specs/implemented/inner/l3-skill-contract.spec.md` §11：`scene.navigate` 的到达判据与终态
   偏航来源按上条改写。
3. `specs/implemented/inner/l3-tool-plane.spec.md` §1：`navigation.vla_nav` 描述补
   「left/right 由站端 VLA-Diff 云链解算；意图参数 2026-09-25 收敛为 `{object, bearing}`，
   wire 仍带 `prompt`（站端合成）」。
4. `doc/l3-dispatcher-planner/rest/dispatcher-deferred-dependencies.md`：R05 补「VLA 终态腿 +
   站端编排」现状；R09 补「对象导航终态=停靠所挂拓扑节点 + 面向对象 bearing」；同步
   `rest/README.md` 索引。

### 4.5 旧接口 → 删除（不保留）

- 不恢复 `navigation.scene_graph_nav` 等旧 wire 别名（`l3-tool-plane` §1 既有裁决）。
- 候选 A 下 `navigation.vla_rotate` 亦不恢复，不得以别名/转发模块/`__getattr__` 回流
  （`l3-package-layout` §5、G32；`l3-migration-protocol` §4）。

## 5. 迁移映射表

| 旧库（DiffAgent2 旧版） | 新库（本方案落点） | 动作 | 备注 |
|---|---|---|---|
| `scene_graph` 对象导航终态（`getPathToObjectWithId` 的 `aim_pos=father->center_` + face-object yaw） | `l3-scenegraph` §2.1/§5/G37 | 契约同步 | 不搬代码；实现归 scenegraph 迁移 P1–P3 |
| 对象导航到达/终态语义 | `l3-skill-contract` §11 | 契约同步 | 同上 |
| `navigation.vla_rotate`（`tools/registry.py`） | 候选 A：无；候选 B：`tools/vla/catalog.py` | 裁决 | 见 §4.3 |
| 站端 VLA 实现细节（`vla/geometry.py` 等） | — | **不迁** | 已在库内 `l4-agent` 工作区（独立仓库，§0.2） |
| `mission_executive` reach settle / post-yaw | — | **不迁** | 禁迁（G10） |

## 6. 删除清单

| 删除项 | 理由 |
|--------|------|
| `l3-scenegraph` §5 中「输出路径的终点是对象 `pos`」与「不保留面向父多面体兼容分支」的表述 | 被 09-24 裁决取代（有意变更） |
| `l3-scenegraph` G37 旧断言 | 同上 |
| `navigation.vla_rotate` 旧别名（候选 A 下） | 不恢复旧 wire 别名（`l3-migration-protocol` §4） |

> 本方案不删除任何生产代码（除候选 A 下站端改名由站端仓自行完成）。

## 7. 实施步骤（P0–P2）

### P0 — 契约与台账（契约先行）

- 范围：§4.4 的 4 项；裁决 2 的候选 A/B 待使用者确认。
- 行为不变式：零代码改动；`l3-tool-plane` §1 集合与 `revision` 在候选 A 下不变。
- 验收：G18 满足（`l3-scenegraph` 仍 `proposed` 及以上）；G21（有意变更登记）。
- 回退：`git checkout` 还原文档。

### P1 — `navigation.vla_rotate` 落地（依裁决）

- 范围：候选 A → 本库零改动（仅登记台账 + 站端改名由站端仓执行）；候选 B → 改
  `tools/vla/catalog.py` + `l3-tool-plane` §1 集合与 `revision` 重算。
- 行为不变式：不改变既有 7 工具行为；未注册名仍 `tool_not_registered`。
- 验收：候选 A → 站端改名后端到端可受理；候选 B → G24（集合与 `revision` 一致）。
- 回退：git。

### P2 — 描述注记与收口

- 范围：§4.4-3/4 的注记与台账；核对无旧别名回流。
- 验收：`l3-dispatcher-planner/` 全树对 `navigation.scene_graph_nav` /（候选 A 下）
  `navigation.vla_rotate` 零生产引用；G29–G32 不受影响。
- 回退：文档级回退。

> **执行记录（2026-09-26）**：P0/P1/P2 已全部执行——
> **P0**：`l3-scenegraph` §2.1/§2.3/§5/G37 与 `l3-skill-contract` §11 已按旧库
> 2026-09-24 终态语义改写（终点=所挂拓扑节点、aim 偏航=节点→对象 bearing、
> `orientation_xyzw` 仅对象自身朝向+水平重合兜底）；`rest` 台账 R09 同步、
> 收口表新增 vla_rotate 行、`rest/README.md` 两行索引更新。
> **P1**：见 §4.3 裁决记录（候选 B 落地）。
> **P2**：`l3-tool-plane` §1 站端几何注记已补（left/right 换 VLA-Diff 云链 +
> `bearing` 意图，l3 schema 不变）。
> **收口（2026-09-26，经使用者许可）**：测试断言已同步（`tests/tool-registry/`
> 与 `tests/basic-flight/` 的 7→8 工具集合、新 `revision`；新增
> `navigation.vla_rotate` 元数据/schema 用例）；`python3 -m pytest
> l3-dispatcher-planner/tests`（排除 4 个 zenoh 收集失败基线）→ **168 passed /
> 1 failed**，唯一失败为既有基线（`core/skill_router.py`，与 09-20 归档同名）。
> 决策记录已归档 `specs/implemented/architecture/2026-09-26-old-repo-vla-convergence.md`；
> 本方案置 **done**。已知边界：站端重扫腿端到端验收待真机/仿真。

## 8. 验收标准

> **统一声明**：除非使用者明确许可，否则跳过验收测试工作（`AGENTS.md` 硬性约束 §9）。

- [ ] G18：`l3-scenegraph` 存在且 `proposed` 及以上；本方案 §4.4 契约改动已落。
- [ ] G21：工具名/描述/契约字符串级 diff 与 §4.3 登记的有意变更一致。
- [ ] G23：零任务编号标识符。
- [ ] G24（候选 B 时）：发现面集合 == `l3-tool-plane` §1 集合，`revision` == 记录值。
- [ ] `navigation.scene_graph_nav` /（候选 A 下）`navigation.vla_rotate` 生产代码零命中。
- [ ] 台账 R05/R09 与 `rest/README.md` 索引一致。

## 9. 风险与对策

| 风险 | 影响 | 对策 |
|------|------|------|
| 裁决 2 未定就动手 | 造出「旧别名转接」，违 `l3-migration-protocol` §4 | P0 先裁决；未定前不注册、不改代码 |
| 候选 A 下站端未同步改名 | 站端重扫腿 `tool_not_registered`（fail-closed） | 登记跨仓收敛项；站端改名完成前该腿明确失败，不静默 |
| 候选 B 下集合与 `revision` 未同步 | G24 判负 | P1 同批重算并回填 §1 |
| 对象导航终态契约与 scenegraph 迁移方案 P0 冲突 | 两份 spec 漂移 | 本方案 §4.4 作为 scenegraph 迁移 P0 的前置修订，同一改动内落地 |
| 把站端实现当本库义务 | 误改独立仓库 | §0.1 边界 + §0.2 事实更正 |

## 10. 修改点清单汇总

| 文件 | 动作 | 说明 |
|------|------|------|
| `specs/proposed/inner/l3-scenegraph.spec.md` | 修改（P0） | §2.1/§5/G37 对象导航终态对齐 09-24 |
| `specs/implemented/inner/l3-skill-contract.spec.md` | 修改（P0） | §11 `scene.navigate` 到达判据/终态偏航来源 |
| `specs/implemented/inner/l3-tool-plane.spec.md` | 修改（P0/P2） | §1 注记；（候选 B）集合与 `revision` |
| `doc/l3-dispatcher-planner/rest/dispatcher-deferred-dependencies.md` | 修改（P0） | R05/R09 同步 |
| `doc/l3-dispatcher-planner/rest/README.md` | 修改（P0） | 索引同步 |
| `l3-dispatcher-planner/.../tools/vla/catalog.py` | 修改（仅候选 B） | 增 `navigation.vla_rotate` ToolSpec |
| `l3-dispatcher-planner/.../execution/composition.py` | 修改（仅候选 B） | `install_flight` 双名注册 `navigation.vla_rotate` |
| `l3-dispatcher-planner/tests/tool-registry/{test_vla_catalog,test_tool_registry,test_methods}.py` | 修改 | 8 工具集合 + 新 `revision` + vla_rotate 元数据/schema 用例 |
| `l3-dispatcher-planner/tests/basic-flight/test_flight.py`、`tests/core-boundary/test_vla_composition.py` | 修改 | 工具集合断言与文案同步 |
| `specs/implemented/architecture/2026-09-26-old-repo-vla-convergence.md` | 新增 | 决策记录（归档） |
| `doc/l3-dispatcher-planner/iteration/design-dispatcher-vla-old-repo-drift.md` | 修改 | §4.5 事实更正（站端已同版本） |
| 本文件 | 新增 | 迁移方案 |

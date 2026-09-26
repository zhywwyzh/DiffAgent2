# 旧库 VLA 变动评估与对新库影响

> 摘要：DiffAgent2 旧版 VLA 自新库迁移基线（新版 HEAD `2c42d6a`，2026-09-21）以来继续大改。
> **机上 dispatcher 的 VLA 实现未再变**（新库机上迁移未过期）；**站端 `l4-agent` 的 VLA
> 实现细节大改**（left/right 几何链换 VLA-Diff 云链、意图参数 `side`/`distance_m` → `bearing`、
> 新增模型 I/O 与 grounding 审计、重扫序列、看门狗）；**`mission_executive` / `scene_graph`
> 的到达与对象导航终态大改**（reach 改停稳判定并回补 post-yaw 收尾腿、对象导航停靠所挂拓扑
> 节点）。本评估给出新库需同步的契约、需裁决的缺口与无需动的部分。
> 本次只评估与登记，不改生产代码；后续 spec/代码改动按 §5 分期另立方案。

## 0. 元信息

| 项 | 值 |
|----|----|
| 日期 | 2026-09-26 |
| 目标路径 | `specs/implemented/inner/`、`specs/proposed/inner/`、`doc/l3-dispatcher-planner/rest/`（评估结论落点） |
| 状态 | done（评估）；§5 的 spec/代码改动待另立方案执行 |
| 关联文档 | [VLA 机上收窄方案](design-dispatcher-vla-waypoint-executor-migration.md)、[场景图迁移方案](design-dispatcher-scenegraph-migration.md)、[几何上移姊妹篇](design-dispatcher-vla-waypoint-ownership-and-station-grounding.md)、`specs/implemented/architecture/2026-09-20-vla-waypoint-executor.md` |

### 0.1 基线与证据口径

- **新库基线**：DiffAgent2 新版 HEAD `2c42d6a`（2026-09-21）。
- **旧库现状**：DiffAgent2 旧版内嵌 `diff-dockers` 子仓库，分支 `station-inf`，HEAD `ae4f71f`（2026-09-25）；
  工作区另有未提交改动（2026-09-26，见 §2.3.3）。
- **路径口径**：
  - `N/` = 新库 `l3-dispatcher-planner/ros_packages/dispatcher/dispatcher/`
  - `O/` = 旧库 `drone_projects/l3-dispatcher-planner/ros_packages/dispatcher/dispatcher/`
  - `S/` = 旧库 `station_projects/l4-agent/src/copaw/station_sidecar/`
- 行号仅作锚点，以符号为准。

## 1. 背景与动机

新库的 VLA 迁移在 2026-09-20/09-21 完成（机上收窄为航点执行器）。此后旧库 VLA 仍在演进，
需要判定：**新库的 VLA 契约、方案与机上实现是否已过期**。旧库 VLA 横跨三层，迁移边界不同：

| 层 | 旧库位置 | 新库归属 |
|----|----------|----------|
| 机上 dispatcher | `O/` | **本仓库目标**（`l3-dispatcher-planner/`） |
| 站端 | `S/` | 独立嵌套仓库 `l4-agent/`（父仓库 `.gitignore` 的 `/l*/` 忽略）；本库工作区已同版本 |
| 任务网关 / 场景图 | 旧库 `mission_executive/`、`ros_packages/scene_graph/` | 禁迁（`l3-execution-seam` §1 / G10）；`scene.*` 为新库目标集合（未实现） |

## 2. 现状事实（旧库 VLA 变动清单）

### 2.1 机上 dispatcher（`O/`）—— 未再变

- [x] `O/tools/vla/vla_skill.py`、`O/tools/registry.py`、`O/perception/base_policy.py` 的最后一次
  改动均为旧库提交 `c5195cf`（2026-09-19，即新库机上迁移所依据的形态）。
- [x] 旧库 `git diff c5195cf..HEAD -- drone_projects/l3-dispatcher-planner/ros_packages/dispatcher`
  **为空**：机上 VLA 实现自 09-19 起未再变。
- [x] 结论：新库 `N/tools/vla/`、`N/tool_plane/`、`N/perception/base_policy.py` 的机上迁移**未过期**；
  新库实现还在端口机制上更完善（`poll_result` 轮询、`advance_prompt` 端口）。

### 2.2 站端 `l4-agent`（`S/`）—— 实现细节大改

子模块 gitlink 由新库基线 `9b7889c` 演进到 `bac15a8`（分支 `station-inf`）。VLA 相关变更：

| 文件 | 变更量 |
|------|--------|
| `S/vla/geometry.py` | +426 |
| `S/vla/infer.py` | +263 |
| `S/vla/model_io_logging.py` | 新增 +159 |
| `S/vla_grounding_logging.py` | 新增 +86 |
| `S/flight/service.py` | +333 |
| `S/flight/scene_match.py` | +79 |
| `S/flight/models.py` | +15 |

具体实现细节：

- [x] **`S/vla/geometry.py`**：
  - 意图参数 `side`/`distance_m` → **`bearing`**（`derive_nav_mode(bearing)`）。
  - **left/right 接近策略换实现**：不再走移植自机上的 dense-window 链，改走 **VLA-Diff 云链**
    `_estimate_region_point_cloud_vla_diff`——ray-grid 优先、最近 `percent_point`（0.3）回落、
    **无 bbox margin、无 dense window**、`z` 取区域中值、raw depth（`pc_max_range` 10.0）；
    waypoint = `object + sign*lateral*left_world + default_forward*forward_world`，
    `lateral = max(half_w + max(d_side, half_w), min_side_lateral)`；新增默认
    `DEFAULT_MIN_SIDE_LATERAL_M = 1.2`（`LX_VLA_GEO_MIN_SIDE_LATERAL_M`）；`default_forward` 为
    VLA-Diff safe-radius 后撤（`safe_dis` 0.6，`mount_undo=False`，delta 留在对象世界系）。
    VLA-Diff 用 `scipy.cKDTree` 加速，站端用等价暴力最近点。
  - **above/front finalize 改为相对物体**：`default_vertical = default_z − object_z`，
    target = `object_pose + offsets`；去掉 `requested_distance` 处理。
- [x] **`S/vla/infer.py`**：新增**模型 I/O 审计**——每次模型调用（`search` / `bbox` /
  `bbox_fallback`）写一行 JSONL 到 `logs/vla_model_io/<首次记录时刻>_<pid>.jsonl`（含 prompt、
  `request_text`、请求/回复墙钟与 `latency_ms`、原始正文、解析结果、失败原因）；审计写失败只
  告警、不改推理语义；`search` 段 fail-closed 记 `search_error`。
- [x] **新增 `S/vla/model_io_logging.py`**（审计写入）与 **`S/vla_grounding_logging.py`**
  （`logs/vla_grounding.jsonl`：每轮用哪一帧、旋转腿数、终态决策、机端同域 `odom_yaw` /
  `yaw_rate`）。
- [x] **`S/flight/service.py`**：意图参数 `{object, bearing}`，任务文本取 `object`、wire `prompt`
  由 `object` 合成、下发前 `record.params = dict(grounded)` 整体替换（剥离 `bearing`，因 l3 准入
  `additionalProperties=False`）；geometry reader 加 `router=kv_zenoh_router()`（D1 回归修复）；
  **重扫序列改 `+x, −2x, −x×7`**（`_resweep_yaw_delta_deg`，`x=40°` 共 9 腿整圈覆盖）；新增
  grounding round 时序记录；scene-match LLM 兜底（`SCENE_MATCH_LLM` 环境开关，5 s 预算）；
  `vla_nav` step watchdog 90 s → 600 s。
- [x] **`S/flight/models.py`**：`navigation.vla_nav` 步骤标题补到达方位后缀（`_BEARING_ZH`，
  前/左/右/上；`behind`/`below`/`none` 不追加）。
- [x] **`S/flight/scene_match.py`**：scene 图导航的 LLM label 匹配兜底（确定性匹配未命中/歧义时
  的一次站侧 `scene_match` 角色调用，thinking-free，temperature 0）。

### 2.3 任务网关 / 场景图 —— 终态大改（禁迁 / 目标集）

- [x] **reach 完成判定改 settle detection**（旧库 `b1eb23f`，2026-09-25；归档
  `specs/implemented/architecture/2026-09-25-reach-settle-arrival.md`）：`REACH_EXEC` 在 planner
  批次终态后按「位置距离 ≤ `reach/settle_pos_thresh`(0.30 m)、速度 ≤ `reach/settle_vel_thresh`
  (0.15 m/s)、加速度 ≤ `reach/settle_acc_thresh`(0.30 m/s²)、yaw rate ≤
  `reach/settle_yaw_rate_thresh`(0.20 rad/s) 连续保持 `reach/settle_hold_time`(0.20 s)」判到达；
  删除 yaw 角度容差、有界重派、post-yaw 腿与 `reach_final_approach`/`reach_post_yaw_dispatched` 事件。
- [x] **对象导航终态改「停靠所挂拓扑节点 + 面向对象 bearing」**（旧库 `b1eb23f`；归档
  `specs/implemented/architecture/2026-09-24-object-nav-topo-terminal.md`）：`getPathToObjectWithId`
  返回 `aim_pos = father->center_`（所挂多面体中心），**不再**追加 `obj->pos` 为终态航点；终态
  偏航 = 该节点→对象的水平 bearing；水平重合时保留 `orientation_xyzw` 锚点、否则 yaw 持 0。
- [x] **`vla_nav` 意图参数改 `{object, bearing}`**（旧库 `ae4f71f`，2026-09-25；归档
  `specs/implemented/architecture/2026-09-25-vla-nav-bearing-intent-argument.md`）：删除意图面
  `prompt`/`side`/`distance_m`；**l3 wire 契约不变**（仍 `object`/`prompt`/`waypoint_world` +
  可选 `yaw`/`look_forward`，`prompt` 由站端合成）。
- [x] **新迁入 uss-nav 原版 planner**（旧库 `c8d7518`，2026-09-21）：新增 `planners/uss_planner/`
  包（约 +1.9 万行）与 `bringup/config/uss_planner.yaml`、launch；旧库 `proposed/inner/
  l3-planner-backend-uss.spec.md`。
- [x] **未提交 WIP（2026-09-26）**：在 settle 判定之后**回补 post-yaw 收尾腿**——目标携带终端
  yaw 且走 waypoint-nav 路由时，原地旋转到目标 yaw，直到误差 ≤ `reach/final_yaw_tolerance`
  （新增参数，默认 10°），新状态 `post_yaw_active_`。

## 3. 目标与约束

- **目标**：给出新库针对旧库 VLA 变动的「需同步 / 需裁决 / 无需动」清单与后续分期。
- **Non-Goals**：
  - 不改 `l4-agent`（站端 VLA 实现归外部仓库）；
  - 不迁 `mission_executive`（`l3-execution-seam` §1 / G10）；
  - 不迁 `uss_planner` 后端（属 planner 后端迁移，不在 VLA 评估内）。
- **硬边界**：
  - 契约先行（`l3-migration-protocol` §1）；禁止转接器；过期必删（不留注释桩/别名）。

## 4. 影响评估

### 4.1 需同步（新库现有契约与旧库现状冲突）

- [ ] `specs/proposed/inner/l3-scenegraph.spec.md`（**proposed**）与旧库 09-24 裁决直接冲突：

  | 新库现文 | 旧库 09-24 现状 |
  |----------|-----------------|
  | §2.1「多面体中心是**内部图连接件**，不是可下发的航点」 | 所挂多面体中心**就是终态航点** |
  | §5「输出路径的**终点是对象 `pos`**」 | 终点 = 所挂拓扑节点（`father->center_`） |
  | §5「目标偏航由对象 `orientation_xyzw` 推出」 | 偏航 = 节点→对象的水平 bearing；`orientation_xyzw` 仅水平重合兜底 |
  | G37「输出路径不含所挂多面体中心，且终点为对象位置」 | 语义反转 |

- [ ] `specs/implemented/inner/l3-skill-contract.spec.md` §11：`scene.navigate` 的「到达判据
  （位置 + 终端偏航双条件）」与终态偏航来源，需按 §2.3 的对象导航终态改写。

### 4.2 缺口 / 需裁决

- [ ] **`navigation.vla_rotate` 在新库完全缺失**（新库全树 0 命中）：旧库仍注册该工具
  （`O/tools/registry.py`，`yaw_delta_deg`，title "Rotate for VLA search"，`action_result`，家族
  `vla`），供站端在 `visible=false` 时下发重扫腿（`agent-station-channels` §3.13）。新库工具面
  只有 7 项（六 `basic_flight.*` + `navigation.vla_nav`），既未注册、也未登记为遗留项（对比
  `navigation.scene_graph_nav` 已在 `l3-tool-plane` §1 明确「不恢复」）。**站端重扫腿在新库会
  `tool_not_registered`**。需裁决：① 补注册；② 站端改用 `basic_flight.rotate` 并同步站端；
  ③ 明确退役并登记台账。
- [ ] `doc/l3-dispatcher-planner/rest/dispatcher-deferred-dependencies.md` 的 **R05**（VLA 终态）
  与 **R09**（对象导航）触发条件，应记入 §2.3 的终态语义变更。

### 4.3 描述性过期（建议补注，不构成契约冲突）

- [ ] `specs/implemented/inner/l3-tool-plane.spec.md` §1 对 `navigation.vla_nav` 的说明仍写
  「station 以累积云 + 位姿插值 + VLM bbox 解算 `waypoint_world`」——**left/right 已不是这条链**
  （改 VLA-Diff 云链，§2.2）；且未点明意图参数 09-25 已收敛为 `{object, bearing}`（wire 仍
  `prompt`，站端合成）。

### 4.4 无需动（已一致）

- [x] `navigation.vla_nav` **wire schema**（`object`/`prompt`/`waypoint_world` 必填 + `yaw`/
  `look_forward` 可选）、`completion=action_result`、`requires_perception=false`：与旧库
  `O/tools/registry.py` 现状一致 → `l3-tool-plane` §1 的 schema 与 `revision` **不改**。
- [x] 机上 VLA 技能形态（三裁决、无 REPLAN、单次下发、`poll_result` 驱动）：与旧库一致
  （新库更完善）。
- [x] far-push / 连续推理退役：旧库（`2c600b0`/`a77850f`）与新库一致。

### 4.5 范围外（登记，不在本评估动作内）

- [x] 站端 VLA 实现细节（VLA-Diff 云链、左右转、terminal yaw、bearing、审计文件、重扫序列）：
  归独立嵌套仓库 `l4-agent/`（父仓库 `.gitignore` 的 `/l*/` 忽略），本库工作区已同版本
  （HEAD `bac15a8`），**非本库跟踪物、非本方案改动对象**（更正见
  [迁移方案](design-dispatcher-old-repo-vla-convergence.md) §0.2）。
- [x] `uss_planner` 后端迁移：新库 planner 仍 EGO（`planner_ego_mode_value` /
  `publish_mode_burst`）；若要跟齐属 planner 后端迁移，单独立项。
- [x] reach settle / post-yaw：归 `mission_executive`（禁迁）；新库 VLA 完成由技能自持（终态腿），
  语义不冲突。

## 5. 建议后续分期

> 每期：范围 + 行为不变式 + 验收 + 回退。本节仅给方向，落地前按需另立方案。

### P0 — spec 同步（契约先行）

- 范围：改 `l3-scenegraph`（proposed）§2.1/§5/G37 与 `l3-skill-contract` §11（对象导航终态）；
  在 `l3-tool-plane` §1 补 left/right 链与 `bearing` 意图注记；同步 `rest` 台账 R05/R09。
- 行为不变式：不改生产代码路径。
- 验收：文档一致；`revision` 不变（wire 未变）。
- 回退：文档级回退。

### P1 — `navigation.vla_rotate` 裁决（待使用者定方向）

- 范围：按 §4.2 三选一；若补注册，需同批实现 + 测试并更新 `l3-tool-plane` §1 集合与 `revision`。
- 行为不变式：不改变既有 7 工具行为。
- 验收：站端重扫腿可被受理；未注册名仍 `tool_not_registered`。
- 回退：git。

## 6. 验收标准

> **统一声明**：除非使用者明确许可，否则跳过验收测试工作（`AGENTS.md` 硬性约束 §9）。

- [ ] §4.1/§4.2/§4.3 各项在新库 spec/台账中已同步或已登记裁决结论。
- [ ] 新库机上 `grep` 无 `vla_geometry` / `geometry_source` / `get_fast_rgb` 残留（承 09-20 归档）。
- [ ] `navigation.vla_nav` 的 `revision` 与 `l3-tool-plane` §1 记录值一致（本评估不改 schema）。

## 7. 风险与对策

| 风险 | 影响 | 对策 |
|------|------|------|
| `l3-scenegraph` 保持现状 | 未来实现 `scene.navigate` 时按过期语义落地 | P0 先同步契约 |
| `navigation.vla_rotate` 长期悬空 | 站端 not-visible 重扫在新库整链失败 | P1 显式裁决并登记 |
| 把站端实现细节当新库义务 | 误改新库以「跟齐」站端 | §4.5 明确归属外部仓库 |
| 依据旧库 `doc/iteration` 反推契约 | 以过程材料当权威 | 以 `specs/` 与本次证据链为准 |

## 8. 修改点清单汇总

| 文件 | 动作 | 说明 |
|------|------|------|
| `specs/proposed/inner/l3-scenegraph.spec.md` | 修改（P0） | §2.1/§5/G37 对象导航终态对齐 09-24 |
| `specs/implemented/inner/l3-skill-contract.spec.md` | 修改（P0） | §11 `scene.navigate` 到达判据/终态偏航来源 |
| `specs/implemented/inner/l3-tool-plane.spec.md` | 修改（P0，描述性） | §1 补 left/right 链与 `bearing` 意图注记 |
| `doc/l3-dispatcher-planner/rest/dispatcher-deferred-dependencies.md` | 修改（P0） | R05/R09 触发条件同步 |
| `l3-dispatcher-planner/.../tools/vla/` + `tool_plane/` | 待裁决（P1） | 视 `navigation.vla_rotate` 裁决结果 |
| 本文件 | 新增 | 评估归档 |

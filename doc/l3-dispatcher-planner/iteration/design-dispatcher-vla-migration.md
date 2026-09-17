# dispatcher VLA 技能迁移方案

> 摘要：把 DiffAgent2 旧版的 `navigation.vla_nav`（VLA 哑执行器）迁入新版
> `l3-dispatcher-planner/`。新库保持「station 下发 grounded detection、板上零 VLM、
> fail-closed 三态、far_push/depth_match_ok/REPLAN 链」语义，接入新版动作账务
> （SkillRouter / ActionGate / WaypointExecution）与工具发现面；`geometry.py`
> 按用户要求保留在 `tools/vla/` 下并标注「vla 专用几何逻辑」，不通用化。
> 依据：旧库当前 HEAD（`station-inf`，`636ecc6`）；台账快照 `1b5fef5` 后 vla 目录再经
> `a77850f` / `acdffc9` / `7bcc999` 调整（见 §2 新增事实），证据一律以当前 HEAD 为准；
> rest 台账 R05/R07；[工具名与业务语义迁移遗留项](../../rest/task-id-to-tool-name-deferred.md)。

## 0. 元信息

| 项 | 值 |
|----|----|
| 日期 | 2026-09-17 |
| 目标路径 | `l3-dispatcher-planner/ros_packages/dispatcher/dispatcher/tools/vla/` |
| 状态 | proposed |
| 关联文档 | [基础飞行方案](design-dispatcher-basic-flight-migration.md)、[l3-l4 RPC 对接方案](design-dispatcher-l4-rpc-integration.md)、[l3-skill-contract.spec.md](../../../specs/implemented/inner/l3-skill-contract.spec.md)、[l3-tool-plane.spec.md](../../../specs/implemented/inner/l3-tool-plane.spec.md)、[l3-migration-protocol.spec.md](../../../specs/implemented/inner/l3-migration-protocol.spec.md)、[rest 台账](../rest/dispatcher-deferred-dependencies.md) |

## 1. 背景与动机

- 新版已完成核心、RPC、基础飞行的迁移与接线，工具发现面当前恰为六个
  `basic_flight.*` 动作（`l3-tool-plane.spec.md` §1）；完整能力仍缺场景导航与 VLA。
  VLA 是用户明确「继续使用原始 tool 名 `navigation.vla_nav`」的能力
  （[task-id-to-tool-name-deferred.md](../../rest/task-id-to-tool-name-deferred.md)），
  属待迁移项而非删除项。
- rest 台账 R05 记录「VLA 专属重规划（REPLAN）与记录读取仍未接入，旧 `arm_action`
  仅作历史线索」；R07 记录「`thinking_debug_dir` 无生产消费者」。本方案即在既有
  ActionGate/SkillHost 动作账务之上迁入 VLA 技能，数字面收敛前先落地技能语义。
- 用户明确两点约束：① `geometry.py` 保留在 `tools/vla/` 技能目录下，文件头标注
  「vla 专用几何逻辑」（不同能力按各自语义调几何，不通用、不抽成跨域共享服务）；
  ② 不恢复 first 系列首帧功能（旧 `first_rgb/first_bbox/first_frame`）。

## 2. 现状事实（问题清单）

> 证据路径：`O/` = 旧库根 `diff-dockers/drone_projects/l3-dispatcher-planner/ros_packages/dispatcher/dispatcher/`；
> `N/` = 新库根 `l3-dispatcher-planner/ros_packages/dispatcher/dispatcher/`。

- [ ] 新库无 VLA 技能与工具面：`N/tools/` 只有 `flight/` 家族；`l3-tool-plane.spec.md#L27-L32`
      生产工具集合为六个 `basic_flight.*`，`revision` 固定。
- [ ] 新库 `perception/base_policy.py` 已完整保留 VLA 几何所需全部原语：
      `build_world_frame_for_image_stamp`（L798）、`_planar_axes_from_bearing`（L980）、
      `_build_region_from_bbox`（L1339）、`bbox_candidate_to_body_incremental_waypoints`（L1392）、
      `_publish_candidate_debug_points`（L1661）、`_finalize_waypoint_candidate`（L1690）、
      `_estimate_region_point_depth`（L1771）、`_estimate_waypoint_candidate_for_region`（L2580）、
      `_cloud_depth_ranges_agree`（L2650）、`_select_nearest_geometry_candidate`（L2658）、
      `_geometry_safe_distance`（L2667）、`_candidate_with_safe_distance`（L2673）、
      `pixel_to_world`（L2720）、`_publish_p2w_marker`（L3016）。但 `N/engine.py` 仅注入
      `get_frame_snapshot`（L37/L44），**未把这些几何原语暴露给技能侧**；`N/core/` 对
      `base_policy|geometry|pixel_to_world` 均无引用——VLA 需要一条「几何原语注入」通路。
- [ ] 新库技能宿主为飞行专属：`N/execution/skill_host.py::DispatcherFlightHost`（含
      `start_goal`/`poll_result`/`fail_sequence`/`publish_phase`）与
      `N/services/flight_motion.py::FlightMotion`（多目标 begin→NEW_ACTION 循环）。
      `N/tools/skill_api.py::SkillHost` 已声明通用端口 `latest_frame / get_fast_rgb /
      arm_action / send_task_goal / consume_head_prompt / advance_prompt / stash_task_result /
      capture_task_generation / task_generation_valid`（L73-L107），但飞行宿主未实现
      frames 端口——VLA 需要自己的宿主组合（帧 + 几何 + 动作账务）。
- [ ] `N/core/tool_workflow.py#L52` 已有 `requires_perception and not input_ready() →
      chain_not_ready` 前置门；`N/engine.py#L228/L292` 分发时对
      `requires_perception` 技能就绪检查。VLA 置 `requires_perception=True` 可直接复用。
- [ ] R05 旧版读取链：`O/vla_skill.py`（现 443 行）`on_action_result`（L258-301）直读
      `host.pending_action.replan_cmd` 决定 REPLAN；旧 `O/engine.py:574` 的 prompt_raw
      下发行已随 RPC 重构漂移、不再相关。新版不能读宿主 `ActionGate.pending_action`
      私有（台账接入顺序），须技能自有 REPLAN 状态。
- [ ] 旧 VLA 语义链（须逐字对齐）：`_consume_grounded_detection` 的 bbox_1000→像素换算、
      visible=false 与 odom 对齐失败的 fail-closed 三态（invalid_grounded_bbox /
      target_not_visible / odom_stamp_unavailable）；`_compute_waypoint_from_detection`
      的 far_push（`depth_match_ok=False` 沿机头 5m）、`search_success_distance_thresh=0.3m`
      接近判定、`_dispatch_waypoint` 内联塑形（高度 clamp 0~1.8、mode_burst）。
- [ ] 旧 vla_nav 工具面（`O/tools/registry.py#L36-L74`）：必填 `object/prompt/bbox_1000/
      image_stamp`，可选 `side/distance_m/visible/finish/provider/image_width/image_height`，
      completion=`workflow_result`，带 `task_id=0`（新版 ToolSpec 无此字段，须去编号）。
- [ ] R07 调试图目录：旧多图思考保存链已随 VLM 迁云删除（`vla_skill.py` 收缩至 443 行，
      旧 `L886` 链不复存在）；旧库 `O/engine.py#L277-L281` 与新版
      `N/core/telemetry.py#L69-L73` 的 `thinking_debug_dir`/`last_thinking_debug_dir`
      双侧均成「仅创建、无消费者」孤儿——归属裁决由「迁入技能」改为「删孤儿 + 台账关门」。
- [ ] first 系列：旧 `first_rgb/first_bbox/first_frame` 与首帧发布器，用户明确暂不保留，
      本方案不迁、不恢复。

### 2.1 旧库演进事实（台账快照 `1b5fef5` → 当前 HEAD `636ecc6`）

| 提交 | 内容 | 对方案影响 |
|------|------|-----------|
| `a77850f` | 删除 vla 连续推理（`vla_skill.py` 减 78 行；engine/config/skill_api 同步删） | 印证「一轮 DISPATCH 单次消费」Non-Goal；`wait_action_tick` 空钩 |
| `acdffc9` | drone 侧 VLM 推理整体迁云：`vla_skill.py` 1164→443 行、`geometry.py` 重写（原迁移 −248 行）、`registry.py` 重写为 grounded schema（`bbox_1000`/`image_stamp` 必填）、`skill_api.py::SkillHost.vlm`/`VlmFacade` 端口退役、engine −70 / base_policy −176 / rpc_plane −114、config.py −14（`nav_tools`/`segment_nav_enabled`/`search_thinking_enabled`/`inference_timeout`/`sleep_for_turn`/`max_yaw_search`/`search_rot_yaw`/`max_z_search`/`search_pos_z`/`reacquire_interval`/`partial_bbox_*`/`llm_stamp_match_tolerance` 全删） | 印证「板上零 VLM、station 单次接地」；fail-closed 三态与 grounded schema 以现 HEAD 为准；搜索参数不迁 |
| `7bcc999` | l3/l4 全链对齐 `navigation.vla_nav`，去除错误的 `vla-reach` | 工具名与方案一致 ✓ |
| `636ecc6` | 文档性提交：station 侧 vla 系列命名收敛（配置键 `lx_vla_*`、异常 `VlaBackendTimeout`/`VlaBackendError`、线上字段 `vla_latency_ms`、常量 `VLA_REQUEST_TIMEOUT_S`），避免同名异构；drone 侧退役 vlm 模块名保持历史；零行为变化 | vla 系列命名先例：语义唯一；geometry.py「vla 专用」标注同向 |

旧库 `config.py` 当前保留的 VLA 关键值（已核 L210-222）：`search_success_distance_thresh=0.3`、
`geometry_agree_safe_dis_radius_m=0.8` / `geometry_mismatch_safe_dis_radius_m=1.2`、
`d_side=0.7` / `d_forward=0.0` / `behind_dist=2.0`、`stable_height=0.4` / `is_stable=False`、
`far_push_distance_m=5.0`。几何原语仍经 engine（`BasePolicyNode` 混入）可达：
`build_world_frame_for_image_stamp`（base_policy.py:906）、`pixel_to_world`（:2858）。

## 3. 目标与约束

- **目标**：
  1. 在新版实现 `navigation.vla_nav` 技能（grounded 消费 → 几何 → 航点 → 动作 → 四裁决），
     行为与旧链对齐（far_push / depth_match_ok / REPLAN / fail-closed 三态）。
  2. `geometry.py` 保留在 `tools/vla/`，文件头标注「vla 专用几何逻辑」；不抽成跨域共享服务。
  3. 工具发现面接入 `navigation.vla_nav`，同步更新 `l3-tool-plane.spec.md` 集合与 `revision`。
  4. R05 的 REPLAN 判据迁为技能自有状态；R07 归属裁决落地（删孤儿字段 + 台账关门）。
- **Non-Goals**：
  - 不迁 VLM/bbox 推理（station 已承担）；
  - 不恢复 first 系列、机上探索编排（yaw/z 步进、扫圈耗尽、多图 thinking）；
  - 不把几何泛化为多能力共享服务；不给 core 增加领域几何方法；
  - 不引入任务编号枚举或映射层。
- **硬边界**：
  - 禁止转接器桥接新旧接口（AGENTS 反转接器）；旧接口不留注释桩。
  - 技能不得直读宿主 `ActionGate.pending_action` 等私有对象（R05 接入顺序）。
  - 改动 spec/本文件前跑 spec 门禁（`specs/tools/spec-lint.sh`，若已迁移）。

## 4. 方案决策

- **目标目录树**（与 `flight/` 家族同构）：

  ```
  tools/vla/
    __init__.py
    catalog.py        # navigation.vla_nav 的 ToolSpec（发现面元数据）
    geometry.py       # vla 专用几何逻辑（文件头显式标注，不通用化）
    ports.py          # VlaSkillHost 协议（帧 + 几何原语 + 动作账务端口）
    vla_skill.py      # VlaSkill：grounded 消费 / 几何 / 动作 / REPLAN 四裁决
  ```

- **命名规范表**：

  | 类型 | 规范 | 示例 |
  |------|------|------|
  | 目录 | 能力家族名 | `tools/vla/` |
  | 文件 | snake_case，语义名 | `geometry.py` / `vla_skill.py` / `catalog.py` |
  | 类 | PascalCase，前缀家族 | `VlaSkill` / `GeometryService` / `VlaSkillHost` |
  | 技能名 | 工具全名（去 task-id） | `navigation.vla_nav` |
  | 工具元数据 | 与 `flight/catalog.py` 同构 | `ToolSpec(name, title, description, schema, ...)` |

> 命名依据：旧库 `636ecc6` 的 vla 系列命名收敛先例——凡服务于 drone-vla 功能的
> 模块一律 `vla` 系列标注，避免同名异构；本方案 `geometry.py` 头注「vla 专用几何逻辑」
> 即为该原则在技能侧的落地。

- **接口形态**：
  - `VlaSkill(SkillBase)`：`name = "navigation.vla_nav"`、`requires_perception=True`、
    `synchronous=False`。钩子：`plan_tick / wait_action_tick(空) / action_done_gate /
    on_action_result / on_cancel / on_global_stop / on_new_prompt_task`。
  - `GeometryService(geom_src)`：接收「几何原语源」端口，仅声明 VLA 所需子集
    （§2 列举的 13 个原语 + 只读配置 `safe_dis_radius_m / if_safe_dis / behind_dist /
    d_side / d_forward / depth_source / is_stable / stable_height` + 遥测 emit）。
    文件头标注：
    `"""vla 专用几何逻辑。不同能力按各自语义调用几何，本模块不通用共享。"""`。
  - `VlaSkillHost`：组合注入 `engine`（动作账务 + 代数）+ `perception`（几何原语源，
    `N/perception/base_policy.py` 实例）+ 配置。实现 `SkillHost` 端口：
    `latest_frame / get_fast_rgb / arm_action / send_task_goal / publish_mode_burst /
    stash_task_result / publish_phase / fail_sequence / capture_task_generation /
    task_generation_valid / consume_head_prompt / advance_prompt`。
    动作出海复用新版 `WaypointExecution`（`N/execution/waypoint_execution.py`），
    与飞行共用飞行独占（`_meta.lx.concurrency = "flight-exclusive"`）。
  - REPLAN 判据：REPLAN 状态（replan_cmd / replan_reason）为技能自有字段，
    在 `on_action_result` 内判定并返回 `SkillVerdict.REPLAN`；不读宿主 pending_action。
  - 工具面：`tools/vla/catalog.py` 产出 `navigation.vla_nav` ToolSpec（§2 旧 schema 去
    `task_id`，completion 沿用 `workflow_result`）；并入 `runtime`/控制面生产集合。
- **旧接口 → 删除**：迁移后旧库 O/ 不做任何改动（独立仓库）；新版不新增任何
  `vla` 旧名桥、不给 `engine` 加 `_geometry` 别名。

## 5. 迁移映射表

| 旧路径/命名 | 新路径/命名 | 动作 | 备注 |
|-------------|-------------|------|------|
| `O/tools/vla/vla_skill.py::VlaSkill`（name="vla"） | `N/tools/vla/vla_skill.py::VlaSkill`（name="navigation.vla_nav"） | rewrite | 保留 grounded 消费/far_push/REPLAN/fail-closed；身份、宿主、喇叭口换新版 |
| `O/tools/vla/geometry.py::GeometryService` | `N/tools/vla/geometry.py::GeometryService` | rewrite/保留 | 头注「vla 专用几何逻辑」；`self._eng.*` 改为注入的几何原语源 |
| `O/engine.py` 几何原语（经 base_policy） | `N/perception/base_policy.py` 原语（已存在，L798-L3016） | 复用注入 | 不改 base_policy 归属；VlaSkillHost 组合注入 |
| `O/tools/vla/vla_skill.py::_consume_grounded_detection`（L383-443） | `N/vla_skill.py` 同名 | rename+适配 | bbox_1000→像素换算、fail-closed 三态逐字保留 |
| `O/tools/vla/vla_skill.py::_dispatch_waypoint`（L317-377） | `N/vla_skill.py` 同名 | rewrite | 内联塑形保留；改为 `host.arm_action + send_task_goal + publish_mode_burst` |
| `O/vla_skill.py::on_action_result` 读 `replan_cmd`（L258-301） | `N/vla_skill.py::on_action_result` 返回 `SkillVerdict.REPLAN` | rewrite | REPLAN 状态技能自有；R05 接入建议落地 |
| `O/tools/registry.py::vla_nav` ToolSpec（L36-74，带 task_id） | `N/tools/vla/catalog.py` ToolSpec | rewrite | 去 task_id；schema 语义不变 |
| `host.recording._record_process_event`（R05 记录消费） | 暂不迁；登记台账 | delete（本轮） | 记录服务未建；`publish_phase` 覆盖状态可见性 |
| `first_rgb/first_bbox/first_frame` 首帧系列 | — | delete（不恢复） | 用户明确暂不保留 |
| R07 多图思考调试保存链（旧 `O/vla_skill.py#L886`） | 已随 VLM 迁云删除；新库不建消费者，删 `core/telemetry.py` 孤儿字段 `thinking_debug_dir`/`last_thinking_debug_dir` | delete | 双侧零消费者（旧 `O/engine.py#L277-L281` 亦孤儿）；过期必删；台账 R07 关门 |

## 6. 删除清单

| 删除项 | 理由 |
|--------|------|
| 新版侧不新建 first 系列（`first_rgb` 等） | 用户明确暂不保留；台账「本轮明确删除，不自动恢复」 |
| 新版不引入任意 `vla` 旧名桥 / `engine._geometry` 别名 / 任务编号枚举 | 反转接器 + 去 task-id 硬约束（G20/G23） |
| 不迁移 `wait_action_tick` 定时重搜 | 一轮 DISPATCH 单次消费；壳通用完成判定已确认 |
| 新版 `core/telemetry.py` 的 `thinking_debug_dir`/`last_thinking_debug_dir` 孤儿字段 | 旧多图思考保存链消费者已随 VLM 迁云删除（acdffc9），双侧零消费者；过期必删 |

## 7. 实施步骤（P0/P1/P2/P3/P4 分期）

### P0 — 契约与工具面先行

- 范围：先契约后代码（migration-protocol §1）。`l3-tool-plane.spec.md` §1 生产集合加入
  `navigation.vla_nav`（schema 按 §4 工具面），`revision` 重算并记录；若技能语义需要，
  在 `l3-skill-contract.spec.md` 补 VLA 身份/四裁决说明；rest 台账 R05 标记「由
  design-dispatcher-vla-migration 接管」并刷新触发条件；R07 标记「旧消费者已随 VLM
  迁云删除（acdffc9），双侧无消费者，本方案删孤儿字段后关门」。
- 行为不变式：发现面新增属性前不得改生产代码路径。
- 验收：spec 门禁绿；文档 `revision` 与工具元数据可重算一致。
- 回退：文档级回退，无代码残留。

### P1 — 几何与宿主

- 范围：`tools/vla/geometry.py`（头注「vla 专用几何逻辑」）、`ports.py`、`VlaSkillHost`。
  几何原语经注入的 perception 源调用（只声明 VLA 所需子集）；帧走 `latest_frame /
  get_fast_rgb`；动作账务走 `ActionGate`（复用 `DispatcherFlightHost.start_goal` 的武装
  序列：snapshot_owner → 代次 → `engine.action_finish=False` → WAIT_ACTION_FINISH）。
  独立小改：删 `core/telemetry.py` 的 `thinking_debug_dir`/`last_thinking_debug_dir`
  孤儿字段（R07 关门）。
- 行为不变式：几何输出与旧库在相同输入下字节级一致；不触碰 core。
- 验收：几何单测（构造 Frame/OdometryBuffer + 合成 bbox/深度/点云）对比旧链期望值；
  host 单测（owner/代次/完成门）。
- 回退：删除新增模块，core 与 flight 不受影响。

### P2 — 技能迁移

- 范围：`vla_skill.py` 迁移 plan_tick 语义：grounded 预检 → `_resolve_world_frame`
  （bracket/odom buffer 对齐，原 `build_world_frame_for_image_stamp`）→
  `_compute_waypoint_from_detection` → far_push / distance<0.3 判定 →
  `_dispatch_waypoint`（consume_head_prompt + arm_action + send_task_goal + 内联塑形）。
  `on_action_result` 四裁决（REPLAN/ADVANCE/IDLE/NEW_ACTION）以技能自有 replan 状态判定。
- 行为不变式：相同 grounded 参数下航点/裁决与旧链一致；fail-closed 三态不新增静默回落。
- 验收：`tests/tool-registry/test_vla_*.py`（schema 校验、负例）、`tests/core-boundary`
  （requires_perception 就绪门、「技能不读宿主私有」静态断言）。
- 回退：技能不注册（不进发现面）即可整体下线，核心 FSM 不受影响。

### P3 — 装配与发现面

- 范围：`N/execution/composition.py` 增 `install_vla(engine, ports, config)`（同飞行：
  构造 WaypointExecution/VlaSkillHost → 注册 `navigation.vla_nav` → 返回 disposer，
  异常回滚 dispose）；`tools/vla/catalog.py` 并入生产工具集合；dispatcher_node 接线。
- 行为不变式：未注册名依旧 `tool_not_registered`；飞行独占与同源抢占仍适用。
- 验收：`tests/tool-registry/test_rpc_plane.py` 空发现面断言更新；发现面 revision 与 spec 一致。
- 回退：disposer 注销技能并清理执行态；回滚 spec。

### P4 — 验收与台账归档

- 范围：全量门禁 G13-G17（技能契约）+ G18-G23（迁移协议）+ G24-G28（工具面）；
  rest R05/R07 更新「已接入/剩余触发条件」；方案置 done 时在
  `specs/implemented/architecture/` 归档决策记录。
- 行为不变式：不因台账关闭而改变生产行为。
- 验收：全量 pytest 绿；隐私门禁（提交前检索）无匹配。
- 回退：台账与归档可回退，代码以 P2/P3 disposer 兜底。

## 8. 验收标准

- [ ] `uv run pytest` 全绿（新增：`tests/tool-registry/test_vla_catalog.py`、
      `tests/core-boundary/test_vla_skill*.py`、`tests/perception/test_vla_geometry.py`）。
- [ ] 发现面断言：工具集合 == 七个（六 flying + `navigation.vla_nav`），`revision` 与
      `l3-tool-plane.spec.md` 记录一致；未注册名仍 `tool_not_registered`。
- [ ] bbox_1000→像素换算、yaw 换算、`far_push_distance_m=5.0`、
      `search_success_distance_thresh=0.3`、`d_side=0.7 / d_forward=0.0 / behind_dist=2.0`、
      高度 clamp 0~1.8 与旧链字节级一致。
- [ ] REPLAN：临时动作完成只进 REPLAN 且不提前 done；重新武装后旧代次结果被拒；
      取消/覆盖后 REPLAN 状态清理。
- [ ] fail-closed：`invalid_grounded_bbox` / `target_not_visible` /
      `odom_stamp_unavailable` 三态唯一 fail 终态；`slog` 事件名/transition reason 与旧链一致。
- [ ] R05/R07 台账在同一改动内更新（R05 接入位置/剩余触发条件；R07 删除后关门）；
      新库 grep `thinking_debug_dir` 0 命中；无 first 系列残留
      （grep `first_rgb|first_frame` 于新库 0 命中，除 `first_indices` 点云去重）。
- [ ] 几何调试发布（`_publish_candidate_debug_points`/`_publish_p2w_marker`）topic 名
      与旧链一致或按显式配置关闭。

## 9. 风险与对策

| 风险 | 影响 | 对策 |
|------|------|------|
| base_policy 几何原语未向技能开放 | VLA 无从计算航点 | VlaSkillHost 组合注入 perception 引用，只暴露 VLA 子集；不动 core |
| 几何输入难端到端复现（真机/仿真无 station） | 验收缺运行证据 | 构造 Frame/OdometryBuffer 单测覆盖 depth/cloud 双路、far_push、REPLAN；登记「本轮不可运行」与回归手段（migration-protocol §6） |
| REPLAN 判据依赖动作结果语义 | 误 done / 误 advance | 技能自有 replan 状态 + 代次门；ActionGate 返回 None 时技能不判定（行动返回 REPLAN 仅由已确定结果触发） |
| 与飞行独占/急停链路冲突 | 双 action 互踩 | 复用 `WaypointExecution` + `flight-exclusive`；急停走既有全局停止口，VLA 不发布独立急停 |
| R07 孤儿字段删除牵连未发现的消费者 | 误删引用报警 | 删除前 grep 全库（生产/测试）确认 `thinking_debug_dir` 0 命中；仅删 telemetry 字段，不动日志根目录 |

## 10. 修改点清单汇总

| 文件 | 动作 | 说明 |
|------|------|------|
| `specs/implemented/inner/l3-tool-plane.spec.md` | 修改 | §1 生产集合 + 记录 revision |
| `doc/l3-dispatcher-planner/rest/dispatcher-deferred-dependencies.md` | 修改 | R05 / R07 更新；「本轮明确删除」沿用 |
| `doc/l3-dispatcher-planner/rest/README.md` | 修改 | 索引同步 |
| `l3-dispatcher-planner/ros_packages/dispatcher/dispatcher/tools/vla/__init__.py` | 新增 | |
| `.../tools/vla/geometry.py` | 新增 | vla 专用几何逻辑（头注） |
| `.../tools/vla/catalog.py` | 新增 | `navigation.vla_nav` ToolSpec |
| `.../tools/vla/ports.py` | 新增 | VlaSkillHost 协议 |
| `.../tools/vla/vla_skill.py` | 新增 | VlaSkill 实现 |
| `.../execution/composition.py` | 修改 | `install_vla(...)` 装配 + disposer |
| `.../core/telemetry.py` | 修改 | 删 `thinking_debug_dir`/`last_thinking_debug_dir` 孤儿字段（R07 关门） |
| `.../utils/control_plane.py`（或 runtime 汇入处） | 修改 | 生产工具集合并入 vla catalog |
| `tests/tool-registry/test_vla_catalog.py` 等 | 新增 | 发现面 + schema 负例 + 技能/几何/宿主测试 |
| `specs/implemented/architecture/2026-09-17-vla-migration.md` | 新增 | done 时归档决策记录 |
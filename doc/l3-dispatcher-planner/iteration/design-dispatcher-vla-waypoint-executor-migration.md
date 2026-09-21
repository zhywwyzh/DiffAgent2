# dispatcher VLA 机上收窄为航点执行器 方案

> 摘要：把 DiffAgent2 旧库（`diff-dockers/drone_projects/l3-dispatcher-planner`）已经
> 落地的「station 解算 waypoint、机上只执行」形态迁到新库：`navigation.vla_nav`
> 下行载荷由 grounded detection（`bbox_1000`+`image_stamp`）改为 `waypoint_world`
> （+可选 `yaw`/`look_forward`），机上删除全部 bbox 消费与几何解算，退化为航点执行器。
> **本次只动新库机上（`l3-dispatcher-planner/` 与 `specs/`），不改 `l4-agent`。**
> 站端是否/如何产出 `waypoint_world` 由外部仓库负责（本库 `l4-agent` 非最新），
> 不在本方案范围；本方案保证「站端一旦按该契约下发，机上即可正确执行」。
> 依据来源：旧库当前 HEAD `tools/vla/vla_skill.py`（航点执行器形态）、
> `tools/registry.py`（`navigation.vla_nav` v3 schema）、旧库归档
> `specs/implemented/architecture/2026-09-19-vla-geometry-on-station.md`；
> 姊妹篇 [VLA waypoint 几何上移 station 方案](design-dispatcher-vla-waypoint-ownership-and-station-grounding.md)
> （含 station 侧；其 station 部分本次不执行）。

## 0. 元信息

| 项 | 值 |
|----|----|
| 日期 | 2026-09-20 |
| 目标路径 | `l3-dispatcher-planner/ros_packages/dispatcher/dispatcher/`、`specs/implemented/inner/` |
| 状态 | done（2026-09-20 执行完毕；归档 `specs/implemented/architecture/2026-09-20-vla-waypoint-executor.md`；经许可运行全量测试 167 passed / 1 failed，唯一失败为既有基线，见归档） |
| 关联文档 | [VLA waypoint 几何上移 station 方案](design-dispatcher-vla-waypoint-ownership-and-station-grounding.md)（姊妹篇）、[dispatcher VLA 技能迁移方案](design-dispatcher-vla-migration.md)、`specs/implemented/inner/l3-skill-contract.spec.md` §7/§10、`specs/implemented/inner/l3-tool-plane.spec.md` §1、`specs/implemented/inner/l3-execution-seam.spec.md` §7、旧库归档 `specs/implemented/architecture/2026-09-19-vla-geometry-on-station.md` |

### 0.1 范围裁定（用户指令）

1. **迁移来源**：旧库机上逻辑（航点执行器形态）迁入新库。
2. **删除**：新库多出来的 VLA 逻辑（机上几何、grounded 消费、几何注入端口）直接删除，
   不留转接口 / 注释桩。
3. **不动 station**：本次不调整 `l4-agent`；站端是否产出 `waypoint_world` 不作为本方案的
   前置或验收条件（本库 `l4-agent` 非最新版本，站端能力归属外部仓库）。
4. **判定口径**：本方案「完成」= 在「站端已按 §4.4 契约下发 `waypoint_world`」的前提下，
   机上能正确消费、执行并回报终态。

## 1. 背景与动机

- 旧库（DiffAgent2 旧版）已在 2026-09-19 完成「VLA bbox 与 waypoint 计算上移 station」：
  站端用「最新累积点云（世界系）+ 位姿按帧时戳插值 + VLM bbox」算出 `waypoint_world`
  下发；机上 `VlaSkill` 退化为纯航点执行器，机上 `tools/vla/geometry.py` 已删除。
- 新库当前仍是**上一代形态**：站端下发 grounded detection（`bbox_1000`+`image_stamp`），
  机上自己做 bbox→像素换算、世界系对齐、几何链解算 waypoint，并保留
  `far_push` / `depth_match_ok` / REPLAN 循环。
- 用户裁定：新库跟齐旧库的机上形态——只消费 station 算好的 waypoint 直接导航。
- 收益：VLA 领域逻辑（VLM 接地 + 几何）收敛到 station 一处；机上删除几何模块与几何
  注入端口，更贴近 `l3-core-boundary` 的「core 只分发 / 技能只执行」形态。

## 2. 现状事实（问题清单）

> 证据路径：`N/` = 新库根 `l3-dispatcher-planner/ros_packages/dispatcher/dispatcher/`；
> `O/` = 旧库根 `diff-dockers/drone_projects/l3-dispatcher-planner/ros_packages/dispatcher/dispatcher/`。

### 2.1 新库机上仍保留几何（待删）

- [ ] **技能 docstring 与依赖**：`N/tools/vla/vla_skill.py#L1-L35`（「哑执行器」但仍是
      grounded 消费形态）、`#L46`（`from ...vla_geometry import GeometryService, VlaGeometryConfig`）。
- [ ] **几何服务私有持有**：`N/tools/vla/vla_skill.py#L70-L72`
      （`GeometryService(host.geometry_source(), geometry_config, self._emit)`）。
- [ ] **grounded 消费 + 几何链 + far_push**：`N/tools/vla/vla_skill.py#L87-L224`
      （`plan_tick`）；`#L375-L436`（`_consume_grounded_detection`：bbox_1000→像素换算）。
- [ ] **几何模块整体**：`N/tools/vla/vla_geometry.py#L1-L601`
      （`GeometryService` / `VlaGeometryConfig` / `VlaGeometrySource` / `pose_to_list` /
      `normalize_direction` / `derive_nav_mode`）。
- [ ] **几何注入端口**：`N/tools/vla/ports.py#L19`（import `VlaGeometrySource`）、
      `#L49`（`geometry_source()`）。
- [ ] **宿主注入 perception + 几何源 + 快通道图像**：`N/execution/skill_host.py#L101-L134`
      （`VlaSkillHost.__init__(engine, execution, perception, config)`、`geometry_source()`、
      `get_fast_rgb()`）。
- [ ] **装配注入几何/感知/mission_type**：`N/execution/composition.py#L36-L85`
      （`install_vla(..., perception, *, geometry_config, search_success_distance_thresh, far_push_distance_m)`）。
- [ ] **组合根读几何参数**：`N/dispatcher_node.py#L144-L194`
      （`create_vla_runtime` 读 `VlaGeometryConfig` 全字段 + `far_push_distance_m`）；
      `#L219-L223`（仅 `perception is not None` 时装配 VLA）。
- [ ] **感知侧 VLA 专属几何原语**：`N/perception/base_policy.py`
      `build_world_frame_for_image_stamp`(#L798)、`_planar_axes_from_bearing`(#L980)、
      `_compute_cloud_ranges`(#L1101)、`_cloud_to_xyz_array`(#L1179)、
      `_build_region_from_bbox`(#L1339)、`bbox_candidate_to_body_incremental_waypoints`(#L1392)、
      `_sensor_priority_for_region`(#L1638)、`_publish_candidate_debug_points`(#L1661)、
      `_finalize_waypoint_candidate`(#L1690)、`_estimate_region_point_depth`(#L1771)、
      `_estimate_region_point_cloud`(#L2079)、`_estimate_waypoint_candidate_for_region`(#L2580)、
      `_cloud_depth_ranges_agree`(#L2650)、`_select_nearest_geometry_candidate`(#L2658)、
      `_geometry_safe_distance`(#L2667)、`_candidate_with_safe_distance`(#L2673)、
      `pixel_to_world`(#L2720)、`pixel_to_world_mask`(#L2779)、`_publish_p2w_marker`(#L3016)；
      以及仅服务该链的数据结构 `Frame`(#L42) / `PixelRegion`(#L57) / `WaypointCandidate`(#L70)。
- [ ] **发现面 schema 仍为 grounded**：`N/tools/vla/catalog.py#L19-L54`
      （必填 `object`/`prompt`/`bbox_1000`/`image_stamp`，`completion='workflow_result'`，
      `requires_perception=True`）；家族自述 `N/tools/vla/__init__.py#L1-L7`。
- [ ] **通用端口含 VLA 专用快通道图像**：`N/tools/skill_api.py#L85`（`get_fast_rgb`）；
      生产消费者仅 VLA（见 §2.4）。
- [ ] **动作完成由技能轮询驱动**：`N/tools/flight/motion.py#L16-L20`
      （`wait_action_tick` 调 `host.poll_result()`）；`N/tools/vla/vla_skill.py#L226-L237`
      同构。**新库不得照搬旧库的空 `wait_action_tick`**（见 §4.6）。
- [ ] **fail 原因未进 wire 词表**：`N/tool_plane/methods.py#L25-L28`（`_FAIL_REASONS`
      仅含 `connection_lost`/`cancelled`，其余 `error.code` 一律回落 `wrong_state`）；
      `invalid_station_waypoint` 若不登记，`rpc_outcome.reason` 将不是该值。

### 2.2 旧库目标形态（迁移来源，逐字对齐）

- [ ] `O/tools/vla/vla_skill.py#L1-L42`（航点执行器 docstring）、
      `#L75-L198`（`plan_tick`：`_consume_station_waypoint` → 距离过近判定 → 单次下发）、
      `#L200-L210`（`wait_action_tick` 空钩 + `action_done_gate` 返回 None）、
      `#L212-L257`（`on_action_result`：ADVANCE / IDLE / NEW_ACTION，**无 REPLAN**）、
      `#L274-L330`（`_dispatch_waypoint`：arm_action → 高度 clamp → mode_burst → send_task_goal）、
      `#L336-L366`（`_consume_station_waypoint`：`waypoint_world` 恰 3 项有限 + `yaw` 有限 → 6-D）。
      > 注：旧库 `wait_action_tick` 为空钩（其壳在别处轮询），**该点不可照搬**；
      > 新库动作完成必须由技能 `wait_action_tick` 调 `host.poll_result()` 驱动（见 §4.6）。
- [ ] `O/tools/registry.py#L36-L73`（`navigation.vla_nav` v3：必填
      `object`/`prompt`/`waypoint_world`，可选 `yaw`/`look_forward`，
      `completion='action_result'`，`requires_perception=False`）。
- [ ] `O/rpc_plane.py#L227-L234`（fail 词表：`invalid_station_waypoint`；原机上四态退役）。
- [ ] 旧库归档 `specs/implemented/architecture/2026-09-19-vla-geometry-on-station.md#L33-L54`
      （机上删除项与行为变化登记）。

### 2.3 契约现状

- [ ] `specs/implemented/inner/l3-tool-plane.spec.md#L34-L61`：`navigation.vla_nav` 的
      `inputSchema`（grounded）、`completion=workflow_result`、`requires_perception=true`
      与 `revision` 记录值，均需改。
- [ ] `specs/implemented/inner/l3-skill-contract.spec.md#L141-L162` §10：身份 / 端口 /
      四裁决 / fail-closed 三态，需按航点执行器收窄。
- [ ] `specs/implemented/inner/l3-skill-contract.spec.md#L96-L99` §7 端口表含
      「快速通道图像（入站）」行；`get_fast_rgb` 退役后该行须同步删除。
- [ ] `specs/implemented/inner/l3-execution-seam.spec.md#L77-L93` §7（取消/保持）**不变**。
- [ ] `specs/implemented/inner/l3-package-layout.spec.md#L41`：模块命名规范不因删除
      `vla_geometry.py` 而变（目录仍合规）。
- [ ] `l3-l4-rpc.spec.md` 信封/终态**不变**；fail 语义经 `error.code` → `_FAIL_REASONS`
      → `outcome.reason`，故映射表是必改点（见 §2.1 末条）。

### 2.4 生产消费者核对（删除前提）

- [ ] `get_fast_rgb` 生产消费者仅 `N/execution/skill_host.py`（VLA 宿主）与
      `N/tools/vla/ports.py`、`N/tools/skill_api.py` 声明；飞行宿主未实现。
- [ ] `geometry_source` / `vla_geometry` 生产消费者仅 VLA 家族与装配根。
- [ ] `sensor.capture` / `OdomBracket` 在**新库不存在**（仅 `N/tools/vla/vla_skill.py`
      注释提及），本次无需退役采集面。
- [ ] `mission_type` 在 `N/perception/base_policy.py` 的读取点（#L1377、#L1585、#L1724、
      #L1739、#L1753、#L1855、#L1878、#L1916、#L2251、#L2261）**全部位于本方案要删的
      几何原语内部**；删除后 `base_policy.mission_type` 与 `support/state.MISSION_TYPE`
      是否随之退役须按调用方检测（旧库保留为留壳）。

## 3. 目标与约束

- **目标**：
  1. `navigation.vla_nav` 载荷改为 `waypoint_world`（+可选 `yaw`/`look_forward`）；
     机上只做语义预检 + 距离过近判定 + 高度 clamp + 单次下发 + 终态回报。
  2. 机上删除 bbox 消费、世界系对齐与全部几何解算；`far_push`/`depth_match_ok`/REPLAN
     随几何一并退役（终态腿语义）。
  3. fail-closed 收敛为单一结构原因 `invalid_station_waypoint`，并**贯通到 wire**
     （`rpc_outcome.reason`）。
  4. 删除机上几何模块、几何注入端口与感知侧 VLA 专属原语（先做无调用方检测）。
- **Non-Goals**：
  - **不改 `l4-agent`**（站端 bbox 推理与站端几何不在本次范围）；
  - 不改 `agent-station-*` 站端契约（不在本仓库）；
  - 不改 planner（EGO）与 cmd 边界；不改 `WaypointExecution` / `LocalGoalSet` 行为契约；
  - 不引入任务编号或枚举映射；不恢复 first 系列；不恢复 replan/重试；
  - 不把几何泛化为多能力共享服务。
- **硬边界**：
  - 契约先行（`l3-migration-protocol` §1）；
  - 被替代的机上几何与端口**直接删除**，不留转接口/注释桩/别名（反转接器 + 过期必删）；
  - 禁止双写：goal 唯一写入方仍是机上 `WaypointExecution`；
  - 禁止假成功：载荷缺失/非法一律 fail-closed；
  - **不照搬旧库空 `wait_action_tick`**（会卡死等待态）；
  - 站端产出归属外部仓库，本方案不以其为前置，也不得因此保留机上几何兜底。

## 4. 方案决策

### 4.1 目标形态

```
station:  (本次不改) 解算 waypoint_world → 下发 navigation.vla_nav
drone:    navigation.vla_nav(waypoint_world) → 语义预检 → 距离过近判定
          → 高度 clamp → arm_action → send_task_goal → WaypointExecution
          → /planner/local_goal → 进度反馈 → rpc_outcome
```

### 4.2 目标目录树（改后）

```
tools/vla/
  __init__.py
  catalog.py        # navigation.vla_nav 的 ToolSpec（waypoint schema）
  ports.py          # VlaSkillHost 协议（去 geometry_source）
  vla_skill.py      # VlaSkill：station waypoint 消费 / 执行 / 三裁决
```

- `tools/vla/vla_geometry.py` **删除**（几何上移；机上零调用方）。

### 4.3 命名规范表

| 类型 | 规范 | 示例 |
|------|------|------|
| 目录 | 能力家族名 | `tools/vla/` |
| 文件 | 家族前缀（`__init__` 除外） | `vla_skill.py` / `catalog.py` / `ports.py` |
| 类 | PascalCase，家族前缀 | `VlaSkill` / `VlaSkillHost` / `VlaHostConfig` |
| 技能名 | 工具全名（去 task-id） | `navigation.vla_nav` |
| 消费入口 | 语义名 | `_consume_station_waypoint`（对齐旧库） |

### 4.4 接口形态

- **载荷（与姊妹篇 §4.3 同款）**：

  | 字段 | 必填 | 规则 | 说明 |
  |------|------|------|------|
  | `waypoint_world` | 是 | `array[number]`，恰 3 项（x,y,z，world/ENU） | 站端几何产物 |
  | `yaw` | 否 | `number`，有限 | 终末偏航；缺省 `look_forward` |
  | `look_forward` | 否 | `boolean`，缺省 `true` | 沿路径朝前 |
  | `object` / `prompt` | 是 | `string`，`minLength=1` | 显示与遥测关联 / 队列语义 |

  移除字段：`bbox_1000`、`image_stamp`、`image_width`、`image_height`、`provider`、
  `visible`、`finish`、`side`、`distance_m`（均由站端消费，不再下行）。

- **身份**：`name="navigation.vla_nav"`、`requires_perception=False`（机上仅需 odom，
  由 `WaypointExecution.state()` 校验）、`synchronous=False`；
  `_meta.lx.completion="action_result"`。
- **裁决**：`on_action_result` 三裁决 `ADVANCE` / `IDLE` / `NEW_ACTION`（贴地腿）；
  REPLAN 与 `replan_cmd`/`replan_reason` 一并退役。
- **fail-closed**：唯一结构原因 `invalid_station_waypoint`
  （`waypoint_world` 缺失/非 3 项/非有限，或 `yaw` 非有限）；该原因须同时登记进
  `tool_plane/methods.py::_FAIL_REASONS`，否则 wire `rpc_outcome.reason` 回落 `wrong_state`。
- **距离过近判定**：`latest_frame()` 可用时，`waypoint_world` 距当前位姿
  `< search_success_distance_thresh` 视为已到达 → `advance_prompt` 静默成功；
  **载荷带 `yaw`（terminal yaw）时豁免该判定**，照常发腿（到达后转向目标）；
  位姿不可用（headless）时跳过该判定，按正常航点执行。
- **yaw / look_forward 派生**：载荷 `yaw` 有限 → `nav_yaw=yaw`、`look_forward=False`、
  `yaw_source="station_geometry"`；否则 `look_forward` 取载荷（缺省 true）、
  `yaw_source="unspecified"`。
- **动作完成驱动**：`wait_action_tick` 必须保留 `host.poll_result()` 轮询
  （`FlightMotion` 同构）；`action_done_gate` 返回 None（走壳通用完成判定）。
- **相位事件与日志**：`publish_phase("searching", result={"kind": "vla_detection",
  "target": <prompt>, "waypoint": [x,y,z]})`（不再携带 `bbox`）；fail 前 slog 事件名
  `vla_invalid_station_waypoint`（替代 `vla_grounded_detection_failed`）；
  过近事件 `vla_waypoint_too_close`、发布事件 `vla_waypoint_published` 保留。
- **机上保留项（不得上移）**：位姿/高度界校验（`execution/waypoint.py#L20-L50`）、
  goal 唯一写入口（`send_task_goal`）、取消/保持（§7 不变）、独占与 owner 门、
  相位与 `rpc_outcome`。
- **旧接口 → 删除**：`tools/vla/vla_geometry.py` 整模块、`geometry_source` 端口、
  `VlaSkillHost` 的 perception 组合注入、`SkillHost.get_fast_rgb`（含 `l3-skill-contract`
  §7 对应行）。

### 4.5 队列/裁决机制（沿用新库端口，不照搬旧库壳）

新库已把旧库壳字段（`command_status` / `_load_next_prompt`）迁为端口
（`consume_head_prompt` / `advance_prompt` / 技能自有 `_advance_after_result`）。
本次**保留新库这套端口机制**，只替换其上游输入（grounded → station waypoint）：

- `plan_tick` 成功消费即终态腿：`host.consume_head_prompt()` → `_dispatch_waypoint(...)`，
  并置 `self._advance_after_result = True`；过近分支只 `advance_prompt`（不发腿）；
- `on_action_result`：`_if_landing` 分支 → `advance_prompt` + 贴地腿 → `NEW_ACTION`；
  否则 `ADVANCE`（`_advance_after_result`）或 `IDLE`；
- 成功/推进路径补 `host.stash_task_result({"completion": "action_result"})`
  （与 `tools/flight/motion.py#L34` 同构）。

### 4.6 与旧库的差异（**不可照搬项**，本方案必须保留的新库适配）

| 项 | 旧库做法 | 新库必须 |
|----|----------|----------|
| 动作完成驱动 | `wait_action_tick` 空钩（壳在别处轮询） | 技能 `wait_action_tick` 调 `host.poll_result()`（否则动作永不完成） |
| fail 词表落地 | `rpc_plane.py` 显式映射表 | 在 `tool_plane/methods.py::_FAIL_REASONS` 登记 `invalid_station_waypoint` |
| 队列推进 | `command_status` + `host._load_next_prompt` | `consume_head_prompt` / `advance_prompt` 端口 + 技能自有 `_advance_after_result` |
| 记录 | `host.recording._record_publish_action` / `_record_process_event` | 不迁（记录服务未建） |
| 首帧系列 | `on_plan_cycle_reset` 重采样 `first_*` | 不迁（用户明确不保留） |
| mission_type | 留壳保留（base_policy 共享层） | 装配侧写入删除；属性/枚举退役待调用方检测 |

## 5. 迁移映射表

| 旧（旧库机上 / 新库现状） | 新（本次落地） | 动作 | 备注 |
|---|---|---|---|
| `O/tools/vla/vla_skill.py::_consume_station_waypoint`(#L336-L366) | `N/tools/vla/vla_skill.py::_consume_station_waypoint` | rewrite（移植） | `waypoint_world` 恰 3 项 + `yaw` 有限 → 6-D |
| `O/tools/vla/vla_skill.py::plan_tick`(#L75-L198) | `N/tools/vla/vla_skill.py::plan_tick` | rewrite | 保留新库端口机制，去 grounded/几何/far_push；保留 terminal-yaw 豁免 |
| `O/tools/vla/vla_skill.py::_dispatch_waypoint`(#L274-L330) | `N/tools/vla/vla_skill.py::_dispatch_waypoint` | rewrite | 去 `replan_cmd`/`replan_reason`/recording；保留 clamp/mode_burst |
| `O/tools/vla/vla_skill.py::on_action_result`(#L212-L257) | `N/tools/vla/vla_skill.py::on_action_result` | rewrite | 四裁决 → 三裁决；landing 腿保留 |
| `O/tools/vla/vla_skill.py::wait_action_tick`(#L200-L206) | — | **不照搬** | 新库必须保留 `host.poll_result()` 轮询（§4.6） |
| `O/tools/registry.py#L36-L73`（v3 schema） | `N/tools/vla/catalog.py` | rewrite | 去 task_id；waypoint schema + `action_result` + `requires_perception=False` |
| `O/rpc_plane.py#L227-L234`（fail 映射） | `N/tool_plane/methods.py::_FAIL_REASONS` | rewrite | 新增 `"invalid_station_waypoint": "invalid_station_waypoint"`，否则回落 `wrong_state` |
| `N/tools/vla/vla_geometry.py` | — | delete | 几何上移；机上无调用方 |
| `N/tools/vla/ports.py::geometry_source` | — | delete | 同上 |
| `N/execution/skill_host.py::VlaSkillHost` 的 `perception`/`geometry_source`/`get_fast_rgb` | — | delete | 机上不再需要感知几何 |
| `N/execution/composition.py::install_vla` 的 `perception`/`geometry_config`/`far_push_distance_m`/mission_type | — | delete | 同上 |
| `N/dispatcher_node.py::create_vla_runtime` 的几何参数与 `perception` 形参 | — | delete | 装配层同步收窄 |
| `N/perception/base_policy.py` VLA 专属原语（§2.1） | — | delete（逐个无调用方检测） | 先 AST/grep 证零残留 |
| `N/tools/skill_api.py::SkillHost.get_fast_rgb` | — | delete | 迁移后零消费者（§7 端口表同步） |
| `N/tools/vla/vla_skill.py` 的 REPLAN 状态 / `far_push` / `depth_match_ok` | — | delete | 终态腿语义（旧库 design-vla-terminal-contract C1/C2） |

## 6. 删除清单

| 删除项 | 理由 |
|--------|------|
| `dispatcher/tools/vla/vla_geometry.py` 整模块 | 几何上移 station；机上零调用方 |
| `dispatcher/tools/vla/ports.py` 的 `geometry_source` 端口 | 同上 |
| `VlaSkillHost` 的 `perception` 组合注入 / `geometry_source()` / `get_fast_rgb()` | 机上不再需要感知几何与快通道图像 |
| `install_vla` 的 `perception` / `geometry_config` / `far_push_distance_m` / `mission_type` 写入 | 同上；mission_type 唯一消费方（NAVIGATION 分支）随几何删除，`base_policy.mission_type` / `MISSION_TYPE` 是否随之退役按调用方检测（旧库保留为留壳） |
| `create_vla_runtime` 的 `VlaGeometryConfig` 读取与 `~vla/*` 几何参数 | 同上 |
| `perception/base_policy.py` VLA 专属几何原语与 `PixelRegion`/`WaypointCandidate`（`Frame` 按调用方判定） | 过期必删；先做无调用方检测 |
| `vla_skill.py` 的 `_consume_grounded_detection` / REPLAN 状态 / `far_push` / `depth_match_ok` / `odom_stamp_unavailable` 分支 | 被 station waypoint 消费取代 |
| `SkillHost.get_fast_rgb` 端口（含 `l3-skill-contract` §7 端口表对应行） | 迁移后零生产消费者 |
| `tests/perception/test_vla_geometry.py` | 几何模块已删 |
| `~vla/far_push_distance_m` 私有参数 | 行为已退役 |

> 附带清理（同轮）：`vla_skill.py` 注释中「== sensor.capture 的 camera_receive_stamp」
> 等指向已退役采集面的表述一并删除；`VlaSkillHost.fail_sequence` docstring 中的三态词表
> 更新为 `invalid_station_waypoint`。

## 7. 实施步骤（P0–P3 分期）

### P0 — 契约先行

- 范围：改 `l3-tool-plane.spec.md` §1（`navigation.vla_nav` `inputSchema` 改
  `waypoint_world`+`yaw`+`look_forward`；`completion` 改 `action_result`；
  `requires_perception=false`；**重算并记录 `revision`**）；改 `l3-skill-contract.spec.md`
  §10（身份 / 端口 / 三裁决 / 单一 fail 原因）与 §7 端口表（删「快速通道图像」行）。
- 行为不变式：不改生产代码路径。
- 验收：spec 内 `revision` 与工具元数据可重算一致；文档一致。
- 回退：文档级回退。

### P1 — 机上技能收窄 + 装配收窄（同一次改动，避免中间态 import 断裂）

- 范围：
  - 重写 `tools/vla/vla_skill.py`（对齐旧库 §2.2 形态，按 §4.4/§4.5/§4.6 保留新库适配）；
  - 改 `tools/vla/catalog.py`（waypoint schema）；
  - 改 `tools/vla/ports.py`（去 `geometry_source`）；
  - 改 `execution/skill_host.py::VlaSkillHost`（去 perception/geometry_source/get_fast_rgb；
    更新 `fail_sequence` docstring）；
  - 改 `execution/composition.py::install_vla`（去 perception/geometry_config/far_push/mission_type）；
  - 改 `dispatcher_node.py::create_vla_runtime`（去几何参数与 perception 形参；
    **VLA 装配不再依赖 `perception is not None`**，headless 亦可装配）；
  - 改 `tool_plane/methods.py::_FAIL_REASONS`（登记 `invalid_station_waypoint`）；
  - **删除** `tools/vla/vla_geometry.py`；改 `tools/vla/__init__.py` 自述。
- 行为不变式：goal 唯一写入口仍为 `WaypointExecution`；取消/保持（§7）不变；
  fail-closed 不新增静默回落；动作完成仍由 `poll_result` 驱动。
- 验收：静态 import 自检；`navigation.vla_nav` 未注册名仍 `tool_not_registered`。
- 回退：git（同轮改动整体回退）。

### P2 — 感知侧几何退役

- 范围：按 §2.1 逐个原语做无调用方检测（AST + grep），删除 VLA 专属几何原语与
  `PixelRegion`/`WaypointCandidate`（`Frame` 依调用方判定）；删除 `SkillHost.get_fast_rgb`；
  按 §2.4 判定 `mission_type` / `MISSION_TYPE` 去留。
- 行为不变式：感知其余能力零行为变化；`get_frame_snapshot` 等保留。
- 验收：`grep` 机上 `vla_geometry|geometry_source|pixel_to_world|bbox_candidate_to_body_incremental_waypoints` 零命中（测试除外）。
- 回退：git。

### P3 — 测试与归档

- 范围：重写 `tests/core-boundary/test_vla_skill.py`、`test_vla_composition.py`、
  `test_vla_skill_host.py`、`tests/tool-registry/test_vla_catalog.py`；
  删除 `tests/perception/test_vla_geometry.py`；`tests/core-boundary/test_core_boundary.py`
  中 VLA 断言同步；归档 `specs/implemented/architecture/2026-09-20-vla-waypoint-executor.md`；
  同步 `doc/l3-dispatcher-planner/rest/` 台账（R05 触发条件）。
- 行为不变式：不因测试改动而改生产行为。
- 验收：全量 pytest 绿（含既有基线 ignore 项）；隐私门禁无匹配。
- 回退：git。

## 8. 验收标准

> **统一声明**：除非使用者明确许可，否则跳过验收测试工作（`AGENTS.md` 硬性约束 §9）。

- [ ] `uv run pytest` 全绿（新增/重写：`test_vla_skill.py`、`test_vla_composition.py`、
      `test_vla_skill_host.py`、`test_vla_catalog.py`；删除 `test_vla_geometry.py`）。
- [ ] 发现面断言：工具集合 == 七个（六 flying + `navigation.vla_nav`），
      `inputSchema.required == ["object","prompt","waypoint_world"]`，
      `completion == "action_result"`，`requires_perception == false`，
      `revision` 与 `l3-tool-plane.spec.md` 记录一致。
- [ ] 终态断言：载荷非法时 `rpc_outcome` 为
      `{"ok": false, "reason": "invalid_station_waypoint"}`（**不是 `wrong_state`**）；
      `odom_stamp_unavailable` / `invalid_grounded_bbox` / `target_not_visible`
      在机上零命中。
- [ ] 执行断言：`waypoint_world` → 6-D 航点；`yaw` 存在时 `look_forward=False`、
      `yaw_source="station_geometry"`；高度 clamp（`min_height`~`max_height`）生效；
      goal 唯一写入口不变；动作完成由 `wait_action_tick` 轮询驱动。
- [ ] 过近断言：`< search_success_distance_thresh` → `advance_prompt` 静默成功；
      带 `yaw` 时豁免（照常发腿）。
- [ ] 取消/保持（§7）回归通过。
- [ ] 删除项零残留：`grep` 机上无 `vla_geometry` / `geometry_source` /
      `get_fast_rgb` / `_consume_grounded_detection` / `bbox_1000`（生产代码）。
- [ ] 装配层：headless 亦装配 VLA（不再要求 perception 非空）。

## 9. 风险与对策

| 风险 | 影响 | 对策 |
|------|------|------|
| 站端产出 `waypoint_world` 的节奏不可控（外部仓库） | 落地后端到端暂不可运行 | 不以其为前置；站端落地走姊妹篇方案；不得因此保留机上几何兜底 |
| 照搬旧库空 `wait_action_tick` | 动作永不完成、FSM 卡在等待态 | P1 保留 `host.poll_result()` 轮询（FlightMotion 同构）；§4.6 明列 |
| `invalid_station_waypoint` 未进 `_FAIL_REASONS` | wire `reason` 回落 `wrong_state`，站端无法区分失败类型 | P1 显式登记映射；§8 增加 outcome 断言 |
| 感知原语存在未发现的调用方 | 误删导致回归 | 删除前 AST + grep 双检；旧库已证零残留，可对齐其删除集 |
| `Frame` 是否 VLA 专属存疑 | 误删破坏感知 | `Frame` 仅在有零调用方证据时删除，否则保留 |
| `requires_perception=false` 改变分发前就绪门 | VLA 在无感知时就绪 | 与旧库一致；机上仅需 odom（`WaypointExecution.state()` 校验） |
| headless 装配新增 | 无感知环境注册 VLA | 与旧库一致（执行器不需帧）；未注册名仍 `tool_not_registered` |
| landing 腿在无帧（headless）时 | 旧库仍返回 `NEW_ACTION` 却未武装，可能空转 | 新库显式：无帧则不发贴地腿，改走 `ADVANCE`/`IDLE`（在 §4.5 落定） |
| 装配层改动面大（host/ports/composition/node/methods 同轮） | 中间态 import 断裂 | P1 作为一次不可分割改动；先删 `vla_geometry` 再改引用 |
| `revision` 忘记重算 | G24 失败 | P0 显式重算并写回 spec |

## 10. 修改点清单汇总

| 文件 | 动作 | 说明 |
|------|------|------|
| `specs/implemented/inner/l3-tool-plane.spec.md` | 修改 | §1 schema / completion / requires_perception / revision |
| `specs/implemented/inner/l3-skill-contract.spec.md` | 修改 | §7 端口表（删快通道图像行）+ §10 身份 / 端口 / 三裁决 / 单一 fail 原因 |
| `.../dispatcher/tools/vla/vla_skill.py` | 重写 | station waypoint 消费 + 执行 + 三裁决（保留 poll_result 驱动） |
| `.../dispatcher/tools/vla/catalog.py` | 修改 | waypoint schema + `action_result` + `requires_perception=False` |
| `.../dispatcher/tools/vla/ports.py` | 修改 | 去 `geometry_source` |
| `.../dispatcher/tools/vla/vla_geometry.py` | 删除 | 几何上移 station |
| `.../dispatcher/tools/vla/__init__.py` | 修改 | 家族自述（去几何保留说法） |
| `.../dispatcher/execution/skill_host.py` | 修改 | `VlaSkillHost` 去 perception/geometry_source/get_fast_rgb；`fail_sequence` docstring |
| `.../dispatcher/execution/composition.py` | 修改 | `install_vla` 收窄 |
| `.../dispatcher/dispatcher_node.py` | 修改 | `create_vla_runtime` 收窄；headless 亦装配 |
| `.../dispatcher/tool_plane/methods.py` | 修改 | `_FAIL_REASONS` 登记 `invalid_station_waypoint` |
| `.../dispatcher/tools/skill_api.py` | 修改 | 删 `get_fast_rgb` 端口 |
| `.../dispatcher/perception/base_policy.py` | 修改 | VLA 专属几何原语退役（逐个检测）；`mission_type` 去留判定 |
| `.../tests/perception/test_vla_geometry.py` | 删除 | 几何模块已删 |
| `.../tests/core-boundary/test_vla_skill.py` | 重写 | 航点执行器用例 |
| `.../tests/core-boundary/test_vla_composition.py` | 重写 | 装配收窄用例 |
| `.../tests/core-boundary/test_vla_skill_host.py` | 修改 | 去 geometry_source/get_fast_rgb |
| `.../tests/tool-registry/test_vla_catalog.py` | 重写 | waypoint schema 正/负例 |
| `doc/l3-dispatcher-planner/rest/dispatcher-deferred-dependencies.md` | 修改 | R05 触发条件同步 |
| `specs/implemented/architecture/2026-09-20-vla-waypoint-executor.md` | 新增 | done 时归档 |

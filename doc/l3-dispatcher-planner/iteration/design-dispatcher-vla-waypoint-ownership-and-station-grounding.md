# VLA waypoint 几何上移 station 的迁移方案

> 摘要：**几何上移 station**。站端以「累积点云（最新，世界系）+ 按 `image_stamp` 插值的
> 位姿 + VLM bbox」算出 waypoint，经 `navigation.vla_nav` **下发 waypoint（不再是 bbox）**；
> 机上退化为航点执行器。不使用深度通道。需要时间匹配的输入只有 **rgb 与 odom**。

## 0. 元信息

| 项 | 值 |
|----|----|
| 日期 | 2026-09-19 |
| 目标路径 | `l4-agent/src/copaw/station_sidecar/`、`l3-dispatcher-planner/ros_packages/dispatcher/dispatcher/tools/vla/`、`specs/` |
| 状态 | proposed |
| 关联文档 | [VLA 技能迁移方案](design-dispatcher-vla-migration.md)、`specs/implemented/inner/l3-skill-contract.spec.md` §10、`l3-tool-plane.spec.md` §1、`l3-execution-seam.spec.md` §7、`l3-l4-rpc.spec.md`、`agent-station-channels.spec.md` §2.1/§2.3/§2.6/§2.7/§3.10/§3.13 |

### 0.1 裁决与决策沿革

| 版本 | 裁决 | 依据 |
|------|------|------|
| 上一版 | 不上移 | 误判为「几何依赖最新位姿」 |
| 本版 | **上移** | ① 几何实际只把**位姿**按 `image_stamp` 历史插值；② 契约可改（用户授权）；③ 站端已有 `CameraModel`（tool-side geometry）与累积云，§3.10 GRASP 已有站端算 waypoint 先例 |

**已定决策（用户裁定）**：

1. **下发 waypoint**：直接改 `navigation.vla_nav` 的下行载荷，由 `bbox_1000` 改为 waypoint。
2. **不用深度**：站端直接用遥测累积的点云（世界系累积结果，**取最新即可、不需要时间戳**）；
   需要时间匹配的只有 **rgb（VLM 输入）与 odom（位姿插值）**。

## 1. 背景与动机

用户提案：遥测已上传 rgb、点云与 odom，把 VLA 的 waypoint 计算从 drone 上移到 station。

目标收益：VLA 领域逻辑（VLM 接地 + 几何）收敛到 station 一处；drone 侧删除
`tools/vla/vla_geometry.py` 与 `VlaSkillHost.geometry_source` 端口，退化为航点执行器，
更贴近 `l3-core-boundary` 的「core 只分发」形态。

## 2. 现状事实（问题清单）

> 每条带「文件路径 + 行号」证据。

### 2.1 机上几何的真实数据依赖（更正）

- [ ] **位姿：按 image_stamp 历史插值** —
  `l3-dispatcher-planner/ros_packages/dispatcher/dispatcher/perception/base_policy.py#L798-L852`；
  缓冲实现 `base_policy.py#L88-L133`（位置线性 + 姿态 slerp，`max_len=100`）。
- [ ] **云：滚动时间窗快照（非按 stamp 取帧）** —
  `base_policy.py#L839-L847`（`cloud_history.snapshot()`）；实现
  `perception/pointcloud_accumulator.py#L18-L78`；装配 `base_policy.py#L399-L407`、
  喂入 `base_policy.py#L675-L684`。**默认 `~cloud_history_enabled=False`** → 回落最新帧云。
- [ ] **深度：最新帧深度（`replace` 保留，未按 stamp 对齐）** —
  `base_policy.py#L844-L852`。
- [ ] **点云 z 偏移** — `base_policy.py#L681-L684`（`pc_z_offset`）。
- [ ] **相机参数** — `base_policy.py#L258-L267`（`camera_extrins_T` / `camera_extrins_R`）。

> 结论：**需要时间匹配的只有位姿（odom）**；云取窗口/最新，深度不参与。

### 2.2 站端已有的等价能力

- [ ] `l4-agent/src/copaw/station_sidecar/telemetry_cache/camera_model.py#L1-L224` —
  `world_pose(position, quat_xyzw)` / `project_depth(...)`；头注明示服务
  「**tool-side geometry (bbox -> world)**」。
- [ ] `l4-agent/src/copaw/station_sidecar/telemetry_cache/cloud_map.py#L52-L136` —
  `RollingCloudMap`：世界系累积 + 体素下采样 + 快照缓存（即所需的「累积点云」）。
- [ ] `l4-agent/src/copaw/station_sidecar/telemetry_cache/__init__.py#L83-L125` —
  `TelemetryCache` 落 cloud/depth/camera/odom latch。
- [ ] `agent-station-channels.spec.md` §3.10 — 旧库 GRASP 已在站端算
  `waypoint_world` / `waypoint_body`（读模型先例）。
- [ ] `agent-station-channels.spec.md` §3.13 — 站端已有「**有界循环 + `ground_` 前缀内部
  命令 + 逐腿 await `rpc_outcome`**」编排先例（not-visible resweep）。

### 2.3 站端缺口

- [ ] **odom 无时间序列/插值** —
  `telemetry_cache/__init__.py#L111-L125` 仅单个 `OdomLatch`（latest）；
  `decoders.py#L216-L221` 虽解析 `stamp` 但未被索引使用。
- [ ] **rgb 无机端时戳** — `decoders.py` 无 stamp；
  `telemetry_cache/__init__.py#L99-L102` 用站端 `now` 落 latch。
  → 站端无法得知 `image_stamp`，而该值必须与机上 odom 同钟域。
- [ ] **累积云参数与机上不一致** — 站端 `cloud_map.py#L32-L35`（60 s / 0.1 m / 20 万点 /
  600 帧）vs 机上 `base_policy.py#L374-L382`（1.0 s / 0.0 / 30 帧）。
- [ ] **`pc_z_offset` 未应用** — 站端 CLOUD 为 raw passthrough（§2.4）。
- [ ] **相机参数一致性未验证** — 站端 `camera_model.py#L38-L47` 默认值「mirror the l3
  dispatcher fleet values」，但 `~camera_extrins_R/T`、`pc_z_offset` 的实际配置在旧库
  `bringup/config/vla/real.yaml`，本仓库无该文件 → 需逐项核对。
- [ ] **几何原语在机上** — 站端只有 `CameraModel`，没有 VLA 几何链
  （`pixel_to_world` / `bbox_candidate_to_body_incremental_waypoints` /
  `_finalize_waypoint_candidate` / `_candidate_with_safe_distance` 等）。
- [ ] **遥测有损** — `channels.spec` §2.3 每通道 `BestEffort` + `Drop`。

### 2.4 机上待移植的几何面（云路径）

| 原语 | 位置 | 处理 |
|------|------|------|
| `PixelRegion` / `WaypointCandidate` / `Frame` | `base_policy.py#L41-L86` | 移植（去 ROS 字段） |
| `_build_region_from_bbox` | `base_policy.py#L1339-L1346` | 移植（只吃 `pos`/`bbox`，不需 rgb） |
| `_planar_axes_from_bearing` | `base_policy.py#L980` | 移植 |
| `_compute_cloud_ranges` | `base_policy.py#L1101` | 移植 |
| `_estimate_waypoint_candidate_for_region` → `_sensor_priority_for_region` + `_estimate_region_point_cloud` | `base_policy.py#L2580` | 移植并**固定走 cloud 路径** |
| `_candidate_with_safe_distance` | `base_policy.py#L2673` | 移植 |
| `_finalize_waypoint_candidate` | `base_policy.py#L1690` | 移植 |
| `bbox_candidate_to_body_incremental_waypoints` | `base_policy.py#L1392` | 移植 |
| `pixel_to_world` | `base_policy.py#L2720` | 移植 |
| `_estimate_region_point_depth` / `_cloud_depth_ranges_agree` / `_select_nearest_geometry_candidate` | `base_policy.py#L1771/#L2650/#L2658` | **不移植**（决策 2 弃深度） |
| `_geometry_safe_distance` | `base_policy.py#L2667-L2671` | 简化为常量 `geometry_agree_safe_dis_radius_m`（无 mismatch 分支） |
| `_cloud_to_xyz_array`（PointCloud2 → xyz） | `base_policy.py#L1179` | **不移植**（站端直接喂 numpy） |
| `_publish_candidate_debug_points` / `_publish_p2w_marker` | `base_policy.py#L1661/#L3016` | **不移植**（ROS marker；站端用 telemetry/日志） |
| `GeometryService._compute_waypoint_from_detection` | `tools/vla/vla_geometry.py#L334-L601` | 移植（去 depth 分支） |

### 2.5 动作循环归属（上移的连带影响）

- [ ] REPLAN / far_push / 0.3 m 接近判定全部依赖几何 —
  `tools/vla/vla_skill.py#L87-L224`（`plan_tick`）、`#L243-L287`（四裁决）。
- [ ] 几何上移后机上无可重算的几何输入 → **循环必须上移或重构**（见 §4.4）。
- [ ] 机上必须保留：位姿/高度校验、goal 唯一写入口、取消/保持
  （`l3-execution-seam.spec.md` §7）、独占与 owner 门、相位与 `rpc_outcome`。

### 2.6 契约现状

- [ ] `agent-station-channels.spec.md` §3.13 现文「leaves l3's bbox→waypoint geometry
  untouched」「odom/pose resolution stays on the drone」需**改**（用户已授权）。
- [ ] `l3-tool-plane.spec.md` §1：`navigation.vla_nav` 的 `inputSchema` 与 `revision` 需改。
- [ ] `l3-skill-contract.spec.md` §10：VLA 身份/端口/四裁决需改。
- [ ] `l3-execution-seam.spec.md` §7：取消/保持**保持不变**。

## 3. 目标与约束

- **目标**：
  1. 几何（bbox→waypoint）在 station 侧实现，仅用累积云 + 位姿@stamp；
  2. 补齐 odom 时间序列与 rgb 机端时戳；
  3. `navigation.vla_nav` 下行载荷由 bbox 改为 waypoint；机上退化为执行器。
- **Non-Goals**：
  - 不改 `WaypointExecution` / `LocalGoalSet` / `/planner/local_goal` 行为契约；
  - 不改 planner（EGO）与 cmd 边界；
  - 不引入任务编号或枚举映射；
  - 不提高可丢遥测配额（§2.7）。
- **硬边界**：
  - 契约先行（`l3-migration-protocol` §1）；
  - 被替代的机上几何**直接删除**，不留转接口/注释桩；
  - 禁止双写：goal 唯一写入方仍是机上 `WaypointExecution`；
  - 禁止假成功：数据缺失一律 fail-closed。

## 4. 方案决策

### 4.1 目标形态

```
station:  capture(含 image_stamp) → VLM(bbox) → geometry
          (bbox + 最新累积云 + odom@image_stamp) → waypoint_world(+yaw)
          → 下发 navigation.vla_nav（waypoint 载荷）
drone:    navigation.vla_nav → 位姿/高度校验 → arm_action → WaypointExecution
          → /planner/local_goal → 进度反馈 → rpc_outcome
```

### 4.2 数据面

| 输入 | 需求 | 方案 |
|------|------|------|
| **odom** | 机端钟域时间序列 + 插值到 `image_stamp` | 站端新增 `OdomTimeSeries`（`drone_status` 已带 `stamp`，增量极小）；**D1 推送** |
| **rgb** | 帧 + 机端相机时戳 | `camera` 通道补机端时戳（D1）；或扩展 §3.13 `sensor.capture` 原子返回帧+stamp（D2） |
| **cloud** | 世界系累积点云，**取最新，不需时戳** | 复用站端 `RollingCloudMap.snapshot()`；对齐累积参数与 `pc_z_offset` |
| **depth** | — | **不使用**（决策 2）；`depth` 遥测通道保留供可视化，不再被 VLA 消费 |

**未决（需确认）**：`drone_status.stamp`（`decoders.py#L216-L221`）是 odom header stamp
还是发送墙钟。若为墙钟，需在 odom 子对象补 header stamp——发布端 `drone_bridge` 在兄弟
仓库（`channels.spec` §1），本仓库无法验证。

### 4.3 `navigation.vla_nav` 下行载荷（决策 1）

`inputSchema` 由 grounded 载荷改为 waypoint 载荷：

| 字段 | 必填 | 规则 | 说明 |
|------|------|------|------|
| `waypoint_world` | 是 | `array[number]`，恰 3 项（x,y,z，world/ENU） | 站端几何产物 |
| `yaw` | 否 | `number`，有限 | 终末偏航；缺省 `look_forward` |
| `look_forward` | 否 | `boolean`，缺省 `true` | 沿路径朝前 |
| `object` | 否 | `string` | 显示与遥测关联 |

移除字段：`bbox_1000`、`image_stamp`、`image_width`、`image_height`、`provider`、
`visible`、`side`、`distance_m`、`finish`（均由站端消费，不再下行）。

- `_meta.lx.completion`：由 `workflow_result` 改为 **`action_result`**（单腿以真实动作
  结果为准）。此项与 `revision` 一并在 P0 登记。
- `requires_perception`：机上不再需要感知帧参与几何 → 改 `false`；机上仅需 odom
  （由 `WaypointExecution.state()` 校验）。**此项须在 P0 契约中确认**（`requires_perception`
  同时是 core 的分发前就绪门，见 `l3-skill-contract` §2）。

### 4.4 动作循环（**需确认的关键点**）

几何上移后机上无法重算，far_push / 0.3 m 接近判定必须在站端表达。两种形态：

| 选项 | 形态 | 评价 |
|------|------|------|
| **(a) 站端编排多腿（推荐）** | 站端在一次用户步骤内循环：geometry → 下发一腿 → await `rpc_outcome` → 未到达则重新 capture+geometry → 下一腿（有界） | 保留 far_push（远目标不在累积云中时按 bbox 方位推进）与迭代精化；沿用 §3.13 已有的站端编排先例 |
| (b) 单腿一次性 | 站端一次算准最终 goal，机上飞完即 done | 改动最小，但目标不在累积云覆盖内即失败，且失去迭代精化 |

- 每腿一次往返；RTT 实测均值 4.6–8.4 ms（`channels.spec` §2.8），腿数有界，可接受。
- 用户可见步骤仍为一次 `navigation.vla_nav`；内部腿不出现在 step batch（同 §3.13 的
  `ground_` 前缀做法）。

> **本方案默认采用 (a)**；(b) 作为最小可用降级，需在方案内显式登记精度与覆盖损失。

### 4.5 机上保留项（不得上移）

- 位姿新鲜度/坐标系/有限性校验（`execution/waypoint_execution.py#L20-L31`）；
- 高度界校验（`waypoint_execution.py#L38-L41`）；
- 取消/停止/保持目标构造（`waypoint_execution.py#L83-L104`）；
- `flight-exclusive` 独占与 owner 门（`tools/runtime.py#L93-L161`）；
- 相位上报与 `rpc_outcome`（`utils/rpc_plane.py#L97-L124`）。

## 5. 迁移映射表

| 旧（机上 / 旧库） | 新（station） | 动作 | 备注 |
|---|---|---|---|
| `tools/vla/vla_geometry.py`（`GeometryService`） | station 侧几何服务 | rewrite | 云路径；去 depth 分支 |
| `base_policy` VLA 几何原语（§2.4 表） | station 侧几何服务内部 | rewrite | 纯 numpy 移植，去 ROS/marker |
| `vla_skill.plan_tick`（grounded 消费 + 几何 + 分发） | 站端编排器 | rewrite | 机上仅留腿执行 |
| `vla_skill.on_action_result`（四裁决） | 站端编排器状态机 | rewrite | 站端等价表达 |
| `OdomLatch`（latest） | `OdomTimeSeries`（插值到 stamp） | new | §4.2 |
| `camera` 遥测通道（无时戳） | 带机端时戳的帧 | modify | §4.2 |
| `navigation.vla_nav` grounded 载荷 | waypoint 载荷（§4.3） | rewrite | 行为契约变更 |
| `VlaSkillHost.geometry_source` / `perception` 注入 | — | delete | 机上不再需要 |
| `pc_z_offset` | 站端几何配置同名项 | migrate | 参数对齐 |
| `_estimate_region_point_depth` 等 depth 原语 | — | delete | 决策 2 |

## 6. 删除清单

| 删除项 | 理由 |
|--------|------|
| `dispatcher/tools/vla/vla_geometry.py` 及其在 `composition.install_vla` 的注入 | 几何上移；机上无调用方（G19/G20） |
| `dispatcher/tools/vla/ports.py` 的 `geometry_source` 端口 | 同上 |
| `VlaSkillHost` 的 `geometry_source()` 与 `perception` 组合注入 | 同上 |
| `base_policy` 中仅供 VLA 使用的几何原语（逐个无调用方检测后） | `l3-migration-protocol` §1/§3 |
| `_estimate_region_point_depth` / `_cloud_depth_ranges_agree` / `_select_nearest_geometry_candidate` 的 VLA 调用点 | 决策 2 弃深度（**是否整体删除需按其他调用方判定**） |
| l4 测试桩的「机上接地」代打（`tests/mocked_drone_stub.py` vla 分支） | 真实链路接线后仅保留测试语义 |

> 附带清理（建议同轮）：`base_policy.py#L2620-L2624` 等处在候选估计热路径上无条件写
> `/tmp/_apply_timing.log`，属调试残留，违反「过期必删」；移植时不带入，机上同轮清理。

## 7. 实施步骤（P0–P4）

### P0 — 契约先行

- 范围：改 `agent-station-channels.spec.md` §3.13（几何归属、帧时戳、`sensor.capture`）、
  §2.1/§6（camera 通道时戳字段）；改 `l3-tool-plane.spec.md` §1（`navigation.vla_nav`
  `inputSchema` + `completion` + `revision`）；改 `l3-skill-contract.spec.md` §10
  （身份/`requires_perception`/端口/四裁决）；新增 station VLA 几何叶契约。
- 行为不变式：不改生产代码路径。
- 验收：G18、G21（行为契约变更登记）、G24。
- 回退：文档级回退。

### P1 — 数据面与站端几何

- 范围：odom 时间序列 + 插值；rgb 机端时戳；累积云参数与 `pc_z_offset` 对齐；
  相机参数核对；站端几何服务（§2.4 云路径移植）。
- 行为不变式：**以回放数据证明站端几何与机上几何逐字段一致**后再切生产。
- 验收：用机上同期 (bbox, image_stamp, 累积云, odom) 回放，`target_pose` / `yaw_source`
  与机上云路径输出对齐（容差显式登记）。
- 回退：站端几何不接入生产，机上路径不变。

### P2 — 站端编排 + 机上执行器

- 范围：站端编排器（capture → VLM → geometry → 腿循环 → 汇总）；机上
  `navigation.vla_nav` 收窄为航点执行（§4.3/§4.4）。
- 行为不变式：机上仍独占 goal 写入口；取消/保持不变。
- 验收：端到端 grounded → 多腿 → `/planner/local_goal` → `/setpoint_cmd`；
  取消/抢占/租约丢失回归。
- 回退：feature-gate 回切。

### P3 — 删除与收敛

- 范围：按 §6 删除机上几何与端口；无调用方检测（G19）；行为契约字符串 diff（G21）。
- 验收：删除项零残留；机上 `grep` 无 `vla_geometry` / `geometry_source` 残留。
- 回退：git。

### P4 — 验收与归档

- 范围：G24–G28；真机/仿真整链；归档
  `specs/implemented/architecture/2026-09-19-vla-geometry-on-station.md`。
- 回退：台账与归档可回退。

## 8. 验收标准

> **统一声明**：除非使用者明确许可，否则跳过验收测试工作（`AGENTS.md` 硬性约束 §9）。

- [ ] 站端几何与机上**云路径**几何在回放数据上逐字段一致（容差显式登记）。
- [ ] odom 时间序列可插值到 `image_stamp`；超范围 fail-closed，使用站端语义化失败原因
      （不复用机上 `odom_stamp_unavailable` 名义）。
- [ ] 累积云参数与 `pc_z_offset` 与机上逐项一致（G21）。
- [ ] 安全距离：弃深度后恒取 `geometry_agree_safe_dis_radius_m`；该行为变化已登记。
- [ ] `navigation.vla_nav` 发现面 `inputSchema`/`completion`/`revision` 与 spec 一致（G24）。
- [ ] 机上 goal 唯一写入方仍为 `WaypointExecution`；取消/保持回归通过。
- [ ] 端到端：grounded → 多腿 → `/planner/local_goal` → `/setpoint_cmd`。
- [ ] 机上删除项零残留；无调用方检测零遗漏（G19/G20）。

## 9. 风险与对策

| 风险 | 影响 | 对策 |
|------|------|------|
| odom 有损致插值失败 | 几何 fail 由上行丢包触发 | 站端按相邻样本 bracket 插值，容忍单点缺失；失败原因显式；不静默回落最新位姿 |
| `drone_status.stamp` 钟域不明 | 插值错位 | P1 先核对 `drone_bridge`（兄弟仓库）；必要时补 odom header stamp |
| 累积云参数/`pc_z_offset`/相机参数不一致 | 航点系统性偏移 | P1 逐项对齐 + 回放验收 |
| 弃深度导致安全距离与 match 语义变化 | 接近行为变化 | 显式登记；回放对比 far_push 触发率 |
| 目标不在累积云覆盖内 | 无候选 | 站端编排 (a) 下按 bbox 方位推进（far_push 等价），不静默跳过 |
| 每腿往返延迟 | 多腿变慢 | 腿数有界；RTT 实测低（§2.8）；必要时评估流式方案（附录 A） |
| 几何原语移植引入数值漂移 | 航点偏差 | 回放逐字段对比 + 容差登记；纯 numpy 可直接单测 |
| 契约改动面大 | 漂移累积 | P0 一次改齐；`l3-migration-protocol` §5 顺序 |

## 10. 修改点清单汇总

| 文件 | 动作 | 说明 |
|------|------|------|
| `specs/implemented/inner/*station-vla-geometry*.spec.md` | 新增 | 站端几何叶契约 |
| `specs/implemented/inner/l3-tool-plane.spec.md` | 修改 | §1 载荷/completion/`revision` |
| `specs/implemented/inner/l3-skill-contract.spec.md` | 修改 | §10 VLA 语义收窄 |
| `l4-agent/src/copaw/station_sidecar/telemetry_cache/__init__.py` | 修改 | odom 时间序列 + rgb 时戳 |
| `l4-agent/src/copaw/station_sidecar/telemetry_cache/cloud_map.py` | 修改 | 累积参数对齐 + `pc_z_offset` |
| `l4-agent/src/copaw/station_sidecar/vla/` | 新增 | 站端几何服务 + 编排器 |
| `l3-dispatcher-planner/.../dispatcher/tools/vla/vla_skill.py` | 修改 | 收窄为航点执行 |
| `l3-dispatcher-planner/.../dispatcher/tools/vla/vla_geometry.py` | 删除 | 几何上移 |
| `l3-dispatcher-planner/.../dispatcher/tools/vla/catalog.py` | 修改 | 新 `inputSchema` |
| `l3-dispatcher-planner/.../dispatcher/tools/vla/ports.py` | 修改 | 去 `geometry_source` |
| `l3-dispatcher-planner/.../dispatcher/execution/composition.py` | 修改 | 去几何注入 |
| `l3-dispatcher-planner/.../dispatcher/perception/base_policy.py` | 修改 | VLA 专属原语逐个退役（先检测） |
| `specs/implemented/architecture/2026-09-19-vla-geometry-on-station.md` | 新增 | done 时归档 |

## 附录 A — 本方案不采纳但登记的备选

1. **流式 waypoint 通道**：站端按云速率重算并发布 `lx/<stack>/vla/waypoint`，机上取最新。
   优点：无逐腿往返。缺点：控制关键数据走有损通道，与 §2.3/§2.7 的「控制面可靠、遥测
   有损」切分冲突。
2. **机上保留几何、站端只做 VLM**（上一版方案）：改动最小，但 VLA 逻辑仍分散两侧。

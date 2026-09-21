# VLA 机上收窄为航点执行器的交付决策

Status: implemented

日期：2026-09-20

现行行为归 `l3-skill-contract.spec.md` §7/§10、`l3-tool-plane.spec.md` §1 与
`l3-execution-seam.spec.md` §7。本记录登记本轮实现选择：对齐 DiffAgent2 旧库
2026-09-19 的「几何上移 station」机上形态，**只动机上，不改 `l4-agent`**。方案全文见
[dispatcher VLA 机上收窄方案](../../doc/l3-dispatcher-planner/iteration/design-dispatcher-vla-waypoint-executor-migration.md)。

载荷：`navigation.vla_nav` `inputSchema` 改为 `object`/`prompt`/`waypoint_world`
（恰 3 项，world/ENU）必填 + `yaw`/`look_forward` 可选；`completion=action_result`；
`requires_perception=false`。`revision` 现行值
`sha256:45c6030faffd0bf2254a6c96da8c0c7bf0f193a1e0ea829f64f7d8929b81e4f7`。

技能（`tools/vla/vla_skill.py` 重写）：单次消费即终态腿——语义预检
（`_consume_station_waypoint`）→ 航点命中相位（携带 `waypoint`，不再携带检测框）
→ 距离过近判定（`< search_success_distance_thresh` 静默成功；**载荷带 `yaw` 时
豁免**——terminal yaw 到达后转向目标；无帧 headless 跳过判定）→ 高度 clamp →
单次下发。三裁决 ADVANCE/IDLE/NEW_ACTION；**REPLAN 退役**（`far_push`/
`depth_match_ok` 随几何上移一并退役）。fail-closed 唯一结构原因
`invalid_station_waypoint`，并经 `tool_plane/methods.py::_FAIL_REASONS` 贯通到
`rpc_outcome.reason`。`wait_action_tick` 保留 `host.poll_result()` 轮询驱动
（FlightMotion 同构；不可照搬旧库空钩）。landing 贴地腿保留；headless 无帧时
不发贴地腿、按队列推进收敛（不空武装）。

删除项（零残留，过期必删）：`tools/vla/vla_geometry.py` 整模块；
`ports.py` 的 `geometry_source` 端口；`VlaSkillHost` 的 perception 注入与
`get_fast_rgb`；`install_vla`/`create_vla_runtime` 的几何配置与 `far_push`
参数；`SkillHost.get_fast_rgb` 端口（含技能契约 §7 对应行）；
`perception/base_policy.py` 的 VLA 专属几何族（42 方法 + `PixelRegion`/
`WaypointCandidate` + 密集窗/ray-grid/marker/bbox/mask 发布器与参数族 +
`get_fast_rgb` 端口方法 + `get_frame_snapshot_near_stamp`/
`build_world_frame_for_image_stamp`，3029 → 1302 行，`py_compile` 通过）；
`support/config.py` 的 `geometry_agree`/`geometry_mismatch`/`stable_height`
死默认值；`import pdb`/`Marker`/`replace` 残留导入。

保留项（对齐旧库留壳，不因引用计数裁剪）：`base_policy` 的 `mission_type`/
`MISSION_TYPE`（旧库保留为共享层留壳）、`is_stable`/`behind_dist`；通用帧同步
机制（`build_frame_from_latest_cache`、fast-RGB 私有缓存、`cloud_history`、
`OdometryBuffer`/`SensorBuffer`、`_compute_cloud_ranges`/`_cloud_to_xyz_array`）。
`core` 的 `PendingAction.replan_cmd`/`is_far_push` 与 `SkillVerdict.REPLAN`
保留为通用账务/裁决机制（技能契约 §4 通用语义，非 VLA 专属）。

装配：`create_vla_runtime(engine, ports, execution_config)` 不再接收 perception，
**headless 亦装配 VLA**（航点执行器不需感知帧）；`~vla/*` 收窄为 `VlaHostConfig`
全字段 + `search_success_distance_thresh`。

验收证据（2026-09-20，经使用者许可运行）：`python3 -m pytest l3-dispatcher-planner/tests`
（排除环境缺 `zenoh` 的四个收集失败基线：`tool-registry/test_connection_lease.py`、
`tool-registry/test_control_plane_lifecycle.py`、`tool-registry/test_l4_rpc_contract.py`、
`ros/test_ego_cmd.py`）→ **167 passed / 1 failed**；唯一失败
`test_core_boundary.py::test_import_closure_has_no_domain_or_ros` 为**既有基线**
（`core/skill_router.py` 自提交 `28db4d1` 起 `from dispatcher.tool_plane.model import ...`
与禁用前缀冲突；`core/` 未被本轮触碰，`git diff HEAD -- core/` 为空），与本轮改动无关，
按归口交该重构后续处理。测试面同步重写：`test_vla_skill.py`/`test_vla_composition.py`/
`test_vla_skill_host.py`/`test_vla_catalog.py`，删除 `tests/perception/test_vla_geometry.py`；
`test_core_boundary.py` 的配置路由用例探测属性由已退役的
`geometry_agree_safe_dis_radius_m` 换为仍在用的 `behind_dist`。

已知边界：站端产出 `waypoint_world` 的能力归外部仓库（本库 `l4-agent` 非最新），
真机/仿真整链验收待站端具备产出条件后补。

# 航点下发执行按家族归属

Status: implemented

日期：2026-09-21

现行行为归 `l3-execution-seam.spec.md` §1/§4/§6/§7 与 `l3-package-layout.spec.md`
§1–§3。本记录登记本轮结构性决策：把单目标航点下发执行（`WaypointExecution`：
批次、反馈、超时、取消/保持）从共享平面 `dispatcher/execution/waypoint.py`
按使用者下沉为两份家族实现。

裁决：用户裁定「航点发布是一个独立能力，后续新增的很多功能完全不使用该
发布」，故不作为跨工具共享能力集中维护。该裁定与当时现行 §1「跨工具共享的
动作发送……归 dispatcher 内部执行模块」条文冲突，已按 `AGENTS.md` §6 停下
引用双方原文请用户裁决，用户裁决为执行迁移；契约先行落地后改实现。

改动（方案：[航点下发执行按家族归属方案](../../doc/l3-dispatcher-planner/iteration/design-dispatcher-waypoint-execution-family-ownership.md)）：

- 删除 `dispatcher/execution/waypoint.py`（不留转接器、别名或注释桩）；
- 新增 `dispatcher/tools/flight/flight_waypoint.py`（类 `FlightWaypointExecution`）
  与 `dispatcher/tools/vla/vla_waypoint.py`（类 `VlaWaypointExecution`），
  两份与旧实现**逐字等价**（公开签名 `__init__/state/start/poll/cancel/stop`
  与全部语义词一致）；同轮按用户指令补家族前缀（初版两份同名
  `WaypointExecution` 会混淆）；
- `execution/composition.py` 作为装配根分别引入两份（`install_flight` 用飞行份、
  `install_vla` 用 VLA 份）；`execution/skill_host.py` 仅同步 docstring；
  `execution/__init__.py` 平面自述收缩为「共享动作端口、家族宿主与装配」；
- 共享平面保留：`ports.py`（planner 线上接口契约，`ros_adapter` 单点实现，
  `Goal`/`FlightPorts`/`FlightState`/`Progress`/`ActionResult`/`FlightConfig`）、
  `skill_host.py`（两家族宿主）、`composition.py`（装配）——本轮 Non-Goals；
- 契约同步：`l3-execution-seam.spec.md` §1 归属表、§2 节律措辞、§3 能力端口
  措辞、§4 语义边界、§6 G11；`l3-package-layout.spec.md` §1 平面表、§2 命名
  （新增「模块（家族执行）」行，执行缝示例改 `execution/ports.py`）、§3 依赖
  方向补充装配根条款；
- 测试面 import 同步：`tests/basic-flight/test_flight.py`、
  `tests/core-boundary/test_vla_skill.py`、`tests/core-boundary/test_vla_skill_host.py`、
  `tests/ros/test_ego_cmd.py` 改指家族模块（`test_vla_composition.py` 无直接
  import，未动）；
- 台账 R05 新增「执行实现归属（2026-09-21）」行。

放弃了什么：以单一共享实现承载航点下发（DRY）。用户明确接受两份相同实现
（「哪怕相同」）；两份之间的差异此后只能来自显式的后续方案，不允许静默分叉。

行为边界不变：topic（`/planner/local_goal`、`/planner/waypoint_progress`）、
消息字段（`LocalGoalSet`/`WaypointProgress`）、`batch_id` 语义、取消/保持
（以新批次发布当前位置保持意图）、goal 唯一写入口、语义词（`waypoint_skipped`/
`planner_timeout`/`execution_cancel_pending`/`execution_not_cancelled`/
`action_generation_exhausted` 等）零变化；两家族实例仍各自随机批次起始。

验收证据（静态）：全树 grep `execution.waypoint` 零命中（生产与测试）；
`execution/waypoint.py` 文件已删除；两份新实现与旧实现逐字一致。按
`AGENTS.md` §9，未运行 pytest（未经使用者明确许可）。

已知边界：`execution/ports.py` 与 `execution/skill_host.py` 仍在共享平面；
若后续裁定一并按家族下沉，须另立方案并同步 `l3-package-layout.spec.md` §3
依赖方向与 `ros_adapter` 实现目标。`scene_nav` 家族尚未迁入（未实现），
本轮未涉及其任何实现取舍。

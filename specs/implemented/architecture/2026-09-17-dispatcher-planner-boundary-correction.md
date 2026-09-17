# mission-executive 控制职责上行到 dispatcher 的边界修正

Status: implemented

日期：2026-09-17

Supersedes: specs/implemented/architecture/2026-09-17-dispatcher-basic-flight.md

本记录依据用户的边界纠正，取代前次交付决策中新增 EGO 取消接口、修改后端停止
行为和裁剪额外消息字段的选择。前次记录与当时的测试结果保留，不改写为本次证据。

source_task_id 与 SOURCE_TASK_* 删除；yaw_low_speed、goal_to_follower 保留，并
恢复 planner 原有读取逻辑。仅 task-id 清理需要同步到 EGO/SUPER；普通取消和停止
控制不再要求 planner 提供新订阅、回调或额外状态清理。公开 camera_fov.h 路径恢复，
不让 planner 因共享依赖目录调整发生无关改动，也不增加转接头文件。

旧 MissionCore::stopMotion 通过发布当前位置、当前偏航角和 look_forward=false
来构造保持意图，再由 publishGoalWindow 作为新批次下发。该职责由 dispatcher 的
WaypointExecution 承接，使用已有目标消息通道；不恢复 mission 包或 action 转换层。
dispatcher 管理取消待处理状态、动作批次和迟到结果，保持批次不作为旧调用成功结果。

普通取消不发全局急停信号；显式急停保留既有信号，并由 dispatcher 编排保持意图。
位姿无效或发送失败时保持取消待处理状态、阻止新动作，不假装已经完成停止。

本轮只修正接口和职责归属，并同步已有测试断言；按用户要求不新增或运行测试、
不执行构建。此前 EGO 专属接口版本的 115 项通过记录不覆盖本修正版，也不能证明
所有后端行为等价。l4-agent 与 DiffAgent2 旧版保持只读；cmd 下游仍不在任务范围。

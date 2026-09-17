# 规范整理与日志迁移核对记录

本文件是迁移资料，不定义契约。现行日志规范见
[日志契约](../../../specs/implemented/inner/observability-log.spec.md)，编码要求见
[编码规范](../../../specs/implemented/inner/l3-coding-style.spec.md)。

## 2026-09-17 文档整理边界

本次只调整文档，没有修改代码、构建配置或运行测试。旧版 mission_executive 的
工具流程应上行到 dispatcher 工具及其状态机；不在新版构建旧包。
原文中的已交付表与重命名表仅保留为历史线索，不能证明新版能力已交付。
此前基础飞行的 115 项通过不覆盖职责修正版；相关证据见
[边界修正决策](../../../specs/implemented/architecture/2026-09-17-dispatcher-planner-boundary-correction.md)。

## 历史编码映射摘录

以下是整理前的映射表，非当前符号清单；尤其不要求恢复任务编号、旧类或命名空间。

| 旧符号 | 历史替代符号 |
| --- | --- |
| `md_` | `mission_data_` |
| `fp_` | `params_` |
| `fd_` | `data_` |
| `mtx_` | `mutex_` |
| `odom_pos_` / `odom_vel_` / `odom_orient_` / `odom_yaw_` | `odometry_position_` / `odometry_velocity_` / `odometry_orientation_` / `odometry_yaw_` |
| `path_res_` / `path_inx_` | `planned_path_` / `path_index_` |
| `aim_pos_` / `aim_yaw_` / `local_aim_pos_` | `target_position_` / `target_yaw_` / `local_target_position_` |
| `ego_exec_finished_` | `planner_execution_finished_` |
| `wp_batch_*` / `wp_window_*` | `waypoint_batch_*` / `waypoint_window_*` |
| `pubLocalGoal` | `publishLocalGoalWindow` |
| `transitState` | `transitionToState` |
| `stashCurStateAndTransit` | `stashStateAndTransition` |
| `getAndPublishNextAim` | `selectAndPublishNextWaypoint` |
| `isInited` | `isInitialized` |
| `visRepairMid` | `visRepairMidpoint` |
| `state` | `getState` |
| `data` | `getData` |
| `mission` | `getMission` |
| `activeTaskId` | `getActiveTaskId` |
| `activeSessionId` | `getActiveSessionId` |
| `droneId` | `getDroneId` |
| `params` | `getParams` |
| `resetPending` | `isResetPending` |

## 历史日志迁移声明摘录

以下保留原规范的历史状态陈述；不作为 DiffAgent2 新版验收记录。

> 以整组件为阶段；每个 l3 阶段均于 2026-09-15 交付。唯一未关闭的 B 层
> 残留逐行记录。

| 组件 | 状态 |
|-----------|-------|
| mission C++ slog | 规范词汇表 + `seq`；rosout 汇点默认关闭；`odom_buffer` 已迁移 —— 已交付 |
| mission py 副本 | 与 C++ 字节一致；`bridge_client` RPC 失败发出信封事件 —— 已交付 |
| dispatcher slog + 记录 | 一个发射器 / 一个 seq / 稠密上行（§6）；模块级代码通过进程单例发射 —— 已交付 |
| dispatcher `rospy.log*`/`print` | 全部迁移到信封事件 —— 已交付（已死的 vendored `parallel_serve_*` / `open_serve_count_video` 函数体未改动） |
| ego_planner | 完整 slog 迁移（入口安装 + 全部源文件 + 头文件）—— 已交付 |
| scene_graph | `ROS_*` 站点迁移到语义事件；`INFO_MSG*` 流宏改指向 slog（颜色→级别：RED→error，YELLOW→warning，plain/GREEN/CYAN→info，BLUE→debug）—— 已交付 |
| bridges (drone_bridge) | 仍有 3 处 `rospy.log*` —— B 层；与共享 py 发射器合并一同迁移（dispatcher 未 catkin 安装进 devel，跨包 import 不可用） |

## 接入与关闭条件

| 项目 | 当前边界 | 触发条件与验收 | 可关闭条件 |
|---|---|---|---|
| 记录服务、快照与 agent_log | 保留严格规范；R01/R02/R06 仍待迁 | 接入时验证单一发射器、seq、停止记录、稠密上行、快照与去重 | 真实生产者与站端消费者闭环通过并记录证据 |
| 场景导航日志生产者 | 归 dispatcher 工具及工具状态机；不是已注册能力声明 | 场景工具迁入时逐项核验事件表、工具名字段、会话关联及聚合关闭；不能恢复来源任务编号 | 工具实现与采集/聚合消费者同步验收 |
| 部署与站端流水线 | 规范约束不等于本仓库已部署 | 接入时核对采集、中继、站端独占订阅及日志呈现 | 附部署侧和站端的可重复验证证据 |

事件名、阈值、聚合窗口及规范信封本次保留。生产者归属与来源任务编号字段的文档
纠正必须在未来接入时同时核对消费者；本次不声称已完成线上字段迁移。
原日志合并记录日期为 2026-09-16，来源包括 log-ingest、l3-log-format、
l3-log-level-policy、ros-log-buffering、l3-scene-nav-task-log。

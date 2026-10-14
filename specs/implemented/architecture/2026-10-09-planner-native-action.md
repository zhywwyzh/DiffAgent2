# planner 原生 action 与动作资源归属决策

Status: implemented
Date: 2026-10-09
Record-Format: historical
Supersedes: specs/implemented/architecture/2026-09-17-dispatcher-planner-boundary-correction.md
Supersedes: specs/implemented/architecture/2026-09-21-waypoint-execution-family-ownership.md
Supersedes: specs/implemented/architecture/2026-10-09-flight-vla-result-convergence.md
Superseded-by: specs/implemented/architecture/2026-10-10-task-cancel-emergency-hover.md

本记录表示代码已落盘，未编译、未运行或验收。现行接口归
[执行缝契约](../inner/l3-execution-seam.spec.md)，实施范围见
[原生 action 方案](../../../doc/l3-dispatcher-planner/iteration/design-planner-native-action.md)。

原目标 topic、进度 topic 和家族航点执行器共同承担关联、取消和停稳，导致
dispatcher 必须自行拼接多个反馈。改用 `/planner/execute_waypoints` 原生
ROS1 action；删除被替代的消息与执行器，不增加旧协议转接层。

planner_execution 统一拥有目标接纳、原目标停稳、执行超时、停止确认和
终态；EGO、DIFF、SUPER 直接提供后端启动及停止实现。动作取消请求只有在
停止动作已发出且新鲜状态持续满足停稳条件后才能确认；确认失败保留故障。
后端不支持的偏航及跟随能力明确拒绝，不以其他动作代替。

dispatcher 的飞行与 VLA 共用 ActionSession。会话绑定调用代次及技能归属，
取消后等待原动作资源释放，迟到终态不能推进新调用。技能继续拥有多腿顺序，
例如位置、终末偏航、贴地全部成功后才完成 VLA。引擎只注入机械推进回调，
不增加动作专用业务状态。

独立执行状态 topic 表达空闲时的启动就绪、停止确认、后端启动标识与恢复
代次；它用于资源接纳及显式恢复，不能替代动作结果。公共物理门限与超时归
`/planner_execution`，EGO 启动文件加载共享配置；其他部署必须自行加载。

此决策替代此前家族执行器拥有物理完成门的归属。旧决策保留为历史。按使用者
约束，本轮未运行测试、构建、语法检查、门禁或仿真；外部调用方迁移、各后端
停止效果及断连恢复仍需运行证据，不能宣称生产可用。

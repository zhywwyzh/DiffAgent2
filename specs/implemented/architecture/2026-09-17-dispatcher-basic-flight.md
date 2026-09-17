# 基础飞行直连 EGO 的交付决策

Status: implemented

日期：2026-09-17

Superseded-by: specs/implemented/architecture/2026-09-17-dispatcher-planner-boundary-correction.md

现行行为归 `l3-execution-seam.spec.md`、`l3-skill-contract.spec.md`、
`flight-actions.spec.md` 与 `l3-tool-plane.spec.md`。本记录延续 dispatcher 直连
planner 的架构方向，记录本轮实现选择，不替代现行契约。

六个 basic_flight 名字直接对应六个技能实例，不恢复 flight 别名。同步起降与急停
报告 forwarded，平移/旋转/返航根据当前批次的实际反馈报告 action_result。共享执行
不识别工具名字，core 保持六态；准入/取消/FSM 处理串行，等待期间释放生命周期锁。

返航使用独立 FlightSession 的确认原点，空参只代表 origin，不把任务队列快照当原点。
地面高度须显式配置；过期、错误坐标系和重置使原点失效。previous 和旧记录消费仍在
台账保留，没有借本轮范围收敛删掉未来消费者所需字段。

仅迁 EGO 真实使用的消息与最小公共依赖，删除 LocalGoalSet 的来源任务编号及旧字段
回退；不迁 mission/task、planner/waypoints action 或旧转换节点。batch_id 仅关联
下游动作反馈，不映射任务身份。普通取消通过当前批次号驱动保持命令，急停独立；
停止同时清除旧偏航目标，避免位置保持时继续转动。

默认六工具在领域测试、真实 FSM、ROS/EGO cmd 和正式启动入口验证后开放。最终
115 项测试通过，包含只读 l4 客户端经真实回环 Zenoh 调用默认工具并收到 outcome。
测试边界止于 cmd 和起降命令转交，不部署或验收 cmd 下游。仅 EGO 完成完整验收，
其他后端不因保留源码或配置思路而被视为能力等价。

# dispatcher 直接向 planner 下发动作的决策

Status: implemented

日期：2026-09-16

依据：用户明确裁定退役 dispatcher 与 mission_executive 间的 `/mission/task`
中间转换层；现行行为约束归 `specs/implemented/inner/l3-execution-seam.spec.md`。

dispatcher 自己持有任务状态机，并经通用端口和 ROS 适配层直接下发 planner 动作。
不恢复独立 mission_executive 包、旧 mission FSM、`/mission/task` action 两端或
兼容路由。此前“保留 action 或选择替代原语”的开放选项在本轮裁定收敛为直接接入。

取消中间层不取消共享执行职责。实例归属、动作代次、真实反馈、结果判定、超时、
取消和急停仍须明确实现。core 保持六态分发和通用生命周期；技能持有领域语义，
共享执行模块持有通用账务，适配层集中通信，不把领域发布器搬回 engine。

后续 S3 只核实直连 planner 的具体消息、反馈、取消/停止和部署接线，不再选择是否
恢复旧 action。`action_result` 仅描述完成语义，并非 ROS action 实现要求。

本记录采纳的是架构方向，不表示直连能力已实现。本轮只修改文档；生产工具集合仍空，
代码阶段未启动，l4-agent 只读。接口取证与验证记录继续由迁移方案维护。

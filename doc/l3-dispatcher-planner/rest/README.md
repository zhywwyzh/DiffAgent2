# l3 待迁依赖与保留项入口

这里记录 DiffAgent2 新版中因 DiffAgent2 旧版 skill 或共享服务存在真实依赖而暂时保留的内容。它是**持续维护的迁移待办与调查资料**，不是另一份 spec；职责、端口和行为契约仍以 `specs/` 为准。

开始迁移或优化下列能力时，先读[保留项台账](dispatcher-deferred-dependencies.md)中的对应条目。即使只是在清理“没有当前调用方”的字段，也要先检查台账中的旧版消费者。

| 即将进行的工作 | 必须重新参考 | 当前状态 |
|----|----|----|
| 停止记录、任务覆盖、重置、记录服务 | [R01](dispatcher-deferred-dependencies.md#r01)、[R02](dispatcher-deferred-dependencies.md#r02)、[R06](dispatcher-deferred-dependencies.md#r06) | 保留接口/状态，记录能力未接入 |
| 飞行技能、急停悬停、执行缝、planner/飞控连接 | [R03](dispatcher-deferred-dependencies.md#r03)、[R05](dispatcher-deferred-dependencies.md#r05) | 仅有急停出站信号，完整执行链待验证 |
| 返回上一位置、返回原点、轨迹/过程历史 | [R04](dispatcher-deferred-dependencies.md#r04)、[R06](dispatcher-deferred-dependencies.md#r06) | 历史状态保留，消费者未迁入 |
| VLA 动作发布、重规划、动作结果接入 | [R05](dispatcher-deferred-dependencies.md#r05) | 上下文及清理保留，生产动作接口未迁入 |
| VLA 多图思考、搜索调试输出 | [R07](dispatcher-deferred-dependencies.md#r07) | 调试目录保留，VLA 消费者未迁入 |
| 队列精简、core 字段删除、宿主端口调整 | 全部条目及台账的“当前队列如何执行” | 不能仅凭新版无读点判定可删 |

每项已说明旧版生产方/消费者、新版位置、当前缺口、何时接入、建议改造位置、验收及可删除条件。未来处理时，在同一改动中更新该项为“已接入／已迁移归属／已删除／继续保留”，写明代码与测试证据、后续触发条件；同步本索引。不要把临时保留变成永久无人认领，也不要在接入时原样复制旧版私有属性访问或任务编号。

本轮实施和审核记录见[接口收紧方案](../iteration/design-dispatcher-interface-tightening.md)。当前默认生产工具集合仍为空；本台账不表示任何缺失 skill 已实现，也不要求在无关任务中顺手恢复旧工具。

## 基础飞行接入顺序（设计中）

后续执行先读[执行顺序与文档导航总纲](../iteration/design-dispatcher-migration-execution-order.md)，
按 S0–S6 依次进入对应规范、子方案和实现文件。直连方向已确定：不迁入
`/mission/task` 或独立 `mission_executive` 包；S3 仅核实 planner 直连端口和反馈。

1. 先完成 [l4 RPC 对接闭环方案](../iteration/design-dispatcher-l4-rpc-integration.md)：
   复用已有 RPC/租约/presence，补 owner token 监听、快速终态回传、重放 owner 门和
   拒绝信封；以工作区 `l4-agent/` 为只读消费者验证。此阶段仍为空生产工具集合，
   不修改 l4，不宣称安全停已经实现物理悬停。
2. 再实施 [基础飞行迁移方案](../iteration/design-dispatcher-basic-flight-migration.md)：
   对接现有六个 `basic_flight.*` 名字，完成 dispatcher 到 planner 的直接执行/反馈链和 R03/R05 飞行接线；R04
   本轮仅实现起飞原点服务，公开 `return` 为空参返回起飞点，不开放 previous。
3. 真实实现与测试完成后才注册生产能力、更新现行 spec/revision 和本索引；当前
   [RPC 提案](../../../specs/proposed/inner/l3-l4-rpc.spec.md)与
   [飞行动作提案](../../../specs/proposed/inner/flight-actions.spec.md)均未采纳。

R04 的逐步历史、游标和任务文本回退，R05 的 VLA 生产判据，以及 R01/R02/R06 的
记录服务依赖继续保留。两份方案不是实现证据，不能据此关闭台账条目。

# l3 待迁依赖与保留项入口

这里记录 DiffAgent2 新版中因 DiffAgent2 旧版 skill 或共享服务存在真实依赖而暂时保留的内容。它是**持续维护的迁移待办与调查资料**，不是另一份 spec；职责、端口和行为契约仍以 `specs/` 为准。

开始迁移或优化下列能力时，先读[保留项台账](dispatcher-deferred-dependencies.md)中的对应条目。即使只是在清理“没有当前调用方”的字段，也要先检查台账中的旧版消费者。

| 即将进行的工作 | 必须重新参考 | 当前状态 |
|----|----|----|
| 停止记录、任务覆盖、重置、记录服务 | [R01](dispatcher-deferred-dependencies.md#r01)、[R02](dispatcher-deferred-dependencies.md#r02)、[R06](dispatcher-deferred-dependencies.md#r06) | 保留接口/状态，记录能力未接入 |
| 飞行技能、急停悬停、执行缝、planner/飞控连接 | [R03](dispatcher-deferred-dependencies.md#r03)、[R05](dispatcher-deferred-dependencies.md#r05) | 取消覆盖已上行修正；修正版未重跑验证 |
| 返回上一位置、返回原点、轨迹/过程历史 | [R04](dispatcher-deferred-dependencies.md#r04)、[R06](dispatcher-deferred-dependencies.md#r06) | origin 已接入；逐步历史/文本消费者待迁 |
| VLA 动作发布、重规划、动作结果接入 | [R05](dispatcher-deferred-dependencies.md#r05) | 飞行动作账务已接入；VLA 专属判据待迁 |
| VLA 多图思考、搜索调试输出 | [R07](dispatcher-deferred-dependencies.md#r07) | 调试目录保留，VLA 消费者未迁入 |
| 队列精简、core 字段删除、宿主端口调整 | 全部条目及台账的“当前队列如何执行” | 不能仅凭新版无读点判定可删 |
| 去除 task-id、迁入原工具名、panorama 来源策略或来源日志 | [工具名与业务语义迁移遗留项](../../rest/task-id-to-tool-name-deferred.md) | 按名分发已接入，旧来源判据尚须逐项迁移；去编号不等于删除业务语义 |

每项已说明旧版生产方/消费者、新版位置、当前缺口、何时接入、建议改造位置、验收及可删除条件。未来处理时，在同一改动中更新该项为“已接入／已迁移归属／已删除／继续保留”，写明代码与测试证据、后续触发条件；同步本索引。不要把临时保留变成永久无人认领，也不要在接入时原样复制旧版私有属性访问或任务编号。

本轮实施和审核记录见[接口收紧方案](../iteration/20260915-20260917/design-dispatcher-interface-tightening.md)。当前默认集合已包含六个 basic_flight；其他技能的能力状态仍须按各自实现证据判断。

## 基础飞行接入结果

后续维护先读[执行总纲](../iteration/20260915-20260917/design-dispatcher-migration-execution-order.md)；此前实现完成过 S0–S6；当前已按用户要求将控制职责收回 dispatcher，修正版未重跑
测试。RPC 和六个 basic_flight 入口保留。
两份现行契约为 [RPC](../../../specs/implemented/inner/l3-l4-rpc.spec.md)与
[飞行动作](../../../specs/implemented/inner/flight-actions.spec.md)。

执行证据见 [RPC 方案](../iteration/20260915-20260917/design-dispatcher-l4-rpc-integration.md)与
[飞行方案 §11](../iteration/20260915-20260917/design-dispatcher-basic-flight-migration.md#11-完成记录2026-09-17)。
先前版本的完整验收为 115 passed，包含只读 l4、真实回环 Zenoh、正式入口与 EGO cmd；
该结果仅作历史，不覆盖当前职责修正。
未修改 l4 或旧版仓库；未验证 cmd 下游处理。

R03 的停止/保持意图现在由 dispatcher 经通用目标口编排，已撤回 planner 专属改动；R04 的起飞原点已接入，逐步历史、游标和任务文本回退
继续保留；R05 的飞行动作账务已接入，VLA 生产判据待迁。R01/R02/R06/R07 的记录与
调试依赖仍未交付，不随本次飞行功能完成而关闭。

## 日志规范与生产者迁移

严格日志要求见[日志契约](../../../specs/implemented/inner/observability-log.spec.md)。
[规范整理与日志迁移核对记录](spec-history-and-log-migration.md)保存旧版迁移状态线索，
并列出记录服务、场景工具事件及站端流水线的接入与验收条件。
R01/R02/R06 仍未关闭；本次只完成文档归属与一致性检查，没有新增运行验收证据。

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

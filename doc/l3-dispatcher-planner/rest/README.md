# l3 待迁依赖与保留项入口

这里记录 DiffAgent2 新版中因 DiffAgent2 旧版 skill 或共享服务存在真实依赖而暂时保留的内容。它是**持续维护的迁移待办与调查资料**，不是另一份 spec；职责、端口和行为契约仍以 `specs/` 为准。

开始迁移或优化下列能力时，先读[保留项台账](dispatcher-deferred-dependencies.md)中的对应条目。即使只是在清理“没有当前调用方”的字段，也要先检查台账中的旧版消费者。

| 即将进行的工作 | 必须重新参考 | 当前状态 |
|----|----|----|
| 停止记录、任务覆盖、重置、记录服务 | [R01](dispatcher-deferred-dependencies.md#r01)、[R02](dispatcher-deferred-dependencies.md#r02)、[R06](dispatcher-deferred-dependencies.md#r06) | 保留接口/状态，记录能力未接入 |
| 飞行技能、急停悬停、执行缝、planner/飞控连接 | [R03](dispatcher-deferred-dependencies.md#r03)、[R05](dispatcher-deferred-dependencies.md#r05) | 强制取消、任务释放和独立停止确认代码已接入；未编译、未验收 |
| 返回上一位置、返回原点、轨迹/过程历史 | [R04](dispatcher-deferred-dependencies.md#r04)、[R06](dispatcher-deferred-dependencies.md#r06) | origin 已接入；逐步历史/文本消费者待迁 |
| VLA 动作发布、重规划、动作结果接入 | [R05](dispatcher-deferred-dependencies.md#r05) | 2026-10-09 已修正失败收尾与多腿单终态、补批次后停稳，代码已接入但未验收； VLA 专属 REPLAN 已随机上收窄退役（终态腿）；记录消费仍挂账；`navigation.vla_rotate` 已补注册（2026-09-26） |
| VLA 多图思考、搜索调试输出 | [R07](dispatcher-deferred-dependencies.md#r07) | 旧消费者已随 VLM 迁云删除；孤儿字段由方案 P1 删除后关门 |
| 队列精简、core 字段删除、宿主端口调整 | 全部条目及台账的“当前队列如何执行” | 不能仅凭新版无读点判定可删 |
| 去除 task-id、迁入原工具名、panorama 来源策略或来源日志 | [工具名与业务语义迁移遗留项](../../rest/task-id-to-tool-name-deferred.md) | 按名分发已接入，旧来源判据尚须逐项迁移；去编号不等于删除业务语义 |
| 场景图能力迁移、对象导航下行、机上在线建图 | [R09](dispatcher-deferred-dependencies.md#r09) | 契约已先行（`l3-scenegraph` 等）；代码未迁；对象导航下行与在线建图不迁并登记；对象导航终态语义已按旧库 09-24 裁决同步进契约（2026-09-26） |

每项已说明旧版生产方/消费者、新版位置、当前缺口、何时接入、建议改造位置、验收及可删除条件。未来处理时，在同一改动中更新该项为“已接入／已迁移归属／已删除／继续保留”，写明代码与测试证据、后续触发条件；同步本索引。不要把临时保留变成永久无人认领，也不要在接入时原样复制旧版私有属性访问或任务编号。

本轮实施和审核记录见[接口收紧方案](../iteration/20260915-20260917/design-dispatcher-interface-tightening.md)。六个 basic_flight 已实现并注册；`navigation.vla_nav` 已随 [dispatcher VLA 技能迁移方案](../iteration/design-dispatcher-vla-migration.md) 进入契约（[工具面契约 §1](../../../specs/implemented/inner/l3-tool-plane.spec.md) 记录现行工具集合与 revision，`navigation.vla_rotate` 补注册后为 8 项），代码按 P1–P3 分期接入；其他技能的能力状态仍须按各自实现证据判断。

## 原生 action 接入（2026-10-09）

[原生 action 方案](../iteration/design-planner-native-action.md)已交付代码，未编译和验收。
R03/R05 的当前归属更新为 planner 原生 action 的停止与停稳、dispatcher 共用动作会话；
旧目标和进度消息退役。三个后端能力差异、配置迁移及剩余条件见台账最新条目。
此前直连 topic 记录为迁移历史，不作为现行接口说明。

## 基础飞行接入历史

后续维护先读[执行总纲](../iteration/20260915-20260917/design-dispatcher-migration-execution-order.md)；此前实现完成过 S0–S6；当前已按用户要求将控制职责收回 dispatcher，修正版未重跑
测试。RPC 和六个 basic_flight 入口保留。
两份现行契约为 [RPC](../../../specs/implemented/inner/l3-l4-rpc.spec.md)与
[飞行动作](../../../specs/implemented/inner/flight-actions.spec.md)。

执行证据见 [RPC 方案](../iteration/20260915-20260917/design-dispatcher-l4-rpc-integration.md)与
[飞行方案 §11](../iteration/20260915-20260917/design-dispatcher-basic-flight-migration.md#11-完成记录2026-09-17)。
先前版本的完整验收为 115 passed，包含只读 l4、真实回环 Zenoh、正式入口与 EGO cmd；
该结果仅作历史，不覆盖当前职责修正。
未修改 l4 或旧版仓库；未验证 cmd 下游处理。

此前 R03 的停止/保持意图由 dispatcher 经通用目标口编排；此归属已被上述原生 action 方案替代。R04 的起飞原点已接入，逐步历史、游标和任务文本回退
继续保留；R05 的飞行动作账务已接入，VLA 专属 REPLAN 已随 [机上收窄方案](../iteration/design-dispatcher-vla-waypoint-executor-migration.md)
退役（station 解算 waypoint 后机上为终态腿，无 replan；归档见
[2026-09-20 决策](../../../specs/implemented/architecture/2026-09-20-vla-waypoint-executor.md)；记录消费仍挂账）。R01/R02/R06
的记录依赖仍未交付；R07 孤儿字段已随方案 P1 删除并关门（删后 `l3-dispatcher-planner/` 全树
grep 零命中，见台账 R07 证据）。上述保留项不随本次飞行功能完成而关闭。

## 日志规范与生产者迁移

严格日志要求见[日志契约](../../../specs/implemented/inner/observability-log.spec.md)。
[规范整理与日志迁移核对记录](spec-history-and-log-migration.md)保存旧版迁移状态线索，
并列出记录服务、场景工具事件及站端流水线的接入与验收条件。
R01/R02/R06 仍未关闭；本次只完成文档归属与一致性检查，没有新增运行验收证据。

## 直连任务结果收敛历史（2026-10-09）

[方案](../iteration/design-flight-vla-result-convergence.md)已完成代码交付：
VLA 失败不再推进成功；位置、终末偏航及贴地腿全部完成才结束调用；
两家族批次完成后追加原目标动态停稳门，旋转增加实际累计偏航核对。
该阶段高度及停稳参数由 FlightConfig 统一持有，后续原生 action 已将公共参数归到 `/planner_execution`；旧 VLA 高度/近点参数需迁移，
贴地须显式配置地面高度。实现归属及剩余条件见台账文末。

本轮未运行测试、构建或验收，不能据此宣称与 DiffAgent2 旧版运行结果等价；
R03 和 R05 的运行证据仍待使用者明确许可后补充。


## 强制取消与当前任务资源释放（2026-10-10）

[优化方案](../iteration/design-task-cancel-emergency-hover.md)已交付本地代码：取消不排普通队列，
立即请求悬停并释放旧调用及动作 owner，设备停止确认独立跟踪；建图、地图、定位和有效原点保留。
EGO/SUPER 本地命令输出增加停止仲裁，DIFF 独立轨迹跟踪端增加输出代次和保持回执。
R03/R05 仍需受控停止及恢复证据；CoPaw 按钮实现及其至设备的完整链路未在本仓库中定位，不能声明端到端已接通。

## 未接入目标预留清理（2026-10-10）

按用户明确要求，[清理方案](../iteration/design-remove-unused-follow-reservation.md)已删除未接入的目标跟随字段、全部消费方及相关外部接入预留说明。
此前历史保留决定不再适用于现行接口；通用感知缓存与偏航控制继续保留。
本轮仅完成代码修改，未运行测试、门禁、构建或验收；消息签名变化须在后续部署前同步生成并构建相关消费方。

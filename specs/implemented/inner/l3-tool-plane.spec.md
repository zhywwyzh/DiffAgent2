# l3 工具面契约

Status: implemented

Contract-ID: l3-dispatcher/tool-plane
Parent: specs/implemented/l3-dispatcher.spec.md

> 拥有 l3 工具控制面（发现、调用、事件、取消与连接租约）的对外协议不变量。
> 覆盖：工具发现面、按名分发与准入、飞行独占与同源抢占、取消、事件账本、
> 连接租约与 owner 门、并发/重放与完成语义，及其承载传输（单入口控制面）。
> 边界：技能如何实现归 `l3-skill-contract`；core 的分发语义与未注册失败归
> `l3-core-boundary`；ROS 收发隔离归 `l3-ros-adapter-boundary`；本契约不
> 涉及 ROS 概念。

## 1. 工具发现面

- 注册面恰为已实现、已测试的工具集合；每项携带 `name`、`title`、
  `description`、`inputSchema`、`outputSchema`、`annotations` 与 `_meta`。
- `_meta` 键集恰为 `lx.completion`（完成语义）与 `lx.concurrency`
  （并发语义，当前全部为 `flight-exclusive`）。控制面不携带、不派生任何
  任务编号标识（`l3-core-boundary` B2/B7/B8）。
- `revision` = 工具元数据按 canonical compact JSON（键排序、去空白、非
  ASCII 不转义）序列化后的 SHA-256，带 `sha256:` 前缀；随元数据任何字节级
  变化而变化，对同一注册面唯一且可复现。
- 无公开的启停开关；列表不随瞬时就绪状态抖动。

**当前生产工具集合**：`basic_flight.takeoff`、`basic_flight.land`、
`basic_flight.translate`、`basic_flight.rotate`、`basic_flight.return`、
`basic_flight.emergency_stop`、`navigation.vla_nav`。基础飞行动作参数与
完成语义归 [基础飞行动作契约](flight-actions.spec.md)；`navigation.vla_nav`
的元数据见下。测试自有能力不注册到生产默认集合；后续能力同样须有完整
实现与测试。

**`navigation.vla_nav`**：station 解算航点的执行载体——站端以「累积点云（最新，
世界系）+ 位姿按帧时戳插值 + VLM bbox」解算 `waypoint_world` 后下发，机上为
航点执行器（无 bbox 消费、无几何解算）。完成语义 `action_result`，
`requires_perception=false`（机上仅需 odometry，由共享执行校验），并发语义同 §4
飞行独占。`title` 为 `Reach a visual target`；`description` 为
`Reach a station-grounded visual target: consume the station-resolved
waypoint (world frame, computed on the station from the grounded bbox +
accumulated cloud + pose@image_stamp) and execute it as one terminal
leg.`；`outputSchema` 为空 object（`type=object`、`properties={}`、
`additionalProperties=false`）。`inputSchema` 顶层 `type=object`、
`additionalProperties=false`，字段：

| 字段 | 必填 | 规则 |
|------|------|------|
| `object` | 是 | `string`，`minLength=1` |
| `prompt` | 是 | `string`，`minLength=1` |
| `waypoint_world` | 是 | `array[number]`，恰 3 项（x,y,z，world/ENU）；有限性由技能 fail-closed，不进 schema |
| `yaw` | 否 | `number`；终末偏航，缺省 `look_forward` |
| `look_forward` | 否 | `boolean`，缺省 `true` |

> schema 与 DiffAgent2 旧版 `tools/registry.py` 同名 ToolSpec 对齐，仅无任务
> 编号（`l3-core-boundary` B2/B7/B8；migration-protocol G23）。原 grounded 字段
> （`bbox_1000`/`image_stamp`/`image_width`/`image_height`/`visible`/`finish`/
> `provider`/`side`/`distance_m`）由站端消费，不再下行。

**`revision` 记录值（现行）**：`sha256:45c6030faffd0bf2254a6c96da8c0c7bf0f193a1e0ea829f64f7d8929b81e4f7`

**目标集合（未注册，2026-09-20 登记）**：`scene.map_search`、`scene.navigate`、
`scene_nav.graph.list`、`scene_nav.graph.select`、`scene_nav.graph.save`、
`scene_nav.graph.objects`、`scene_nav.graph.object_pose`。这七项**尚未实现、
未测试、未注册**，不进入现行发现面，现行 `revision` 不变；实现与测试同批交付后
才并入现行集合并重算 `revision`（`l3-dispatcher/migration-protocol` §1、§2-⑦：
文档登记不构成生产能力，不豁免「不留桩」）。

| 工具名 | `inputSchema` 字段 | 完成语义 | 并发语义 |
|--------|--------------------|----------|----------|
| `scene.map_search` | `object`（必填，`string`，`minLength=1`） | `workflow_result` | `flight-exclusive` |
| `scene.navigate` | `object_id`（必填，`integer`） | `workflow_result` | `flight-exclusive` |
| `scene_nav.graph.list` | 无 | `workflow_result` | `flight-exclusive` |
| `scene_nav.graph.select` | `graph`（必填，`string`，`minLength=1`） | `workflow_result` | `flight-exclusive` |
| `scene_nav.graph.save` | `graph`（可选，`string`，`minLength=1`） | `workflow_result` | `flight-exclusive` |
| `scene_nav.graph.objects` | `graph`（可选，`string`）、`label`（可选，`string`） | `workflow_result` | `flight-exclusive` |
| `scene_nav.graph.object_pose` | `graph`（可选，`string`）、`object_id`（必填，`integer`）、`pos`（可选，`array[number]` 恰 3 项）、`yaw`（可选，`number`）、`delta_pos_local`（可选，同 `pos`）、`delta_rot_local_xyzw`（可选，`array[number]` 恰 4 项）、`apply`（可选，`boolean`） | `workflow_result` | `flight-exclusive` |

- 上表 `inputSchema` 顶层均为 `type=object`、`additionalProperties=false`；
  `scene_nav.graph.list` 的 `outputSchema` 为空 object，其余为非空 object
  （结果字段由 `l3-dispatcher/skill-contract` 的家族条目与该能力叶契约定义）。
- `scene.navigate` 的终态必须携带对象级结果（对象身份、到达与否、最终位置、
  最终偏航、失败原因），不得只上报航点完成（`l3-dispatcher/scenegraph` §6）。
- 编辑与保存类工具的写操作**经 builder 的 HTTP 面**执行，dispatcher 不直接写图
  （`l3-dispatcher/scenegraph` §8）。
- **有意变更登记**：旧库 wire 别名 `navigation.scene_graph_nav`（本地把 `object`
  解析为 `object_id`）**不恢复**——按 §2 未注册名一律拒绝，且
  `l3-dispatcher/migration-protocol` §4 禁止遗留垫片；旧调用方须改用
  `scene.navigate` 并直接携带 `object_id`（对象语义在站端解析）。

## 2. 按名分发与准入

- `name` 是分发、查找与重放关联的唯一键；任务识别到能力归属之间不存在
  任何编号或枚举映射层（`l3-core-boundary` B8）。
- 未注册名一律拒绝，准入子原因为 `tool_not_registered`。
- 执行方法请求必带调用关联键 `call_id`；缺失即拒绝为 `invalid_arguments`。
- `arguments` 按该工具 schema 严格校验：未知键、缺键、类型不符、非有限数
  与错误元数一律拒绝；失败属 `invalid_arguments`，子原因区分
  `unknown_argument`、`missing_required_argument`、`argument_out_of_range`。
- 注册表是 schema 校验与工具发现的唯一来源。

## 3. 承载传输与拒绝信封

线上 admission/outcome、task presence 与连接监听的精确信封和生命周期归
[l4 RPC 契约](l3-l4-rpc.spec.md)。本叶的 runtime ack/event、发现、事件游标和取消
描述进程内能力，不表示站端存在对应的发现/轮询/取消 RPC 方法。

- 控制面是唯一活跃入口：单 key `lx/<stack-id>/rpc`，一站一入口；请求形如
  `{"method", "params"}`，`params.context` 携带连接身份三元组（见 §6）。
- 成功回复 `{"type":"rpc_result","method","result"}`；拒绝回复
  `{"type":"rpc_error","method","reason","message"}`。
- 传输层拒绝 reason 词表（固定）：`method_not_found`、`invalid_arguments`、
  `connection_not_owner`、`connection_busy`、`wrong_state`、`internal_error`。
  `transport_unavailable` 在本控制面无实现证据，未采纳，待实现侧补证后再议。
- 准入子原因词表（固定）：`tool_not_registered`、`call_id_conflict`、
  `call_not_found`、`already_terminal`、`connection_active`、`invalid_cursor`、
  `unknown_argument`、`missing_required_argument`、`argument_out_of_range`、
  `invalid_request`。
- wire 名的归一只作用于名字解析，不产生第二注册面。
- 每个 queryable 必须以完整语义应答，不半途留挂。

## 4. 飞行独占与同源抢占

- 飞行独占槽唯一：每个 stack 至多一个持有飞行槽的非终态调用。
- 存在持槽调用时，来自异源（不同 station 实例）的新普通调用拒绝为
  `flight_busy`；来自同 station 实例的新指令可抢占——旧调用立即失去飞行槽
  并保证收敛为恰好一个 `fail` 终态（异步），新调用随即接管槽位。
- 当前无豁免同源约束的工具；所有已注册调用均经过同一 owner 门。

## 5. 取消

- 取消幂等。
- 未知调用 → `call_not_found`；已终态调用 → `already_terminal`（不重复
  终态）。
- 被接受的取消恰好收敛为一个 `fail` 终态事件，错误码 `cancelled`。
- 取消不隐含急停；全局安全停止经核心端口执行，不伪造工具调用。

## 6. 连接租约与 owner 门

- 连接身份三元组：`station_id` + `station_instance_id` + `lease_id`；
  `stack_id` 即 key 前缀，不作为 payload 字段。
- 一 station 至多连一 stack，一 stack 至多连一 station（严格一一）。
- 发现与连接状态查询免租约；调用、事件与取消必须携带当前有效租约。
  缺失、过期或不匹配 → `connection_not_owner`；任何工具无非
  owner 旁路。
- acquire 冲突 → `connection_busy`（附当前 owner 与过期时刻）；同身份重复
  acquire 幂等返回原租约。默认 TTL 15 s，renew 周期不慢于 5 s；renew 与
  release 对当前 owner 幂等。存在非终态调用时显式 release 拒绝为
  `connection_active`。
- 租约丢失走有序安全状态机（持有 → 丢失 → 取消中 → 已请求安全停 →
  无主），安全停失败即 fail-closed 停在取消中；活动调用收敛为一个
  `fail` 终态，错误码 `connection_lost`，随后经注入的核心全局停止端口执行安全停。端口缺失或执行失败时保持取消中，不得释放为无主。

## 7. 事件账本与调用关联

- 事件仅按调用关联键 `call_id` 关联，不引入其他关联维度。
- 事件账本有界重放：游标轮询（`after_seq` + `limit`）；`seq` 在单运行时内
  单调递增；`event_id` 跨重启全局唯一。
- 只返回该租约的事件；对其他租约的事件，游标直接越过。
- 游标过期或超前时给出确定性复位原因（`event_history_expired`、
  `client_cursor_ahead`）。
- 事件可见性按租约过滤；同一调用的事件序列不得跨租约泄漏。

## 8. 终态唯一

- 事件 status 恰为 `running`、`done`、`fail` 三值。
- 事件 phase 词表固定为：`accepted`、`perceiving`、`planning`、
  `dispatching`、`executing`、`result_ready`、`done`、`fail`；映射层对
  词表外的 phase 一律按 `running` 归一。
- 每个已准入调用恰好一个终态事件（`done` 或 `fail`）；迟到或重复的终态
  被忽略。
- ack 只表示已准入，绝不表示完成；完成只由终态事件表达。

## 9. 并发、重放与完成语义

- 同一 `call_id` 同载荷重放：返回原 ack，不二次执行。
- 同一 `call_id` 异载荷：拒绝为 `call_id_conflict`。
- 完成语义恰为三值：`forwarded`（已转交下游）、`action_result`（以下游
  动作结果为准）、`workflow_result`（以工作流结果为准）；生产能力在注册元数据中声明完成语义。
- 传输超时、进程存活、容器就绪绝不算成功完成。

## 10. 门禁

| 门禁 | 检查 |
|------|------|
| G24 | 发现面断言：工具名集合 == §1 **现行集合**（六个基础飞行动作 + `navigation.vla_nav`），`revision` == §1 记录的现行值；§1 目标集合不计入本断言 |
| G25 | 进程内 runtime ack 与事件键集判定（必备键子集 + 负例）：ack 必含 `call_id` 与租约身份三键；事件必含 `call_id`/`status`/`phase`/`event_id`/`seq`；status ⊆ §8 三值、phase ⊆ §8 词表；二者均不得携带任务编号标识 |
| G26 | 代码产出的拒绝 reason 集合 ⊆ §3 两层词表；新增 reason 须先改本契约 |
| G27 | 负例判定：未注册名 → `tool_not_registered`；异源占用 → `flight_busy`；非 owner→ `connection_not_owner` |
| G28 | 每个已准入调用恰有一个终态事件；同 `call_id` 同载荷重放返回原 ack |

> G24–G28 为本叶新增，与既有 G1–G23 全局编号不冲突。`specs/tools/*` 门禁
> 引擎迁移前，以等价命令与既有 pytest 承担判定。
>
> **统一声明**：除非使用者明确许可，否则跳过验收测试工作（`AGENTS.md` 硬性约束 §9）。

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

**工具清单（14 项）与完成语义**：

| 工具名 | 完成语义 |
|---|---|
| `navigation.vla_reach` | `workflow_result` |
| `scene.map_search` | `workflow_result` |
| `scene.navigate` | `workflow_result` |
| `flight.takeoff` | `forwarded` |
| `flight.land` | `forwarded` |
| `flight.translate` | `action_result` |
| `flight.rotate` | `action_result` |
| `flight.return` | `action_result` |
| `flight.emergency_stop` | `forwarded` |
| `scene_nav.graph.list` | `workflow_result` |
| `scene_nav.graph.select` | `workflow_result` |
| `scene_nav.graph.save` | `workflow_result` |
| `scene_nav.graph.objects` | `workflow_result` |
| `scene_nav.graph.object_pose` | `workflow_result` |

**`revision` 记录值（现行）**：`sha256:333e24d208bcdfa34efa75c45b2377761503dc401999433eb3ec891a82ea2276`

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
  `invalid_request`、`object_not_resolved`。
- wire 名的归一只作用于名字解析，不产生第二注册面。
- 每个 queryable 必须以完整语义应答，不半途留挂。

## 4. 飞行独占与同源抢占

- 飞行独占槽唯一：每个 stack 至多一个持有飞行槽的非终态调用。
- 存在持槽调用时，来自异源（不同 station 实例）的新普通调用拒绝为
  `flight_busy`；来自同 station 实例的新指令可抢占——旧调用立即失去飞行槽
  并保证收敛为恰好一个 `fail` 终态（异步），新调用随即接管槽位。
- `flight.emergency_stop` 是唯一豁免同源约束的抢占工具（异源亦可抢占），
  且仍受 owner 门约束，无旁路。

## 5. 取消

- 取消幂等。
- 未知调用 → `call_not_found`；已终态调用 → `already_terminal`（不重复
  终态）。
- 被接受的取消恰好收敛为一个 `fail` 终态事件，错误码 `cancelled`。
- 取消不隐含急停；急停是显式的 `flight.emergency_stop` 调用。

## 6. 连接租约与 owner 门

- 连接身份三元组：`station_id` + `station_instance_id` + `lease_id`；
  `stack_id` 即 key 前缀，不作为 payload 字段。
- 一 station 至多连一 stack，一 stack 至多连一 station（严格一一）。
- 发现与连接状态查询免租约；调用、事件与取消必须携带当前有效租约。
  缺失、过期或不匹配 → `connection_not_owner`；任何工具（含急停）无非
  owner 旁路。
- acquire 冲突 → `connection_busy`（附当前 owner 与过期时刻）；同身份重复
  acquire 幂等返回原租约。默认 TTL 15 s，renew 周期不慢于 5 s；renew 与
  release 对当前 owner 幂等。存在非终态调用时显式 release 拒绝为
  `connection_active`。
- 租约丢失走有序安全状态机（持有 → 丢失 → 取消中 → 已请求安全停 →
  无主），安全停失败即 fail-closed 停在取消中；活动调用收敛为一个
  `fail` 终态，错误码 `connection_lost`，随后执行与急停相同的安全停。

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
  动作结果为准）、`workflow_result`（以工作流结果为准）；每工具取值见
  §1 清单。
- 传输超时、进程存活、容器就绪绝不算成功完成。

## 10. 门禁

| 门禁 | 检查 |
|------|------|
| G24 | 发现面断言：工具名集合 == §1 清单（14 项），`revision` == §1 记录的现行值 |
| G25 | ack 与事件键集判定（必备键子集 + 负例）：ack 必含 `call_id` 与租约身份三键；事件必含 `call_id`/`status`/`phase`/`event_id`/`seq`；status ⊆ §8 三值、phase ⊆ §8 词表；二者均不得携带任务编号标识 |
| G26 | 代码产出的拒绝 reason 集合 ⊆ §3 两层词表；新增 reason 须先改本契约 |
| G27 | 负例判定：未注册名 → `tool_not_registered`；异源占用 → `flight_busy`；非 owner（含急停）→ `connection_not_owner` |
| G28 | 每个已准入调用恰有一个终态事件；同 `call_id` 同载荷重放返回原 ack |

> G24–G28 为本叶新增，与既有 G1–G23 全局编号不冲突。`specs/tools/*` 门禁
> 引擎迁移前，以等价命令与既有 pytest 承担判定。

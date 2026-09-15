# l3 工具面契约补齐 方案

> 摘要：本文件是总纲 `doc/l3-dispatcher-planner/iteration/design-dispatcher-architecture-stabilization.md`
> 的**后续轮次 S7**（不在 S0–S6 序列内）。目标：把「工具面（`ros_packages/dispatcher/dispatcher/tools/`
> 与其传输面）的对外协议不变量」从旧库 spec **补齐进新库 `specs/`**，使 S5/S6 之后的判定与门禁
> 在新库内有权威。本方案**只写契约**，不改代码、契约正文、测试；代码对齐由既有各期负责。
>
> **需用户显式放行**：`specs/` 不在默认编辑目标树（`l3-dispatcher-planner/`）内。

## 0. 元信息

| 项 | 值 |
|----|----|
| 日期 | 2026-09-12 |
| 目标路径 | 新增 `specs/proposed/inner/l3-tool-plane.spec.md`（P1 晋升后为 `specs/implemented/inner/l3-tool-plane.spec.md`；均需放行）；本方案文件 `doc/l3-dispatcher-planner/iteration/design-dispatcher-tool-plane-contract.md` |
| 状态 | done（2026-09-12 执行完毕；deep-oracle 六项处置全部完成，F3 已登记，见 §11 附录） |
| 期 | **S7（后续轮次，不在 S0–S6 序列内）** |
| 行为影响 | 纯契约；零代码改动 |
| 前置 | S1（契约修订口径与有意变更登记）、S5（编号退役，含 `revision` 新值与 ack/事件键集）、S6（未注册分发 done→fail） |
| 需用户显式放行 | **是：`specs/` 不在默认编辑目标树内** |
| 关联文档 | 总纲（§4.1 目标树、§4.2 一层依赖矩阵、§4.3 命名、§4.4 门禁表 A6、§4.7 路线图「后续轮次」行、§4.8 文档集）；姊妹篇 S1 `design-dispatcher-spec-reconciliation.md`、S5 `design-dispatcher-taskid-retirement-full.md`、S6 `design-dispatcher-dispatch-fail-semantics.md`；模板 `_TEMPLATE.md` |
| 契约依据 | `specs/README.md`（生命周期布局、根叶分层、命名与 header、规则 1–5）、`specs/implemented/l3-dispatcher.spec.md`、`specs/implemented/inner/{l3-core-boundary,l3-ros-adapter-boundary,l3-skill-contract,l3-migration-protocol}.spec.md` |
| 内容来源（只读） | 旧库（DiffAgent2 旧版）`diff-dockers/specs/implemented/inner/agent-station-tools.spec.md`（v7 权威）、`agent-station-fleet.spec.md`、`diff-dockers/specs/proposed/inner/agent-station-rpc.spec.md`、`agent-station-channels.spec.md`（**仅作迁移历史**） |
| 路径约定 | 全文一律用**相对路径**（`l3-dispatcher-planner/…`、`specs/…`、`diff-dockers/…`、`doc/…`）；不写主机绝对路径与个人标识 |

## 1. 背景与动机

- **`specs/` 是唯一权威**（`specs/README.md#L82-L92` 规则 1/2/3：每个 spec 一个权威、
  不得重建项目本地 spec、实现不得分叉）。但**工具面的对外协议在新库 `specs/` 里没有归属**：
  新库现有 3 根（`l3-dispatcher` / `topology` / `development-workflow`）与 7 叶
  （`inner/{l3-core-boundary, l3-ros-adapter-boundary, l3-execution-seam, l3-skill-contract,
  l3-migration-protocol, l3-coding-style, entity-naming}`），没有任何一份拥有工具发现面、
  准入/拒绝词表、飞行独占、恰好一个终态事件、`call_id` 关联、连接租约身份、`revision` 语义。
- 这些不变量目前**只存在于旧库**（`diff-dockers/specs/**`），新库代码却已按它们实现——
  即「实现有新库、契约只在旧库」，违反「一个权威」（`specs/README.md#L82-L83`），
  使 S5/S6 的判定缺少新库内的判据。
- 本方案只做一件事：**补契约**（新增 1 个叶）。不改代码、不迁技能族、不动 `tools/<family>/`、
  不改任何对外字段（字段级变更由 S5/S6 负责）。代码对齐既有各期。

## 2. 现状事实（问题清单）

> 每条 = 路径 + 本次实测行号 + 现象。行号均为本次读取所得。

### 2.1 新库 `specs/` 缺工具面权威

- 3 根：`specs/implemented/l3-dispatcher.spec.md`、`topology.spec.md`、`development-workflow.spec.md`；
  7 叶：`specs/implemented/inner/{l3-core-boundary,l3-ros-adapter-boundary,l3-execution-seam,
  l3-skill-contract,l3-migration-protocol,l3-coding-style,entity-naming}.spec.md`。
- `specs/implemented/l3-dispatcher.spec.md#L32-L42` 的 `## Inner contracts` 表只列 5 个叶
  （core-boundary / ros-adapter-boundary / execution-seam / skill-contract / migration-protocol，
  另两个分挂 `topology`、`development-workflow` 根）；**无工具面叶**。
- `specs/implemented/l3-dispatcher.spec.md#L25-L28` 只有两条与工具面沾边的骨架不变量
  （「未注册即失败」「终态唯一」），**没有**发现面、`revision`、准入/拒绝词表、`call_id` 关联、
  连接租约身份、飞行独占的任何条款。
- 实测检索（`tools/|tool plane|工具面|revision` 于 `specs/`）：仅命中 `specs/README.md#L23`
  （门禁引擎目录 `tools/`，与此无关）、`#L94`（门禁脚本）、`l3-core-boundary#L27`
  （作为反例的 import 路径 `tools/vla`）、`entity-naming#L38/#L42`（`specs/tools/` 脚本目录）。
  **结论：新库 `specs/` 工具面权威为零。**

### 2.2 旧库工具面不变量的分布（内容来源；逐条抄要点 + 行号）

`diff-dockers/specs/implemented/inner/agent-station-tools.spec.md`（自称 v7 权威，`#L7-L11`）：

- `#L25-L36` 五条根本规则：按稳定 `name` 分发、**task ids never appear on the wire**（`#L25`）；
  只有已实现、已测试的能力出现在 `tools/list`（`#L26`）；保留编号不得静默转 0（`#L27`）；
  工具用窄 ROS 端口组合（`#L28-L29`）；`ToolRuntime` 拥有关联、独占、取消、进度与**恰好一个终态事件**（`#L30-L31`）；
  prompt 仅显示/感知输入，控制语义在 schema 校验的 `arguments`（`#L32-L33`）；**无 JSON-RPC envelope，
  一次 zenoh key 一次操作**（`#L35-L36`）。
- `#L40-L71` 14 工具注册表（name / task id 标签 / 参数 / ROS 出口 / completion）；`#L63-L67`
  编号是 l4 内部 plan/history 标签、保留号不得出现在 `tools/list`、调保留号返回 `tool_not_registered`。
- `#L73-L106` 参数 schema 严格校验（未知键/缺键/布尔当数/非有限数/错误元数一律拒绝）；
  `#L104-L106` l3 registry 是校验与 JSON Schema 生成的唯一来源。
- `#L108-L139` 工具模型（`name/title/description/inputSchema/outputSchema/annotations/_meta`；
  `_meta` 含 `lx.completion`/`lx.concurrency`）；`#L137-L139` 无公开 `enabled` 开关、列表不随瞬时就绪抖动。
- `#L141-L174` 六个 zenoh key（`tools/list`、`tools/call`、`tools/events`、`tools/cancel`、
  `grasp_result/<session>/<step>`、`health`）；`#L149-L158` 每个 queryable 必须 `complete=true`；
  `#L169-L173` 已退役的 `scenegraph/*`、`task/start`、`task/events` 不得再声明，无双路径兼容期。
- `#L175-L191` `tools/list`：`revision` = 有序工具元数据 canonical compact JSON 的 SHA-256。
- `#L193-L244` `tools/call`：`call_id` + `name` + `arguments` + `context{station_id,station_instance_id,lease_id}`；
  `call_id` 是站端作用域关联键；未广告名 → `tool_not_registered`；ack 只表示**已准入、绝非完成**；
  同一 `call_id` 同载荷重放返回原 ack、不二次执行，异载荷 → `call_id_conflict`。
- `#L246-L295` `tools/events`：游标轮询（`after_seq`/`limit`）、有界重放、`seq` 每运行时单调、
  `event_id` 跨重启全局唯一 `evt_<uuid8>_<seq>`；只返回该租约的事件、`next_seq` 越过外来事件；
  仅按 `call_id` 关联；status 恰为 `running|done|fail`，phase 为
  `accepted|perceiving|planning|dispatching|executing|result_ready|done|fail`；
  **每个已准入调用恰好一个终态事件**，迟到/重复终态被 `ToolRuntime` 忽略。
- `#L297-L319` `tools/cancel`：幂等；未知调用 → `call_not_found`；终态调用 → `already_terminal`；
  接受的取消结束为**一个 `fail` 事件**（`error.code="cancelled"`）；**不隐含急停**。
- `#L321-L335` 失败信封与 reason 词表（`-32601` lookup、`-32602` schema、`-32603` 缺陷、
  `-32000` 业务拒绝：`flight_busy`、`connection_not_owner`、`connection_busy`、`connection_active`、
  `call_id_conflict`、`call_not_found`、`ros_unavailable`、`load_refused`、`reset_failed`）。
- `#L337-L384` 运行架构：registry + runtime + 窄适配器；适配器不持全局传输状态。
- `#L386-L416` 并发与完成：全部工具 `flight-exclusive`；**每 stack 至多一个非终态调用**；
  新普通调用在活动调用期间 → `flight_busy`；`flight.emergency_stop` 是唯一抢占工具但**仍 owner-only**；
  completion 语义 `forwarded` / `action_result` / `workflow_result`；传输超时/进程存活/pod 就绪
  **绝不算成功完成**。
- `#L437-L456` 验收（6 组测试，含确定性 `revision`、保留号拒绝、恰好一终态、重启安全 event id）。

`diff-dockers/specs/implemented/inner/agent-station-fleet.spec.md`：

- `#L23-L31` 不变量：一 station 至多连一 stack、一 stack 至多连一 station（严格一一）；
  **只有连接 owner 可收日志/遥测并调用任何工具（含 `flight.emergency_stop`）**；
  连接丢失→取消活动调用→请求既有安全停→再释放 stack。
- `#L43-L55` 身份四元组：`stack_id` / `station_id`（安装期稳定）/ `instance_id`（进程启动随机）/
  `lease_id`（成功 acquire 返回的不透明随机 id）；重复身份被拒。
- `#L91-L137` 连接查询面 `acquire`/`renew`/`release`/`status`（key 在 `lx/<stack-id>/connection/`，
  `complete=true`）；acquire 冲突 → `reply.err` `-32000` reason `connection_busy`（带当前 owner 与过期时刻）；
  默认 TTL 15 s、renew 不慢于 5 s；renew/release 对当前 owner 幂等。
- `#L139-L162` owner 作用域工具面：`tools/list`/`health`/`connection/status` 免租约；
  `tools/call`/`tools/events`/`tools/cancel` 需要当前租约；缺失/过期/不匹配租约 →
  `reply.err` `-32000` reason `connection_not_owner`；**非 owner 无急停旁路**。
- `#L185-L203` 租约丢失安全状态机：`OWNED -> LEASE_LOST -> CANCELLING -> SAFETY_REQUESTED -> UNOWNED`；
  过期或 owner-token 丢失立即停止准入，若有活动调用则取消并发**一个** `fail`（`error.code="connection_lost"`），
  随后走与 `flight.emergency_stop` 相同的安全停；活动调用期间显式 release 被拒为 `connection_active`。

`diff-dockers/specs/proposed/inner/agent-station-rpc.spec.md`（**状态 proposed**，当前 wire 契约的来源之一）：

- `#L41-L63` 单 key `lx/<stack-id>/rpc`；请求 `{"method", "params": {…, "context": {station_id,
  station_instance_id, lease_id}}}`；成功 `{"type":"rpc_result","method","result"}`；
  拒绝 `{"type":"rpc_error","method","reason","message"}`。
- `#L65-L67` 原型 reason 词表：`connection_not_owner`、`connection_busy`、`invalid_arguments`、
  `wrong_state`、`method_not_found`、`transport_unavailable`。
- `#L68-L74` 静态方法表：`connection.acquire|renew|release|status` + 执行方法（飞行/导航）；
  执行方法须在 `params.context` 携带有效租约身份。
- `#L128-L137` 权威过渡：本提案**不制造第二个活权威**；`agent-station-tools.spec.md`（implemented）
  在 Phase B 退役 `tools/*` 前仍是唯一权威。

`diff-dockers/specs/implemented/inner/agent-station-channels.spec.md`（**v6 任务面文本已作废**）：

- `#L36-L40`（v7 change）明示：可执行控制语义、发现、调用、生命周期与取消**移到**
  `agent-station-tools.spec.md`；该 spec **取代本文 v6 §3 的任务措辞**；实现只暴露
  `tools/list|call|events|cancel`，`task/start` 与 `task/events` 退役、无兼容别名。
- `#L407-L411`（§3 内「v7 authority」声明）再次明示：本节保留的 v6 任务面文本
  **仅作迁移历史，MUST NOT 用于实现 `task/start` 或 `task/events`**。
  → **本文 v6 条文（`#L42-L53`、§3.1–§3.12 的 task_id 词表/`task_ack`/`task_event` 等）
  一律不得作为新契约来源。**

`diff-dockers/specs/implemented/inner/l4-agent-station-monitor.spec.md`：

- 实测检索（`tools/|tool_event|revision|call_id`）**零命中**→ 与工具面无关，**不引用**。

### 2.3 新库实现当前真实行为（契约必须覆盖的行为面）

> `PKG = l3-dispatcher-planner/ros_packages/dispatcher/`。以下为本次实测行号。

发现面（registry）：

- `PKG/dispatcher/tools/registry.py#L31-L235` — `_specs()` 返回**恰 14 个** `ToolSpec`；
  名字集合实测为 `navigation.vla_reach, scene.map_search, scene.navigate, flight.{takeoff,land,translate,
  rotate,return,emergency_stop}, scene_nav.graph.{list,select,save,objects,object_pose}`。
- `#L252-L261` — `list_tools()`：`canonical = json.dumps(tools, ensure_ascii=False, sort_keys=True,
  separators=(",", ":"))`，`revision = "sha256:" + sha256(canonical)`（`#L254-L255`）。
  本次实测值：`sha256:cc1dcd1bcfa6f33fa10222042918a234ddcf2eddd7a79b96925194a981c0d69b`（长度 71）。
- `PKG/dispatcher/tools/model.py#L96-L111` — `public_dict()` 键集 =
  `name, title, description, inputSchema, outputSchema, annotations{destructiveHint,idempotentHint},
  _meta`；`_meta` 实测键集 = `lx.task_id`（`#L108`）、`lx.completion`（`#L109`）、
  `lx.concurrency`（`#L110`，恒 `"flight-exclusive"`）。
- 实现偏差：`PKG/dispatcher/rpc_plane.py#L11-L16` 的 docstring 自称「PREPARED, NOT ACTIVATED、
  env-gated behind `L3_RPC_PLANE`」，但 `PKG/dispatcher/zenoh_rpc.py#L174-L179` 在 `start()` 内
  **无条件** `RpcPlane(self)` + `start()`；全仓 `L3_RPC_PLANE` 仅在该 docstring 出现 1 次（实测 grep）
  → **该 docstring 陈旧，实际生效面就是 `lx/<stack>/rpc`**。

按 name 分发与准入（registry / runtime）：

- `PKG/dispatcher/tools/registry.py#L263-L271` — `tool_for_name()`：未注册名抛
  `ToolProtocolError(-32601)`，`data.reason="tool_not_registered"`（`#L266-L270`）。
- `#L289-L349` — `normalize_call()`：`allowed = {"call_id","name","task_id","arguments","context"}`
  （`#L292`；`task_id` 为 S5 退役对象）；未知字段 → `unknown_argument`（`#L293-L295`）；
  强制 `task_id == spec.task_id`（`#L300-L307`，S5 退役）；`context` 允许
  `{flight_session_id,step_id,display_text,station_id,station_instance_id,lease_id}`（`#L313-L325`）；
  空串校验 → `missing_required_argument`（`#L360-L363`）。
- `#L352-L357` — `_invalid()` 统一为 `INVALID_PARAMS(-32602)` + `data.reason`/`details`。
- `#L374-L455` — `_validate_object()`：未知键 `unknown_argument`、缺键 `missing_required_argument`、
  越界/类型/非有限 `argument_out_of_range`。

运行时（runtime）与租约（connection_lease）：

- `PKG/dispatcher/tools/runtime.py#L83-L155` — `admit()`：`call_id` 同载荷重放返回原 ack（`#L89-L97`）、
  异载荷 → `call_id_conflict`（`#L92-L96`）；**owner-only** `self._leases.require_owner(...)`（`#L100`）；
  活动调用存在时——普通工具从**同一 station 实例**下发则可抢占（`_same_station_owner`，`#L23-L28`、
  `#L103-L126`），否则 `flight_busy`（`#L113-L122`）；`flight.emergency_stop` 走抢占分支（`#L127-L129`）；
  ack 键集含 `type/accepted/call_id/name/task_id/flight_session_id/step_id/station_id/
  station_instance_id/lease_id/reason/ts`（`#L131-L144`）；准入即写 `running`/`accepted` 事件（`#L148-L153`）。
- `#L157-L211` — `cancel()`：未知调用 → `call_not_found`（`#L188-L193`）；终态调用 →
  `cancelled:false, reason:"already_terminal"`（`#L194-L201`）；幂等（`#L202-L204`）；
  需 `require_owner`（`#L185`）。
- `#L213-L244` — `emit()`：status 仅 `running|done|fail`（`#L224-L225`）；已终态或未知 → 返回 `False`
  （`#L229-L230`）→ **恰好一个终态**；终态后清 `_active_call_id`（`#L240-L243`）。
- `#L262-L270` — `mark_cancelled()`：终态 `fail` + `error.code="cancelled"`。
- `#L272-L340` — `events()`：`after_seq`/`limit` 校验（`#L287-L298`，上限 1000）；历史过期 →
  `cursor_reset:true, reset_reason:"event_history_expired"`（`#L304-L312`）；游标超前 →
  `reset_reason:"client_cursor_ahead"`（`#L313-L321`）；只回该租约事件、`next_seq` 越过外来事件
  （`#L322-L333`）；需 `require_owner`（`#L299-L300`）。
- `#L353-L372` — `cancel_active_for_lease_loss()`：租约丢失时对活动调用发**一个**终态
  `fail`，`error.code="connection_lost"`。
- `#L374-L389` — `issue_safety_stop()`：合成 `flight.emergency_stop` 调用（`#L385` 硬编码 `task_id=25`，S5 退役对象）。
- `#L395-L435` — `_append_event_locked()`：`event_id = f"evt_{instance8}_{seq}"`（`#L409`）、
  `seq` 单调（`#L406`）；事件键集含 `task_id`（`#L413`，S5 退役）、`frame_id`（`#L416`）。
- `PKG/dispatcher/connection_lease.py#L24` — `DEFAULT_TTL_S = 15.0`。
- `#L148-L175` — `acquire()`：同 station/instance 幂等返回原租约（`#L158-L161`）；异 owner →
  `connection_busy`（`#L162-L166`）；`LOSS_IN_PROGRESS` 期间拒 acquire（`#L153-L157`，`#L34`）。
- `#L177-L188` / `#L190-L215` — `renew`/`release`：owner-only（`_require_owner_locked` `#L339-L351`）；
  活动调用期间 release → `connection_active`（`#L200-L205`）。
- `#L217-L232` — `status()`：免租约快照（`owned`/`state`/`ttl_ms`/`expires_at`）。
- `#L238-L243` — `require_owner()`：身份三元组校验，缺失/不匹配 → `connection_not_owner`（`#L62-L80`）。
- `#L249-L323` — `expire_if_due()` / `notify_owner_lost()` / `mark_lost()` / `_complete_loss()`：
  有序状态机 `OWNED -> LEASE_LOST -> CANCELLING -> SAFETY_REQUESTED -> UNOWNED`，安全停失败时
  fail-closed 停在 `CANCELLING`（`#L312-L317`）。

传输面（zenoh_rpc / rpc_plane）：

- `PKG/dispatcher/zenoh_rpc.py#L111-L122` — `queryable_suffixes()` = `sim/reset`、`grasp_result/*`、
  `health`、`agent_log/snapshot`（**已无 `tools/list|call|events|cancel`**）。
- `#L124-L131` — 存在性 token `lx/<stack>/presence/task/<instance>`；owner 监视 key
  `lx/stations/<station>/connection/<lease>/<stack>`。
- `#L174-L179` — `RpcPlane` 无条件启动（**实际任务面 = `lx/<stack>/rpc`**）。
- `#L487-L496` — `health` 免租约。
- `#L533-L580` — 反馈面：`on_tool_phase()` 由 `_publish_task_phase` 的 `frame_id` 经
  `call_id_for_frame` 回退解析（`#L544-L551`）；phase→status 统一映射（`#L560-L567`）。
- `PKG/dispatcher/rpc_plane.py#L40-L42` — `CONNECTION_METHODS`（4 个连接方法）。
- `#L44` — `TRANSPORT_FIELDS = {"call_id","context"}`。
- `#L53-L68` — legacy wire 名别名 `basic_flight.* → flight.*`、`navigation.vla_nav → navigation.vla_reach`、
  `navigation.scene_graph_nav → scene.navigate`（含 `basic_flight.return` 补 `target="origin"`）。
- `#L144-L174` — `_FAIL_REASONS`（`connection_lost→connection_not_owner`、`cancelled→wrong_state`）；
  `_admission_reason()` 映射到 wire 词表（`method_not_found`/`invalid_arguments`/`connection_not_owner`/
  `connection_busy`/`internal_error`）。
- `#L332-L396` — `_execution_call()`：执行方法必带 `call_id`（`#L335-L341`），否则
  `invalid_arguments`；从注册表**按名**解析（`#L356`，wire 名经 `_WIRE_ALIASES` 归一）；
  `runtime.admit({... "task_id": spec.task_id ...})`（`#L383-L391`，S5 退役对象）。
- `#L221-L250` — `on_event()`：把终态 `done|fail` 桥成 `lx/<stack>/rpc_outcome`（键
  `type/method/call_id/outcome`）。

测试（既有行为证据）：

- `l3-dispatcher-planner/tests/tool-registry/test_tool_registry.py#L93-L101`（发现面 14 名 + `revision` 稳定）；
  `#L146-L159`（恰好一终态）；`#L161-L180`（取消幂等 + `already_terminal`）；`#L302-L321`（急停抢占）；
  `#L323-L331`（保留号不可调用，S5 将随 `tool_for_task_id` 删除）。
- `tests/tool-registry/test_connection_lease.py#L205-L231`（owner-only 含急停）；
  `#L253-L276`（租约过滤 + 越过外来事件）；`#L279-L294`（分页游标）；`#L302-L334`（过期→取消→安全停）；
  `#L337-L396`（丢失顺序 + fail-closed 可续）；`#L508-L549`（无请求的静默过期看门狗）。
- `tests/tool-registry/test_rpc_plane_basic_flight.py#L180-L213`（拒绝词表映射）；
  `#L255-L283`（`_on_rpc` 端到端）。`tests/tool-registry/test_rpc_plane_navigation.py#L128-L154`、
  `#L209-L233`（别名归一 + 本地 object_id 解析）。

## 3. 目标与约束

- **目标**：把工具面不变量（发现面 / 按名分发 / 准入与拒绝词表 / 飞行独占与同源抢占 / 取消 /
  事件账本与 `call_id` 关联 / 恰好一个终态事件 / 连接租约身份与 owner 门 / 并发与重放 /
  完成语义）**搬进新库 `specs/`**，成为 S5/S6 之后判定与门禁的新库内权威。
- **Non-Goals**：
  - **不改代码**（代码对齐归 S1–S6 与既有各期；本方案零代码改动）；
  - 不迁技能族、不建 `tools/<family>/`、不动 `SkillHost` 端口（总纲 §4.6）；
  - 不改任何对外字段（`_meta` 去 `lx.task_id`、ack/event 去 `task_id`、未注册 done→fail
    均由 S5/S6 落地；本方案只在契约中把它们写成**目标态**并引用 S1 的登记）；
  - 不重建项目本地 spec（`l3-dispatcher-planner/**` 或其 `docs/` 下不得出现第二权威）。
- **硬边界**：
  - **禁止项目本地 spec**（`specs/README.md#L84-L86` 规则 2；`AGENTS.md` 硬约束 5）：
    内容只落 `specs/`；
  - **契约不写实现细节/行号**（`specs/README.md#L43-L45` 分类测试与「实现表是叶或非 spec 文档」）：
    新契约只写机制与判据，不写模块布局、行号、函数名清单；
  - **禁止转接器 / 过期必删**（模板 §3 硬边界）：不为新旧 wire 名（`basic_flight.*`）在契约里
    保留兼容条款；契约写目标形态，不写过渡垫片；
  - 文档一律简体中文；不写主机绝对路径与个人标识；
  - **契约变更需放行**：`specs/` 不在默认目标树内，执行前须取得用户显式确认。

## 4. 方案决策

### 4.1 形态裁决：**新增 1 个叶**（挂现有 `l3-dispatcher` 根）

**裁决：1 叶**，命名为 `l3-tool-plane`。**否决拆 2 叶**（「工具面不变量」+「传输与租约」）。

理由（依 `specs/README.md#L43-L45` 分类测试与 `#L34-L35` 叶定义）：

1. **叶 = 一个聚焦的机制**（README `#L34-L35`）。工具面与其租约/传输在新库是**同一个机制**：
   唯一的传输载体（`lx/<stack>/rpc`）承载的正是这个工具面，租约门就长在**准入内部**
   （`runtime.py#L100` 的 `require_owner` 位于 `admit()` 内），而非独立的传输细节。
   拆成两叶会把「准入」这一条不变量的判据切成两半。
2. **避免重复归属**（README 规则 5「陈旧事实、重复归属……在同一改动中移除」）：owner 门
   （`connection_not_owner`）、拒绝词表、`connection_active`、终态事件同时属于「准入/租约」
   两侧；拆 2 叶会让同一条不变量在叶子间互相引用，制造第二归属。
3. **实现耦合佐证**：`ToolRuntime` 与 `ConnectionLeaseManager` 由同一 middleware 装配
   （`zenoh_rpc.py#L68-L75`：`self.leases = ConnectionLeaseManager(...)`、
   `self.runtime = ToolRuntime(self.registry, command_queue, self.leases)`），二者是同一控制面的两面。
4. **不触根线预算**：根上限 10 文件、每根 ≤400 行（README `#L31-L33`），**叶无行数预算**；
   单一叶不会挤占根预算，规模也不构成拆叶理由。

**粒度对照**：旧库把它拆在 3 份 spec（tools / fleet / rpc），是因为其权威范围是**整个 agent-station
系统（l4 + l3）**并在做锁步过渡；新库根 `l3-dispatcher` 只拥有 l3 侧，且新库实现已把
工具运行时与租约合并为同一控制面。**故 1 叶是新库的最小充分权威。**

### 4.2 新契约文件名与 header 骨架（逐字）

- **文件名**：`l3-tool-plane.spec.md`（遵循 `specs/README.md#L63-L64` 的叶命名
  `<area>-<name>.spec.md`，`area=l3`、`name=tool-plane`）。
- **落地路径**：起草期 `specs/proposed/inner/l3-tool-plane.spec.md`
  （README `#L19-L20`：`proposed/inner/` 放未采纳的叶契约提案）；晋升后
  `specs/implemented/inner/l3-tool-plane.spec.md`。
- **header 骨架（逐字）**：

  ```text
  # l3 工具面契约

  Status: proposed
  Contract-ID: l3-dispatcher/tool-plane
  Parent: specs/implemented/l3-dispatcher.spec.md
  ```

  - `Status` 取 `proposed`：契约描述的是**目标形态**（含 S5/S6 后的字段与语义），当前代码仍是
    迁移中途态（`_meta.lx.task_id`、ack/event 的 `task_id`、未注册 done 仍在），故不得谎称
    `implemented`；晋升条件见 §7 P1。
  - `Contract-ID` 用叶格式 `<root-id>/<leaf-id>`（README `#L39-L41`）。
  - `Parent` 精确指向现有根路径（README `#L40-L41`）。
- **`## Inner contracts` 表是否同步改**：README `#L41` 规定「父根在 `## Inner contracts` 里列出
  每个**已实现**的叶路径」。**起草期（`proposed`）不改**根表（不列未实现叶）；**晋升为
  `implemented` 时，在同一改动内**向 `specs/implemented/l3-dispatcher.spec.md#L36-L42` 追加一行
  `| specs/implemented/inner/l3-tool-plane.spec.md | 工具发现/调用/事件/取消与连接租约的对外协议 |`。
  不预置占位行（不留桩）。

### 4.3 内容大纲（拟写条款，每条一句话 + 判据）

> 条款编号 `T*` 仅用于本方案索引；正式契约内部编号由起草时按 README 风格确定（建议 `T1…T10`）。
> 每条判据都可在当前代码上用静态检查或既有 pytest 复现。

| 条款 | 一句话 | 判据 |
|---|---|---|
| T1 工具发现面 | 注册面恰为已实现、已测试的工具集合；每项携带 `name/title/description/inputSchema/outputSchema/annotations/_meta`；`revision` 是工具元数据 canonical compact JSON 的 SHA-256，随元数据字节级变化；存在**唯一**且可复现；无公开 `enabled` 开关、列表不随瞬时就绪抖动 | `ToolRegistry.default().list_tools()`：工具名集合 == 契约清单、`revision` 等于契约记录快照、`_meta` 键集等于契约键集（现 14 项） |
| T2 按名分发 | `name` 是分发与查找的唯一键；未注册名一律 `tool_not_registered`；控制面**不引入任务编号**，编号不上 wire、不参与路由（引用 `l3-core-boundary` B2/B7/B8） | 契约清单只有 name 无编号；grep 契约正文零编号标识符；`tool_for_name` 未注册名返回 `tool_not_registered` |
| T3 传输面与拒绝信封 | 单 key（一站一入口）承载请求；请求含 `method` 与 `params`，`params.context` 携带连接身份三元组；成功 `rpc_result`、失败 `rpc_error{reason,message}`；拒绝 reason 词表固定（见下） | wire 请求/回复键集断言；reason 词表快照（代码 `reason` 字面量集合 ⊆ 契约词表） |
| T4 准入与参数校验 | 执行方法必带调用关联键；`arguments` 按该工具 schema 严格校验（未知键/缺键/类型/非有限/元数一律拒绝）；校验失败属 `invalid_arguments` | 未知键/缺键/越界用例；`_validate_object` 分支与契约逐条对应 |
| T5 飞行独占与同源抢占 | 每 stack 至多一个非终态调用；异源新普通调用 → `connection_busy`；同 station 实例新指令可抢占（先取消旧、再准入新）；`flight.emergency_stop` 是唯一抢占工具但**仍 owner-only** | `flight_busy`/抢占用例（`test_connection_lease.py#L205-L231`、`test_tool_registry.py#L302-L321`） |
| T6 取消 | 幂等；未知调用 `call_not_found`；终态调用 `already_terminal`；接受的取消结束为**一个** `fail` 终态（`error.code="cancelled"`）；**不隐含急停** | 取消用例（`test_tool_registry.py#L161-L180`）；契约明写「不隐含急停」 |
| T7 事件账本与 `call_id` 关联 | 有界历史、每运行时单调 `seq`、跨重启全局唯一 `event_id`；游标轮询（`after_seq`/`limit`）；只回该租约的事件且 `next_seq` 越过外来事件；游标过期/超前有确定复位原因；事件**仅按 `call_id` 关联** | 过滤/分页/复位用例（`test_connection_lease.py#L253-L294`）；事件键集断言 |
| T8 恰好一个终态事件 | status 恰为 `running\|done\|fail`；phase 词表固定；每个已准入调用**恰好一个**终态（`done` 或 `fail`），迟到/重复终态被忽略 | `emit` 二次终态返回假用例（`test_tool_registry.py#L146-L159`） |
| T9 连接租约身份与 owner 门 | 身份三元组（station_id + station_instance_id + lease_id）；一一独占；发现类查询免租约、调用/事件/取消需租约；缺失/过期/不匹配 → `connection_not_owner`；租约丢失走有序安全状态机、活动调用收到**一个** `connection_lost` 终态；活动期间 release → `connection_active` | owner-only/丢失顺序/看门狗用例（`test_connection_lease.py#L205-L231`、`#L302-L396`、`#L508-L549`） |
| T10 并发/重放与完成语义 | 同 `call_id` 同载荷重放返回原 ack、不二次执行；异载荷 → `call_id_conflict`；完成语义为 `forwarded\|action_result\|workflow_result`；传输超时/进程存活/pod 就绪**绝不算成功完成** | 重放用例（`test_tool_registry.py#L125-L143`）；契约明写完成语义三值 |

**拒绝 reason 词表（T3 的固定集合，两层）**：

- 传输层 `rpc_error.reason`（消费者可见的粗粒度）：`method_not_found`、`invalid_arguments`、
  `connection_not_owner`、`connection_busy`、`wrong_state`、`internal_error`；
  `transport_unavailable` 为旧库原型词表所列（`agent-station-rpc.spec.md#L65-L67`），
  新库代码**未产出**该 reason → 契约标注为**未核实/待定**，不擅自删也不擅自写为现行。
- 准入子原因（`data.reason`，随 message 细化）：`tool_not_registered`、`call_id_conflict`、
  `call_not_found`、`already_terminal`、`connection_active`、`invalid_cursor`、`unknown_argument`、
  `missing_required_argument`、`argument_out_of_range`、`invalid_request`、`object_not_resolved`。
  （`tool_identity_mismatch` 属 S5 退役对象，**不进契约**。）

### 4.4 搬运与消歧（逐条标注「搬 / 改写 / 弃」）

| 旧库条款 | 动作 | 说明 |
|---|---|---|
| tools `#L25`（按名分发、编号不上 wire） | **搬** | 与 `l3-core-boundary` B2/B7/B8 一致 |
| tools `#L26`（只列已实现已测试能力） | **搬** | → T1 |
| tools `#L27`、`#L63-L67`（保留编号不静默转 0 / 不进 tools_list） | **弃（编号类）** | 编号概念整体退役（S5/G23），不搬 |
| tools `#L28-L29`、`#L30-L31`、`#L32-L33` | **搬/改写** | `ToolRuntime` 职责与「prompt 仅显示」搬入 T5/T8；「窄 ROS 端口」归 `l3-ros-adapter-boundary`，此处只引用 |
| tools `#L35-L36`（无 JSON-RPC envelope、一次 key 一次操作） | **改写** | 新库 wire 是「单 key + `{method,params}`」（rpc 提案），故改写为 T3 的形态 |
| tools `#L40-L61`（14 工具表含 task id 列） | **改写** | 搬 name + 参数 schema + completion；**删 task id 列** |
| tools `#L73-L106`（schema 严格校验、registry 单一来源） | **搬** | → T4；不搬具体 schema 值（属实现/文档面），契约只写「按工具 schema 严格校验」 |
| tools `#L108-L135`（工具模型；`_meta`） | **改写** | 搬键集；**`lx.task_id` 由 S5 去除**，契约键集不含它 |
| tools `#L137-L139`（无 `enabled`、列表不抖） | **搬** | → T1 |
| tools `#L141-L147`（六 key） | **改写** | 新库**已收敛为单 key `lx/<stack>/rpc`**（`queryable_suffixes` 无 `tools/*`）；契约写单 key，不写六 key |
| tools `#L149-L158`（`complete=true`） | **搬** | 作为传输约束保留 |
| tools `#L169-L173`（退役 key 不得再声明） | **弃/改为负向** | 契约只写「本控制面是唯一活跃入口，不声明已退役 key」一句，不写历史叙述（README 规则 5） |
| tools `#L175-L191`（`tools/list` 与 `revision`） | **改写** | 发现面契约保留；wire 名从 `tools/list` 改为本控制面的发现方法，`revision` 语义照搬 → T1 |
| tools `#L193-L244`（调用、`call_id`、ack、幂等/冲突） | **搬** | → T4/T10；ack 语义「已准入、绝非完成」照搬 |
| tools `#L246-L295`（events、游标、终态唯一、phase 词表） | **搬** | → T7/T8 |
| tools `#L297-L319`（cancel 幂等、`cancelled` 终态、不隐含急停） | **搬** | → T6 |
| tools `#L321-L335`（错误码与 reason 词表） | **搬 + 改写** | 与 rpc 提案词表合并为两层（§4.3）；`ros_unavailable`/`load_refused`/`reset_failed` 属资源面，**登记为待定**（新库资源面 `sim/reset` 仍用 `reset_failed`，`zenoh_rpc.py#L436-L441`） |
| tools `#L337-L384`（运行架构/模块布局） | **弃** | 属实现结构，不进契约（README 分类测试） |
| tools `#L386-L416`（独占、抢占、完成语义三值） | **搬** | → T5/T10 |
| tools `#L437-L456`（验收） | **改写** | 转为本方案 §8 的 A6 门禁，不写进契约正文 |
| fleet `#L23-L31`（一一独占、owner-only 含急停、丢失即取消+安全停） | **搬** | → T9 |
| fleet `#L43-L55`（身份四元组、重复身份拒绝） | **改写** | 新库只用三元组（无 `stack_id` 字段入 payload，stack 即 key 前缀）→ T9 |
| fleet `#L91-L137`（连接查询面、TTL/renew、`connection_busy`） | **搬** | → T9 |
| fleet `#L139-L162`（owner 作用域工具面、`connection_not_owner`） | **搬** | → T9 |
| fleet `#L185-L203`（丢失安全状态机 `OWNED→…→UNOWNED`、`connection_active`） | **搬** | → T9 |
| rpc `#L41-L63`（单 key、`{method,params}`、`rpc_result`/`rpc_error`） | **搬** | → T3（这是新库实际生效的 wire 形态） |
| rpc `#L65-L67`（原型 reason 词表） | **搬 + 标未核实** | `transport_unavailable` 无实现证据（§4.3） |
| rpc `#L128-L137`（权威过渡） | **弃** | 旧库内部权威链叙述，不进新契约 |
| channels `#L36-L40`、`#L407-L411`（v7 authority 声明） | **弃（v6 历史）** | 只作「旧 v6 任务面已作废」的依据写进本方案 §2.2，**不进契约** |
| channels v6 §3 全部条文（`#L42-L53`、§3.1–§3.12） | **弃（v6 历史）** | 该文件明示 MUST NOT 用于实现；不得作为任何契约来源 |
| monitor spec | **不引用** | 实测与工具面零关联（§2.2） |

**编号类条款与 S5 的关系**：一切 task id 相关条款（tools `#L27`/`#L40-L61` 的 id 列/`#L63-L67`/
`#L321-L335` 的编号校验、fleet/channels 里的编号叙述）**一律不进新契约**；新契约写明「控制面
以 `name` 为唯一分发键、不引入任务编号」，与 S5 的退役方向、`l3-core-boundary` B2/B7/B8、
`l3-migration-protocol` G23 一致。

### 4.5 门禁落点（与总纲 A6 对应）

总纲 §4.4 已登记 **A6 = 工具面对外协议门禁**。本方案把 A6 拆成三项**可执行**判定
（门禁脚本 `specs/tools/*` 未迁移，先用等价命令/测试；总纲 §4.4 尾注口径）：

- **A6-1 发现面 `revision` 断言 + 工具集快照**：
  ```bash
  python3 -c "import sys; sys.path.insert(0,'ros_packages/dispatcher'); \
  from dispatcher.tools.registry import ToolRegistry; lt=ToolRegistry.default().list_tools(); \
  print(lt['revision']); print([t['name'] for t in lt['tools']])"
  ```
  判据：名称集合 == 契约清单（14 项）；`revision` == 契约记录快照。
  **本次实测（S5 前）**：`sha256:cc1dcd1bcfa6f33fa10222042918a234ddcf2eddd7a79b96925194a981c0d69b`；
  **S5 后**：`sha256:333e24d208bcdfa34efa75c45b2377761503dc401999433eb3ec891a82ea2276`
  （S5 方案 §4.2/§8 已实测登记）。契约同时记录两值并注明「以 S5 完成为分界」。
- **A6-2 ack / event 键集快照**：对 `tool_call_ack`（`runtime.py#L131-L144`）与 `tool_event`
  （`runtime.py#L407-L428`）逐键断言。**S5 前** ack/event 含 `task_id`（`#L136`/`#L413`）；
  **S5 后**键集删去 `task_id`，其余键与取值不变（S5 方案 §4.5 逐字给了改后片段）。
  ```bash
  grep -nE '\"task_id\"|\"call_id\"|\"lease_id\"' PKG/dispatcher/tools/runtime.py
  ```
- **A6-3 拒绝 reason 词表快照**：抽取代码里的 `reason` 字面量集合，判 ⊆ 契约词表；
  并断言负例（未注册名 → `tool_not_registered`、非同源占用 → `flight_busy`）。
  ```bash
  grep -rnoE '\"reason\": *\"[a-z_]+\"' PKG/dispatcher/tools/ PKG/dispatcher/connection_lease.py PKG/dispatcher/rpc_plane.py
  ```
  判据：集合 ⊆ §4.3 两层词表；多出的 reason 须先改契约（README 规则 3）。

A6 的**范围**明确排除：S6 的 `/agent_task_phase` `done→fail`（那属 `l3-core-boundary` B5/G3 的
core 面，见 S6 §4/§8），以及资源面（`grasp_result/*`、`sim/reset`、`agent_log/snapshot`）与非工具的
`health` 语义——后者各自归其机制，不在工具面契约内。

### 4.6 与现有契约的边界（避免重复归属）

| 邻接契约 | 它拥有 | 本叶拥有 | 划分判据 |
|---|---|---|---|
| `l3-skill-contract` | 技能的**身份/生命周期/钩子/端口**（技能 ↔ 宿主） | 一个**调用**是什么：发现、准入、事件、取消、完成语义、租约 | 技能契约答「如何实现一个技能」，工具面答「一次对外调用如何被发现/准入/收敛」；工具面**不重述** §7 端口清单 |
| `l3-core-boundary` | core 的 FSM、任务队列、**未注册分发的 fail（B5/O3）**、无编号（B2/B7/B8） | 控制面的**对外协议**（wire 键、请求/回复信封、`revision`、事件账本、租约身份） | 同一「未注册」概念分两层：wire 层注册表查不到名 → 工具面 `tool_not_registered`（准入拒绝，无调用产生）；进入 FSM 后队首命令无技能 → core `fail` 相位（B5/S6）。二者键面不同、互不复述 |
| `l3-ros-adapter-boundary` | ROS 收发隔离（R1/R2/R4/R6） | 传输**与 ROS 无关**的协议面（zenoh 只是载体之一） | 工具面契约**不得**出现 `rospy`/ROS 消息类型；四类 core 通道与 ROS 落点归适配边界 |
| `l3-migration-protocol` | 迁移流程与判据（含 G23 禁编号） | —（不重叠） | 工具面只声明目标形态；「如何迁」归规程 |
| `development-workflow/l3-coding-style` | 命名/Doxygen/单位/头文件 | — | 契约措辞与文件命名遵循 README header 规范，不重述编码风格 |

## 5. 迁移映射表（旧库条款 → 新库契约条款 → 动作）

| 旧库位置（只读来源） | 新库契约条款（拟） | 动作 |
|---|---|---|
| tools `#L25-L26`、`#L35-L36` | T1/T2/T3 | 搬 / 改写 |
| tools `#L28-L31`、`#L386-L416` | T5/T8/T10 | 搬 |
| tools `#L73-L106`、`#L193-L244` | T4 | 搬 |
| tools `#L108-L135` | T1（键集，去 `lx.task_id`） | 改写 |
| tools `#L141-L158` | T3（单 key + `complete=true`） | 改写 |
| tools `#L175-L191` | T1（`revision` 语义） | 改写 |
| tools `#L246-L295` | T7/T8 | 搬 |
| tools `#L297-L319` | T6 | 搬 |
| tools `#L321-L335` | T3（reason 词表分层） | 搬 + 改写 |
| tools `#L27`、`#L40-L61`（id 列）、`#L63-L67`、`#L337-L384` | — | **弃**（编号类 / 实现结构） |
| fleet `#L23-L31`、`#L43-L55`、`#L91-L162`、`#L185-L203` | T9 | 搬（身份四元组→三元组改写） |
| rpc `#L41-L67` | T3 | 搬（`transport_unavailable` 标未核实） |
| rpc `#L128-L137` | — | 弃（权威过渡叙述） |
| channels `#L36-L40`、`#L407-L411`、v6 §3 | — | 弃（v6 历史，明示作废） |

## 6. 删除清单

> **本方案不删代码**。§6 只声明「新库不搬旧库的作废/编号类条款」，并登记唯一需要显式处置的
> 陈旧措辞（**登记而非本方案执行**）。

| 项 | 处置 | 理由 |
|---|---|---|
| 旧库 v6 任务面条文（channels `#L42-L53`、§3.1–§3.12） | **不搬**（弃） | 该文件 v7 authority 明示 MUST NOT 使用（`#L407-L411`） |
| 一切 task id 条款（tools `#L27`/id 列/`#L63-L67`、fleet/channels 编号叙述） | **不搬**（弃） | S5 / `l3-core-boundary` B2/B7/B8 / G23 |
| 旧库 tools `#L337-L384` 运行架构与模块清单 | **不搬** | 实现结构不进契约（README 分类测试） |
| `rpc_plane.py#L11-L16` docstring 的「PREPARED, NOT ACTIVATED / env-gated」措辞 | **登记，不在本方案改**（代码归其自身轮次） | 与代码事实不符（`zenoh_rpc.py#L174-L179` 无条件启动；`L3_RPC_PLANE` 全仓 0 读取）——记入 §9 R3，由代码轮次修正，本方案只写契约 |
| `specs/implemented/l3-dispatcher.spec.md#L36-L42` 根表 | P1 晋升时**追加一行**（非删除） | README `#L41` 要求父根列出已实现叶 |

## 7. 实施步骤（P0 → P3 分期）

### P0 — 起草叶契约（需放行）

- 范围：新增 `specs/proposed/inner/l3-tool-plane.spec.md`，按 §4.2 header + §4.3 大纲落 §T1–T10。
- 行为不变式：代码/测试零改动；根表不动。
- 验收：header 合规（README `#L65-L76`）；`Status: proposed` 与所在目录一致；契约正文零行号、
  零模块布局；工具名清单与 `list_tools()` 实测一致。
- 回退：删除该文件。

### P1 — 挂 Parent 与晋升（需放行）

- 范围：把文件从 `specs/proposed/inner/` 移到 `specs/implemented/inner/`（README `#L89-L90`
  规则 4：整条记录在生命周期目录间移动），`Status: proposed → implemented`；**同一改动**内
  向 `specs/implemented/l3-dispatcher.spec.md#L36-L42` 追加叶行。
- 前置：S5 已落地（`_meta`/ack/event 去 `task_id`、`revision` 新值），否则契约与代码存在
  未登记漂移，不得晋升。
- 行为不变式：纯位置 + 一行表格；不新增目录（按需创建）。
- 回退：文件移回 `proposed/` + 还原 header + 撤销根表行。

### P2 — 与实现对照验收

- 范围：跑 §8 全部判定；把任何不一致登记为待办（方案或 issue），**不改契约迁就现状**。
- 行为不变式：只读检查，无副作用。
- 回退：不适用（无改动）。

### P3 — 门禁接入

- 范围：把 §4.5 的 A6-1/2/3 接入门禁（`specs/tools/*` 迁移后接脚本，迁移前用等价 grep/pytest；
  总纲 §4.4 尾注）。
- 行为不变式：门禁只读；未迁移前不凭空引用 `specs/tools/*` 为强制门禁（README `#L94-L96`）。
- 回退：撤销门禁接线。

## 8. 验收标准

- [ ] **契约头规范自检**：文件名 `l3-tool-plane.spec.md` 匹配 `<area>-<name>.spec.md`；
  第 3 行 `Status:` 与所在目录一致；含 `Contract-ID: l3-dispatcher/tool-plane` 与
  `Parent: specs/implemented/l3-dispatcher.spec.md`（README `#L61-L76`）。
- [ ] **`specs/README.md` 规则逐条对照**：规则 1（`specs/` 内唯一权威）、规则 2（无项目本地 spec）、
  规则 5（只含当前内容、无迁移叙述与重复归属）逐条判绿。
- [ ] **A6-1 可跑**：`list_tools()` 名称集合 == 契约 14 项；`revision` == 契约记录快照
  （S5 前 `sha256:cc1dcd1b…c0d69b` / S5 后 `sha256:333e24d2…ea2276`）。
- [ ] **A6-2 可跑**：`tool_call_ack` / `tool_event` 键集 == 契约快照（S5 后不含 `task_id`）。
- [ ] **A6-3 可跑**：代码 `reason` 字面量集合 ⊆ 契约两层词表；负例（未注册名 / 非同源占用）判定正确。
- [ ] **与 S5 的 `revision` 断言一致**：契约记录的两值与 S5 方案 §4.2/§8 一致（不得另立数值）。
- [ ] **零编号**：契约正文 `grep -nE '\btask_id\b|lx\.task_id' specs/**/l3-tool-plane.spec.md`
  零命中；契约不出现编号常量表。
- [ ] **零实现细节**：契约正文不出现 `.py` 路径、函数名清单、行号。
- [ ] **零代码回归**：`git diff --stat` 仅含 §10 列出的文件（仅本方案 + 新契约）。
- [ ] **G18（契约先行）**：新增叶存在于 `specs/`（起草期 `proposed`、晋升后 `implemented`），
  满足 `l3-migration-protocol` §8 G18「`proposed` 及以上」。

## 9. 风险与对策

| # | 风险 | 影响 | 对策 |
|---|---|---|---|
| R1 | 与旧库漂移（旧库后续再改工具面，新库契约不再同步） | 双权威/判决过时 | 新库契约是唯一权威（README 规则 1）；旧库改动须先在本叶落地；本方案 §5 给逐条来源便于回溯 |
| R2 | 契约过细变成实现描述 | 违反 README 分类测试、维护成本高 | §3 硬边界禁写 `.py`/行号/函数名；只写机制与判据；§8 设「零实现细节」判定 |
| R3 | 放行阻塞（`specs/` 不在默认目标树内） | S7 停在 P0 | §0 明写需放行；未放行时本方案保持 `proposed`、不改任何文件（除本方案自身） |
| R4 | 单叶过宽（10 条款）被评审要求拆分 | 返工 | §4.1 已给「1 叶」的四条理由与「为何不拆」；若评审仍要求拆，拆分点应落在 T9（租约）与 T1–T8（工具语义），且须先改总纲 §4.4/§4.8 登记形态 |
| R5 | 与 S5/S6 数值/键集脱节 | A6 断言失败 | §4.5 直接引用 S5 方案 §4.2/§4.5/§8 的实测值与键集；S5 执行时以 S1 登记为准（S5 §1.3），本叶只引用不复述 |
| R6 | `transport_unavailable` 等旧库词背无实现证据 | 契约写错 | §4.3 明确标「未核实/待定」，不写为现行；待代码或 l4 侧确认后补 |
| R7 | `Status: proposed` 晋升时机不明 | 长期停留未生效 | §7 P1 明确晋升前置（S5 落地）与同一改动内容（移动 + 改 header + 追加根表行） |

**回滚路径**：P0/P1 为契约文档，`git` 还原（删除新契约 / 移回 + 还原 header + 撤销根表行）；
P2/P3 为只读检查与门禁接线，撤销接线即可。工作区不留中间产物。

## 10. 修改点清单汇总

| 文件 | 动作 | 说明 |
|---|---|---|
| `specs/proposed/inner/l3-tool-plane.spec.md` | 新增（P0，需放行） | 本方案唯一契约产物；`Status: proposed` |
| `specs/implemented/inner/l3-tool-plane.spec.md` | P1 迁移后路径（需放行） | 由 `proposed/` 移入并改 `Status: implemented` |
| `specs/implemented/l3-dispatcher.spec.md` | 修改（P1，需放行） | `#L36-L42` `## Inner contracts` 表**追加一行**叶路径 |
| `doc/l3-dispatcher-planner/iteration/design-dispatcher-tool-plane-contract.md` | 新增 | 本方案（S7） |

**本方案不动的文件（明确排除）**：

- 全部代码与测试：`l3-dispatcher-planner/**`（含 `ros_packages/dispatcher/**`、`tests/**`）——零改动；
- 其余契约：`l3-dispatcher.spec.md` 的不变量节与既有 5 叶、`topology`、`development-workflow` 及其叶；
- 总纲与 S0–S6 子方案（本方案只引用；与总纲冲突处**以总纲为准**，见下）；
- 旧库 `diff-dockers/specs/**`（**只读**，不修改）。

**需先改总纲的登记（不在本方案自行改总纲）**：

- 总纲 §4.4 已登记 A6，但**未给 A6 的判定细节**；本方案 §4.5 只做「落点展开」，若总纲要求
  A6 与其它门禁并列编号展示，则须**先改总纲 §4.4**再落本方案——本方案不擅改总纲。
- 总纲 §4.8 文档集与 §10 尾注的「后续轮次」未点名 S7 的文件名；若需把
  `design-dispatcher-tool-plane-contract.md` 纳入总纲索引，须**先改总纲**。

**登记的后续轮次（不在本方案内）**：`specs/tools/*` 门禁脚本迁移（A6 由等价命令转正式脚本）；
`rpc_plane.py` 陈旧 docstring 修正（归代码轮次，本方案只登记 R3）。

**未核实项（诚实标注）**：

- `transport_unavailable` 与 `ros_unavailable`/`load_refused`/`reset_failed` 在新库控制面的
  适用性——**未核实**（`transport_unavailable` 无实现证据；后三者属资源面，是否纳入本叶待定）。
- 旧库 `agent-station-fleet.spec.md#L23-L31` 的「日志/遥测投递」是否已在新库落地对应实现——
  **未核实**（本方案只搬「一一独占 + owner-only」的身份与准入不变量，不搬日志/遥测面）。

## 11. 附录：执行记录

### 2026-09-12 执行（S7 置 done）

- **执行者**：SOLO Agent 直接执行 P0–P3（纯契约，doc/specs 面）；deep-oracle 独立评审。
- **放行口径**：G-放行-2 沿用 S1 期用户「放行全部（specs/）」的显式放行。
- **P0+P1 实测**：`specs/proposed/inner/l3-tool-plane.spec.md` 起草（header：`Status: proposed`、`Contract-ID: l3-dispatcher/tool-plane`、Parent 指根）→ 前置满足（S5 done：编号全域零命中、revision 现行值 `sha256:333e24…`）→ 晋升：Write 新路径 + Delete 旧路径（语义等价整条移动）+ `Status: implemented` + 根契约 Inner contracts 表追加一行（同一改动内）；`proposed/` 空目录已不存在（合规「不预建空目录」）。
- **P2/P3 实测**：契约正文零 `\btask_id\b`/`lx.task_id`/`.py`/行号（Grep 零命中）；A6-1——14 工具名与完成语义三值 per-tool 与 `list_tools()` 逐项断言一致、revision == `sha256:333e24d208bcdfa34efa75c45b2377761503dc401999433eb3ec891a82ea2276`；A6-2——runtime 事件键 `call_id/status/phase/event_id/seq` 在位且零任务编号键；A6-3——代码 reason 字面量全集 ⊆ 契约两层词表（复位原因/错误码归 §5/§6/§7 条款）；门禁 G24–G28 与既有 G1–G23 全局唯一（deep-oracle 全局扫描实证）；G18 满足（叶存在于 `implemented/`）。
- **deep-oracle 评审结论**：初判「暂缓置 done」+ 6 项处置清单（3 FAIL + 3 CONCERN），已按其处方全部处置：
  - **F1**（T8 phase 词表遗漏）：§8 补 8 值词表（`accepted|perceiving|planning|dispatching|executing|result_ready|done|fail`）+ 映射层对词外值按 `running` 归一——词表取源权威（v7）值，与新库映射实现一致，非迁就现状；
  - **F2**（§3 别名句超纲违反「不写过渡垫片」硬边界）：改写为无历史词的抽象负向指针「wire 名的归一只作用于名字解析，不产生第二注册面」；`_WIRE_ALIASES` 的退役排期登记代码轮次；
  - **C1**（§4 抢占语义三处与实现时序不符）：改写为「飞行独占槽唯一 + 旧调用异步收敛一个 fail + 急停是唯一豁免同源约束的抢占工具」；
  - **C2**（G25 键集口径）：采「必备键子集 + 负例 + status/phase ⊆ 词表」口径；本方案 §8 A6-2 的「== 快照」口径据此降级（勘误）；
  - **C3**（规则 5 去叙述化）：契约只留现行 revision 值（退役前值 `sha256:cc1dcd…` 移录本附录存档）；去掉来源限定词；
  - **F3**（**登记不改契约，最重要发现**）：发现/取消/事件轮询三个操作面在 wire 层无入口——单 key 方法分发只有 connection 四方法与执行方法（注册工具名），`list_tools()`/`cancel()`/`events()` 的调用方仅测试与进程内，wire 消费者无法发现（拿不到 revision）、无法取消、无法游标轮询事件（只收到粗粒度 `rpc_outcome`）。**登记为后续轮次：「发现/取消/事件轮询的 wire 方法补入 rpc 面」**（属未在任何 S 期登记的契约-实现漂移；`rpc_plane.py` 陈旧 docstring 修正随之提升优先级）。G24/G27/G28 的进程内判定不受影响。
- **R7 事件记录**：契约修复期间发生一次部分回滚（§4/§1/§3 三处修复被外部写者回退，§8/G25 幸存），以整文件原子写入恢复并 t+15s 复验存活。
- **登记的后续轮次**：F3 的 wire 方法补齐轮次；`specs/tools/*` 门禁脚本迁移（G24–G28 转正式脚本）；`_WIRE_ALIASES` 别名退役排期；`rpc_plane.py` docstring 修正；`transport_unavailable` 与资源面 reason 的适用性待定项。

> 注：本附录曾于 2026-09-12 回写后被外部进程（Trae IDE 陈旧缓冲）回滚丢失，2026-09-13 依据会话记录重建，内容与首次回写一致。

# dispatcher task_id 全链路退役（S5）方案

> 摘要：这是总纲 `design-dispatcher-architecture-stabilization.md` §4.7 路线图中 **S5**
> 的执行版方案，是已 done 的
> `design-dispatcher-taskid-retirement-deps-migration.md`（engine 单文件 12 触点退役）的
> **续篇**。本轮把任务编号从「发现面 / 准入面 / 运行时 ack 与事件 / engine 遥测」整条链路
> 退役，并关闭前序方案 §10「登记的后续轮次待办 ②」中「tools/model 迁入轮裁决
> `ToolCall.task_id` 字段与新任务解析的对齐」这一条。产物为**字段级对外变更**（发现面
> `_meta` 与 ack/event 字段去除），已在 S1 契约修订登记为有意变更（见 §1.3）。

## 0. 元信息

| 项 | 值 |
|----|----|
| 日期 | 2026-09-12 |
| 目标路径 | `l3-dispatcher-planner/ros_packages/dispatcher/`（代码）、`l3-dispatcher-planner/tests/`（测试）。下称 `PKG = l3-dispatcher-planner/ros_packages/dispatcher/` |
| 状态 | done（2026-09-12 执行完毕；deep-oracle 放行，附条件项已完成，见 §11 附录） |
| 期中 | S5（总纲 §4.7） |
| 前置 | S1（契约修订 + 有意变更登记）、S4（ROS 适配面收口） |
| 关联文档 | 总纲：`doc/l3-dispatcher-planner/iteration/design-dispatcher-architecture-stabilization.md`；模板：`_TEMPLATE.md`；前序（本方案不改写它）：`design-dispatcher-taskid-retirement-deps-migration.md`；S1：`design-dispatcher-spec-reconciliation.md`（**已存在，其 §4.5 的对外变更登记为权威**；本文 §1.3 为执行期引用副本） |
| 契约依据 | `specs/implemented/inner/l3-core-boundary.spec.md`（B2/B7/B8 + G5）、`specs/implemented/inner/l3-migration-protocol.spec.md`（§4「禁止引入中间表示」+ G23）、`specs/implemented/inner/l3-skill-contract.spec.md`（§2「技能身份只有名字」） |
| 路径约定 | 全文一律用**相对路径**；不写主机绝对路径与个人标识 |

## 1. 背景与动机

### 1.1 契约禁令（为什么任务编号被禁）

- **B2 无任务编号**（`l3-core-boundary.spec.md#L28-L30`）：l3 中不存在任务编号这一概念；
  不得定义、映射或按任务编号做分支，直接依据 rpc-json 解析出的任务名分配与处理；
  「引入编号作为中间表示属无谓开销与概念污染」。
- **B7 编号零残留**（`#L38-L39`）：l3 任何模块都不得定义、传递或存储任务编号；
  若上游调用协议仍携带该字段，**由适配层在入口处丢弃**，不得进入领域层。
- **B8 无中间映射**（`#L40-L41`）：任务识别到能力归属之间不得插入编号或枚举映射层。
- **G5**（`#L63`）：l3 的 core 与领域层零命中任务编号标识符；上游字段只允许出现在
  适配层的丢弃逻辑。
- **`l3-migration-protocol` §4「禁止引入中间表示」**（`l3-migration-protocol.spec.md#L61-L63`）：
  不得引入任务编号作为任务识别与能力归属之间的中间层；旧库中一切与编号相关的常量表、
  映射结构、解析与校验逻辑，一律不迁移。对应 **G23**（`#L105`）。
- **`l3-skill-contract` §2**（`l3-skill-contract.spec.md#L33-L34`）：技能身份只有名字一项，
  不声明也不依赖任何任务编号；按名分发是唯一分发依据。

### 1.2 漂移历史（engine 已退役 → tools 轮次又带回）

1. `design-dispatcher-taskid-retirement-deps-migration.md` 已在 **engine.py 单文件**上退役
   全部 12 处 task_id 触点（删除 `TASK_ID` import、`prepare_task_ids`、`current_task_id`、
   `_is_aggregated_task_id` 等），其 §8 V4 负向 grep 当时**零命中**。
2. 但同一方案的 §4.2 选项 c 明确记录：因 `tools/model.py::ToolCall.task_id`（旧行号 L31）
   与退役方向相冲，故**当轮不迁 tools/model.py**，把该冲突登记给 tools 轮次：
   > §10「登记的后续轮次待办 ② tools/model.py 迁入轮若需运行期 `SkillCommand`……并裁决
   > `ToolCall.task_id` 字段与新任务解析的对齐。」
3. 随后 zenoh 传输迁移轮与 tools registry 轮迁入了 `tools/{model,registry,runtime}.py` 与
   `rpc_plane.py`，**把编号概念随 `ToolCall`/`ToolSpec` 一起带回**：registry 重建了
   `_by_task_id` / `tool_for_task_id` / 强制 `task_id == spec.task_id` 校验 / `_meta["lx.task_id"]`，
   runtime 的 ack 与事件重新携带 `task_id`，engine 又回读 `call.task_id` 写入 `current_task_id`
   与遥测。总纲 §2.A 已登记此漂移（`PKG/dispatcher/engine.py` 的 `current_task_id`/`task_id=`/
   `task_ids=[…]`「与已执行的退役方向相反」）。
4. **S5 = 关闭该待办**：让整条链路与前序方案已确立的方向重新一致；engine 不再回读，
   领域层（`tools/`、`core/`）零编号标识符；**wire 不携带编号（§4.4 取证）**，故无入口丢弃动作。

### 1.3 有意对外变更登记（引用 S1 的登记项）

> `design-dispatcher-spec-reconciliation.md`（S1）§4.5 已登记三件对外变更，是**权威**；
> 本节只做执行期引用（数值/键集以本方案实测为准），**不另立权威**。

| # | 有意变更 | 兼容处置 |
|---|----------|----------|
| E1 | 工具发现面 `list_tools()`：每个工具的 `_meta` 去除 `lx.task_id` 键 → `revision`（sha256）变化 | **l4 不使用发现面**（`agent-station-rpc.spec.md`「Discovery is unnecessary: the method table is static and known to both sides」）→ 无消费方；变更性质 = 已登记的**字节级值更新**，非兼容问题；`revision` 新值由 §8 断言 |
| E2 | `tools/call` 准入 ack（`tool_call_ack`）与事件流（`tool_event`）去除 `task_id` 字段 | **l4 零消费**（ack 只读 `accepted`，outcome 只读 `call_id`/`outcome`）→ 无消费方；关联键本就是 `call_id`；ack/event 其余键集不变 |
| E3 | 分发未命中路径从 done 改为 fail（B5/G3） | **属 S6，不在本文范围**，仅登记归属 |

## 2. 现状事实（问题清单）

> 行号**本次实测**（用 Grep 全文枚举，`task_id|task-id|task_ids` 全模式）。
> 每条标注属「领域层残留」还是「适配层 wire 兼容」。`PKG = l3-dispatcher-planner/ros_packages/dispatcher/`。

### 2.0 核查记录

- `doc/l3-dispatcher-planner/iteration/design-dispatcher-spec-reconciliation.md` **已存在**（S1）→
  §1.3 改为引用其 §4.5 登记项（本文不再自行立权威）。
- `PKG/dispatcher/zenoh_rpc.py`：全文**零** `task_id` 命中（实测）——本轮无改动。
- `PKG/dispatcher/tools/executor.py`、`control_plane.py`、`skill_api.py`、`state.py`、
  `config.py`、`slog.py`、`connection_lease.py`、`perception/*`：全文**零** `task_id` 命中（实测）。
- `PKG/dispatcher_node.py#L7`：docstring 含散文「NO task-id dispatch」——**非标识符**（连字符
  写法），且语义仍正确（描述「无编号分发」），**不改**（见 §6 注）。
- `ros_packages/planner/**` 的 `source_task_id`（C++，`quadrotor_msgs/LocalGoalSet` 消息字段）：
  运动规划包、ROS 消息字段面，**不属 l3 dispatcher**，不在本轮范围。

### 2.1 `PKG/dispatcher/tools/model.py`（领域层残留，3 处）

| 行号（实测） | 现象 | 分类 |
|---|---|---|
| `#L31` | `ToolCall.task_id: int` 字段（`ToolCall` 定义于 `#L25-L51`） | 领域层残留 |
| `#L82` | `ToolSpec.task_id: int` 字段（`ToolSpec` 定义于 `#L77-L111`；字段序：`name, task_id, title, …`） | 领域层残留 |
| `#L108` | `public_dict()` 的 `_meta` 写入 `"lx.task_id": self.task_id` | 领域层残留（发现面泄漏） |

### 2.2 `PKG/dispatcher/tools/registry.py`（领域层残留，14 + 14 处）

索引与准入：

| 行号（实测） | 现象 | 分类 |
|---|---|---|
| `#L244` | `self._by_task_id = {spec.task_id: spec for spec in specs}` | 领域层残留 |
| `#L245` | 唯一性校验同时看 `_by_name` 与 `_by_task_id`（`if … len(self._by_task_id) != len(specs)`） | 领域层残留 |
| `#L273-L287` | `def tool_for_task_id(self, task_id: int) -> ToolSpec` 整方法（含 `#L278` 的 `_by_task_id.get`、`#L285` 的 `{"reason": …, "task_id": task_id}`） | 领域层残留 |
| `#L292` | `normalize_call` 的 `allowed = {"call_id", "name", "task_id", "arguments", "context"}` 仍把 `task_id` 列为合法字段 | 领域层残留（准入面接受编号） |
| `#L300-L307` | `task_id = payload.get("task_id")` → 非 int 即 `tool_identity_mismatch` → `task_id != spec.task_id` 再报 `tool_identity_mismatch` | 领域层残留（强制编号校验） |
| `#L341` | `ToolCall(… task_id=task_id, …)` 构造 | 领域层残留 |

`_specs()` 的 14 个 `ToolSpec(...)` 以**第 2 个位置参数**传 task id（`ToolSpec(` 出现的行 =
`#L36/L55/L65/L75/L85/L95/L111/L130/L140/L150/L162/L172/L182/L199`；对应 id 实参行）：

| 工具名 | 实参行（实测） | 值 |
|---|---|---|
| `navigation.vla_reach` | `#L38` | 0 |
| `scene.map_search` | `#L57` | 6 |
| `scene.navigate` | `#L67` | 7 |
| `flight.takeoff` | `#L77` | 20 |
| `flight.land` | `#L87` | 21 |
| `flight.translate` | `#L97` | 22 |
| `flight.rotate` | `#L113` | 23 |
| `flight.return` | `#L132` | 24 |
| `flight.emergency_stop` | `#L142` | 25 |
| `scene_nav.graph.list` | `#L152` | 30 |
| `scene_nav.graph.select` | `#L164` | 31 |
| `scene_nav.graph.save` | `#L174` | 32 |
| `scene_nav.graph.objects` | `#L184` | 33 |
| `scene_nav.graph.object_pose` | `#L201` | 34 |

（这 14 处位置参数随 `ToolSpec.task_id` 字段去除而删除；属领域层残留。）

### 2.3 `PKG/dispatcher/tools/runtime.py`（领域层残留，3 处）

| 行号（实测） | 现象 | 分类 |
|---|---|---|
| `#L136` | `admit()` 的 ack 字典含 `"task_id": call.task_id` | 领域层残留（对外 ack） |
| `#L383` | `issue_safety_stop()` 合成的 `ToolCall(… task_id=25, …)` 硬编码编号 | 领域层残留（合成编号） |
| `#L413` | `_append_event_locked()` 的事件字典含 `"task_id": call.task_id` | 领域层残留（对外事件） |

### 2.4 `PKG/dispatcher/rpc_plane.py`（3 处：2 处叙述 + 1 处本地合成字段；**无 wire 字段可丢**——取证见 §4.4）

| 行号（实测） | 现象 | 分类 |
|---|---|---|
| `#L20` | docstring：「…and the **task_id is resolved from the registry** rather than trusted from the wire」——自述编号由注册表解析（**本地派生**） | 领域层残留（叙述需改写为「无编号」；非「入口丢弃」问题） |
| `#L347` | `_execution_call` 注释「…and resolve the **task_id** from the registry (never trust it from the wire)」 | 领域层残留（同 `#L20`） |
| `#L387` | 构造 `runtime.admit({… "task_id": spec.task_id, …})`——把编号合成为准入字段（**本地注入**） | 领域层残留（删除） |
| `#L44` | `TRANSPORT_FIELDS = frozenset({"call_id", "context"})` | —（**不改**：wire 无 `task_id`，无丢弃需求，见 §4.4） |
| `#L53` `_WIRE_ALIASES` | 实测仅映射**名字**（`basic_flight.* → flight.*`、`navigation.vla_nav → navigation.vla_reach`、`navigation.scene_graph_nav → scene.navigate`），**不含** task_id | —（无需改） |

### 2.5 `PKG/dispatcher/engine.py`（领域层残留，5 处）

| 行号（实测） | 现象 | 分类 |
|---|---|---|
| `#L180` | 注释块（`#L178-L182`）叙述 `current_task_id` 初始值语义 | 领域层残留（注释） |
| `#L185` | `self.current_task_id = 0` | 领域层残留 |
| `#L437` | `_activate_tool_call` 内 `self.current_task_id = int(call.task_id)` | 领域层残留 |
| `#L443` | `_telemetry("info", "tool_call_received", …, task_id=call.task_id, …)` | 领域层残留（slog 键集） |
| `#L509` | `_start_prompt_task(task_ids=[call.task_id], …)` 传入编号列表 | 领域层残留 |

补充实测：`current_task_id` 的**唯一**写入点为 `#L185`/`#L437`，**无任何读点**（grep 全文
`current_task_id` 仅命中 `#L180` 注释、`#L185`、`#L437`）→ 删除后零引用。

### 2.6 测试（随领域改动同步）

`tests/tool-registry/test_tool_registry.py`：

| 行号（实测） | 现象 |
|---|---|
| `#L26-L41` | `EXPECTED_TOOLS` 为 `{name: task_id}` 映射（14 项） |
| `#L75`/`#L79` | `call_payload(call_id, name, task_id, arguments, identity)` 形参 + payload 内 `"task_id"` |
| `#L97` | `{tool["name"]: tool["_meta"]["lx.task_id"] …}` 读发现面编号 |
| `#L101` | `len(first["revision"]) == 71`（长度断言，值会变） |
| `#L109`/`#L120` | `normalize_call` payload `"task_id": 22` / `assert call.task_id == 22` |
| `#L128`/`#L149`/`#L164`/`#L307`/`#L311` | `call_payload(…, 20/20/23/22/25, …)` 传编号实参 |
| `#L210`/`#L241` | `normalize_call` payload `"task_id": 22 / 0` |
| `#L278`/`#L287` | `for call_id, name, task_id, arguments in (…)` + payload `"task_id": task_id` |
| `#L323-L331` | `test_reserved_task_ids_are_not_callable` 调 `registry.tool_for_task_id(task_id)`（`#L328`） |

`tests/tool-registry/test_connection_lease.py`：

| 行号（实测） | 现象 |
|---|---|
| `#L84`/`#L88` | `payload(call_id, name, task_id, identity, arguments)` 形参 + payload 内 `"task_id"` |
| `#L189`/`#L218`/`#L222`/`#L227`/`#L256`/`#L263`/`#L282`/`#L307`/`#L315`/`#L403`/`#L525` | 11 个 `payload(…)` 调用点传编号实参 |

`tests/tool-registry/test_rpc_plane_basic_flight.py`：

| 行号（实测） | 现象 |
|---|---|
| `#L7` | 模块 docstring「name/task_id/argument 适配」 |
| `#L109`/`#L110`/`#L113`/`#L120`/`#L125`/`#L127` | `CASES` 元组第 3 项 task_id（20/21/22/23/25/24） |
| `#L131`/`#L132` | parametrize 形参 `task_id` |
| `#L147` | `assert command.call.task_id == task_id` |
| `#L277`/`#L281` | 注释「registry 解析的 task_id」/ `assert command.call.task_id == 22` |

`tests/tool-registry/test_rpc_plane_navigation.py`：

| 行号（实测） | 现象 |
|---|---|
| `#L146`/`#L228`/`#L317`/`#L345` | `assert command.call.task_id == 0 / 7 / 0 / 7` |

`tests/zenoh-bench/verify_routing.py`（wire 兼容面）：

| 行号（实测） | 现象 |
|---|---|
| `#L137`/`#L144`/`#L157` | `admit(name, task_id, arguments, …)` 形参 + `tools/call` payload 内 `"task_id"` + `ack.get("task_id") == task_id` |
| `#L318` | `{tool["name"]: tool["_meta"]["lx.task_id"] …}` |
| `#L341`/`#L387`/`#L403`/`#L431`/`#L549` | `tools/call` payload 字面量含 `"task_id": 20/27/21/20/20` |

`tests/zenoh-bench/mock_mission_action.py`：

| 行号（实测） | 现象 | 分类 |
|---|---|---|
| `#L18` | `goal_to_dict` 读 `int(getattr(goal, "task_id", 0))`——读取**下游 ROS action 消息字段** | 下游 wire 字段面，非 l3 领域编号（见 §4.4 裁决） |

## 3. 目标与约束

- **目标**：让 l3（core + 领域层）零任务编号标识符；发现面、准入面、ack、事件、engine
  遥测不再携带编号；**wire 不携带该字段（§4.4 取证）**，故无入口丢弃动作。
- **Non-Goals**：
  - 不改 FSM 语义、不改分发失败语义（done→fail 属 S6）；
  - 不改对外协议中**非编号**的字段：slog 事件名、topic/queryable/presence token、
    ROS topic/param/消息字段名；
  - 不迁技能族、不改 `ros_adapter/`；
  - 不改 `ros_packages/planner/**`（含 `source_task_id`）与下游 `quadrotor_msgs` 消息字段。
- **硬边界**（承接总纲 §3 与 `l3-migration-protocol` §4）：
  - **禁止转接器**：不为兼容旧字段新设转换层；
  - **过期必删**：被替代的旧字段/旧方法**直接删除**，不留别名、不留注释桩；
  - **无调用方不迁**：仅被测试引用的符号（`tool_for_task_id`）随测试一起删除；
  - **不投机设计**：`_start_prompt_task`（未迁移）不得因本轮改造而要求编号参数。

## 4. 方案决策

### 4.1 数据模型层（裁决：去除字段 + 调整位置参数）

- `tools/model.py`：删除 `ToolCall.task_id`（`#L31`）与 `ToolSpec.task_id`（`#L82`）。
- `tools/registry.py`：`_specs()` 内 14 个 `ToolSpec(...)` 的**第 2 个位置参数**（`#L38/L57/L67/L77/L87/L97/L113/L132/L142/L152/L164/L174/L184/L201`）整行删除；
  字段序变为 `name, title, description, input_schema, output_schema, completion, adapter, requires_perception=…`。
- **`SkillCommand` / `ToolCommand` 不受影响**：二者（`model.py#L54-L74`）只持有
  `call: ToolCall` 引用与 `requires_perception`/`kind`/`reason`，**自身无 task_id 字段**
  （实测）。删除 `ToolCall.task_id` 不改变它们的字段集与签名，故零改动。

### 4.2 发现面（裁决：`_meta` **直接去除** `lx.task_id`，不留兼容键）

- **裁决**：`public_dict()` 的 `_meta` 删除 `"lx.task_id": self.task_id`（`model.py#L108`），
  仅保留 `lx.completion` / `lx.concurrency`。
- **否决「保留但去语义」**（如恒 0 占位）：`lx.task_id` 是**领域层标识符**，保留即违反
  G5（`l3-core-boundary.spec.md#L63`「core 与领域层零命中任务编号标识符」）与 G23；且
  「保留但无意义」的字段是典型的转接垫片，违反「过期必删」。
- **兼容处置**：按 §1.3 E1 登记为有意变更；发现面本就以 `name` 为键，站端/l4 改读 `name`；
  `revision` 随之变化，**新值在 §8 断言**（实测见 §8）。**不留兼容别名键**。
- **`revision`（sha256）变化**：本次实测（以现有 registry 的 `public_dict` 去掉 `lx.task_id`
  后重算 canonical JSON 的 sha256）：
  - 退役前：`sha256:cc1dcd1bcfa6f33fa10222042918a234ddcf2eddd7a79b96925194a981c0d69b`（长度 71）
  - 退役后：`sha256:333e24d208bcdfa34efa75c45b2377761503dc401999433eb3ec891a82ea2276`（长度 71）

### 4.3 准入面（裁决：不再要求编号，删除映射索引与校验）

- `normalize_call`（`registry.py#L289`）：
  - `allowed` 集合（`#L292`）删除 `"task_id"` → 字段集为 `{"call_id", "name", "arguments", "context"}`；
  - 删除 `#L300-L307` 整块（`payload.get("task_id")` 的类型校验与 `task_id != spec.task_id`
    的 `tool_identity_mismatch` 校验）；
  - `ToolCall(...)` 构造（`#L338-L349`）删除 `task_id=task_id,`（`#L341`）。
  - 效果：携带 `task_id` 的 payload 进入领域准入即被 `unknown_argument` 拒绝——
    这正是 G5 的负向门禁语义（适配层必须在其之前丢弃，见 §4.4）。
- 删除 `_by_task_id`（`#L244`）与 `tool_for_task_id`（`#L273-L287`）；唯一性校验（`#L245`）
  收敛为只校验 `_by_name`：
  ```python
  self._by_name = {spec.name: spec for spec in specs}
  if len(self._by_name) != len(specs):
      raise ValueError("tool names must be unique")
  ```
- **无调用方检测（实测 grep 证据）**：全文 `tool_for_task_id` 仅 2 处命中——
  `PKG/dispatcher/tools/registry.py#L273`（定义）与
  `tests/tool-registry/test_tool_registry.py#L328`（测试调用）。**无生产调用方** →
  方法与其专属测试一并删除（`_by_task_id` 仅在该方法体与 `__init__` 内被引用）。

### 4.4 wire 兼容（裁决：**不存在 wire 兼容问题**——撤销「入口丢弃」设计）

- **取证结论（2026-09-12，旧库 l4-agent + 旧库契约）**：`task_id` **从不经 wire 传输**。证据：
  1. l4 出站 payload 仅 `method` + `params`（旧库 `station_projects/l4-agent/src/copaw/station_sidecar/rpc_plane.py` 的 `call()` / `execution()`）；`params` 只有 arguments + `call_id` + `context`（租约三元组）。
  2. l4 工具表 `station_projects/l4-agent/src/copaw/agents/tools/plan_tools.json` 的 9 条工具**无任何整数标识字段**（`vla_nav {object, bearing}`）。
  3. 契约明文：`specs/implemented/inner/agent-station-tools.spec.md#L25`「Dispatch is by stable `name` only; **task ids never appear on the wire**」；同文件 `#L63-L67`「Task ids in the table are **l4-internal plan/history labels only**; they are never serialized on the wire」。
  4. 样例载荷 `test/vla/nearest_white_pillar.rpc.json`：`rpc`（wire）段无 `task_id`，`task_id: 0` 只出现在 `expected_l3_normalization`（l3 本地派生结果）。
- **裁决**：B7 的「**若**上游调用协议仍携带该字段，由适配层在入口处丢弃」（`l3-core-boundary.spec.md#L38-L39`）是**条件条款**；取证表明条件不成立，故：
  - **不新增** `_DROPPED_WIRE_FIELDS`，**不改** `TRANSPORT_FIELDS`（`#L44`）；
  - 处置改为**删除本地派生**：删 `#L387` 的 `"task_id": spec.task_id,`；把 `#L20` docstring 与 `#L347` 注释的「task_id is resolved from the registry」改写为「按名从 registry 解析（无编号）」；
  - 若仓外旧客户端确在 `params` 多带 `task_id`：现行为是注册表的 `unknown_argument` **显式拒绝**，保持即可——**不静默丢弃、不增兼容层**（`l3-migration-protocol` §4 禁止为兼容旧调用方保留入口）。
  - **S1 不需要**为此新增任何契约条款（原设计所依赖的条件条款未被触发）。
- **字符串出现范围（修正后）**：`tools/`、`core/`、`utils/` **全域零命中** `\btask_id\b`（无白名单）——比原设计更强的门禁。
- **下游 ROS 消息字段（`tests/zenoh-bench/mock_mission_action.py#L18`）**——**2026-09-13 修订（用户裁决）**：
  原裁决（「`/mission/task` goal 的 `task_id` 属下游 ROS 消息 schema，读取保留，登记为下游契约项」）
  的前提已被推翻：**mission-execute 后续已不存在**，该 goal 字段成为无用内容，且 l3 按名分发
  （`basic_flight.*` 等 wire 名直接控制）不依赖任何编号映射。处置改为：**删除 mock 的该字段读取**
  （本修订同一改动内执行）。
- **`ros_packages/planner/**` 的 `source_task_id`（2026-09-13 二次裁决：范围外，不清除）**：
  它是 `quadrotor_msgs/LocalGoalSet` 的**来源枚举标签**（取值为具名常量
  `SOURCE_TASK_EXPLORATION`/`SOURCE_TASK_COUNTING`，仅用于 planner 全景模式判定），
  与 l3 的逐工具编号无派生关系、非其直接前序/后续产物。按用户清除口径（只清「直接叫
  `task_id` 的及其直接产物」），**不出本方案范围、不列待办处置项**，仅作范围外事实登记。

### 4.5 ack / 事件 / 合成 call（裁决：全部去 `task_id`；改后逐字片段）

`tools/runtime.py::admit` ack（`#L131-L144`）改后：

```python
            ack = {
                "type": "tool_call_ack",
                "accepted": True,
                "call_id": call.call_id,
                "name": call.name,
                "flight_session_id": call.flight_session_id,
                "step_id": call.step_id,
                "station_id": call.station_id,
                "station_instance_id": call.station_instance_id,
                "lease_id": call.lease_id,
                "reason": "admitted",
                "ts": _utc_now_iso(),
            }
```

`tools/runtime.py::_append_event_locked` 事件（`#L407-L428`）改后（键集其余不变）：

```python
        event = {
            "type": "tool_event",
            "event_id": f"evt_{self._event_instance}_{self._event_seq}",
            "seq": self._event_seq,
            "call_id": call.call_id,
            "name": call.name,
            "flight_session_id": call.flight_session_id,
            "step_id": call.step_id,
            "frame_id": call.frame_id,
            "station_id": call.station_id,
            "station_instance_id": call.station_instance_id,
            "lease_id": call.lease_id,
            "status": status,
            "phase": phase,
            "progress": progress,
            "isError": status == "fail",
            "structuredContent": dict(structured_content or {}),
            "message": message,
            "error": dict(error) if error is not None else None,
            "ts": _utc_now_iso(),
        }
```

`tools/runtime.py::issue_safety_stop` 合成 call（`#L380-L388`）改后：

```python
        call = ToolCall(
            call_id=f"safety_{uuid.uuid4().hex[:12]}",
            name="flight.emergency_stop",
            arguments={},
            flight_session_id=f"lease_loss_{uuid.uuid4().hex[:8]}",
            step_id="safety_stop",
            display_text=f"lease loss: {reason}",
        )
```

### 4.6 engine（裁决：`current_task_id` 字段、遥测键、`task_ids` 全部去除）

- `__init__`：删除 `#L185` `self.current_task_id = 0`；同步改写 `#L178-L182` 注释块，
  去掉对 `current_task_id` 的叙述（保留 `task_action_client` 相关说明）。
- `_activate_tool_call`（`#L432-L446`）改后逐字：

  ```python
      def _activate_tool_call(self, call: ToolCall) -> None:
          self._active_tool_call = call
          self._active_tool_name = call.name
          self.latest_agent_prompt_frame_id = call.frame_id
          self._active_task_frame_id = call.frame_id
          self._telemetry(
              "info",
              "tool_call_received",
              call_id=call.call_id,
              tool_name=call.name,
              frame_id=call.frame_id,
              task_generation=self.task_generation,
          )
  ```
  （删除 `#L437` 赋值与 `#L443` 的 `task_id=call.task_id,`——**slog 事件键集变化**属 §1.3
  已登记的有意变更 E2 的同类项，逐字键集见上。）
- `start_tool_workflow` 的 `_start_prompt_task(...)` 调用（`#L508-L513`）删除
  `task_ids=[call.task_id],`（`#L509`）整行；并在 §9 登记：**任务注入轮次迁入
  `_start_prompt_task` 时不得引入任务编号参数**（该方法的 `hasattr` 守卫 `#L461` 使该调用
  当前不可达，但源码仍须一致，避免未来迁入时把编号带回）。

### 4.7 测试（逐文件裁决）

- `test_tool_registry.py`：
  - `EXPECTED_TOOLS`（`#L26-L41`）改为工具名集合（去 id）；发现面断言（`#L97`）改为
    `{tool["name"] for tool in first["tools"]} == EXPECTED_TOOLS`；
  - `call_payload`（`#L75-L86`）去 `task_id` 形参与 payload 键，并同步 `#L128/#L149/#L164/#L307/#L311` 调用点；
  - `normalize_call` 直构 payload 去 `"task_id"`（`#L109/#L210/#L241/#L287`）与断言
    `call.task_id == 22`（`#L120`）；
  - `#L278-#L291` 循环去 `task_id` 形参与键；
  - **删除** `test_reserved_task_ids_are_not_callable`（`#L323-L331`，随 `tool_for_task_id` 消失）；
  - `#L101` `len(revision) == 71` 保留（长度不变，值由 §8 断言另测）。
- `test_connection_lease.py`：`payload`（`#L84-L91`）去 `task_id` 形参与键；同步 11 个调用点
  （`#L189/#L218/#L222/#L227/#L256/#L263/#L282/#L307/#L315/#L403/#L525`）。
- `test_rpc_plane_basic_flight.py`：`CASES`（`#L108-L128`）去 task_id 列（`#L109/#L110/#L113/#L120/#L125/#L127`）；
  parametrize（`#L131`）与断言（`#L147/#L281`）去 `task_id`；模块 docstring（`#L7`）改述；
  注释（`#L277`）改述。
- `test_rpc_plane_navigation.py`：删除 4 条 `command.call.task_id == …` 断言
  （`#L146/#L228/#L317/#L345`）。
- `verify_routing.py`：`admit()`（`#L137-#L158`）去 `task_id` 形参、payload 键与
  `ack.get("task_id")` 断言（`#L157`）；payload 字面量去 `"task_id"`（`#L341/#L387/#L403/#L431/#L549`）；
  发现面读法（`#L318`）改为按 `name`（并同步 `EXPECTED_TOOLS` 值去 id）。
  **实测复核项**：该 bench 仍在调用 `tools/list`、`tools/call`、`tools/events` 后缀（`#L119/#L312`
  等），而当前服务面仅剩 `lx/<stack>/rpc`（`zenoh_rpc.py#L117-L122`、`rpc_plane.py#L195-L199`）；
  其 payload 结构需按**执行时的实际服务面**复核后再同步（见 §9 风险 R5）。
- `mock_mission_action.py`：`#L18` **不改**（下游 ROS 消息字段面，见 §4.4）。

## 5. 迁移映射表（旧 → 新 → 动作）

| 旧（实测行号，相对 `PKG/dispatcher/`） | 新 | 动作 |
|---|---|---|
| `tools/model.py::ToolCall.task_id`（#L31） | — | delete |
| `tools/model.py::ToolSpec.task_id`（#L82） | — | delete |
| `tools/model.py::public_dict()._meta["lx.task_id"]`（#L108） | — | delete |
| `tools/registry.py::_by_task_id`（#L244） | — | delete |
| `tools/registry.py` 唯一性校验的 `_by_task_id` 分支（#L245） | 仅校验 `_by_name` | rewrite |
| `tools/registry.py::tool_for_task_id`（#L273-L287） | — | delete |
| `tools/registry.py::normalize_call` 的 `allowed["task_id"]`（#L292） | `{"call_id","name","arguments","context"}` | rewrite |
| `tools/registry.py` 的 `task_id` 类型/一致性校验块（#L300-L307） | — | delete |
| `tools/registry.py::ToolCall(… task_id=task_id …)`（#L341） | 去该 kwarg | rewrite |
| `tools/registry.py::_specs()` 14 个位置实参（#L38…#L201） | 去第 2 位置参数 | rewrite |
| `tools/runtime.py` ack `"task_id"`（#L136） | — | delete |
| `tools/runtime.py` 合成 `task_id=25`（#L383） | — | delete |
| `tools/runtime.py` 事件 `"task_id"`（#L413） | — | delete |
| `rpc_plane.py` docstring/注释的编号解析叙述（#L20/#L347） | 「按名解析」 | rewrite |
| `rpc_plane.py` 准入 payload `"task_id": spec.task_id`（#L387） | — | delete |
| （撤销）`rpc_plane.py::_execution_call` 参数折算（#L354） | **不新增** `_DROPPED_WIRE_FIELDS`：wire 无编号，无丢弃需求（§4.4） | drop |
| `engine.py::__init__` 的 `current_task_id`（#L185）+ 注释（#L180） | — | delete（注释 rewrite） |
| `engine.py::_activate_tool_call` 的 `current_task_id` 赋值（#L437） | — | delete |
| `engine.py` 遥测 `task_id=call.task_id`（#L443） | 去该 kwarg | rewrite |
| `engine.py::start_tool_workflow` 的 `task_ids=[call.task_id]`（#L509） | — | delete |
| 4 个 tool-registry 测试 + `verify_routing.py` 的编号构造/断言 | 去编号 | rewrite |
| `mock_mission_action.py#L18`（下游 ROS 消息字段） | 保留 | keep |

## 6. 删除清单

| 删除项 | 位置（实测行号） | 理由 |
|---|---|---|
| `ToolCall.task_id` 字段 | `tools/model.py#L31` | B2/B7/B8；G5/G23 |
| `ToolSpec.task_id` 字段 | `tools/model.py#L82` | 同上（编号只用于准入校验） |
| `_meta["lx.task_id"]` | `tools/model.py#L108` | 发现面泄漏编号；§4.2 直接去除 |
| `_by_task_id` 索引 | `tools/registry.py#L244` | 编号索引；无生产调用方 |
| `tool_for_task_id` 方法 | `tools/registry.py#L273-L287` | 唯一调用方为测试 `test_tool_registry.py#L328`（实测 grep） |
| `normalize_call` 的 `task_id` 准入与校验 | `tools/registry.py#L292/#L300-L307/#L341` | 准入面不得接受编号 |
| `_specs()` 的 14 个编号位置实参 | `tools/registry.py#L38…#L201` | 随字段删除 |
| ack `task_id` | `tools/runtime.py#L136` | 对外字段去编号（§1.3 E2） |
| 合成 `task_id=25` | `tools/runtime.py#L383` | 硬编码编号 |
| 事件 `task_id` | `tools/runtime.py#L413` | 对外字段去编号（§1.3 E2） |
| 准入 payload `task_id` | `rpc_plane.py#L387` | 领域残留 |
| `engine.current_task_id` 及全部触点 | `engine.py#L180/#L185/#L437` | 编号状态本体，删后零引用（§2.5 实测） |
| engine 遥测 `task_id` 键 | `engine.py#L443` | 键集变化属已登记变更 |
| `task_ids=[…]` 实参 | `engine.py#L509` | 编号列表传递 |
| `test_reserved_task_ids_are_not_callable` | `test_tool_registry.py#L323-L331` | 随 `tool_for_task_id` 删除 |

- **不留兼容别名**：不保留 `ToolCall.task_id` 的 property、不保留 `_meta["lx.task_id"]` 的
  占位键、不保留 `tool_for_task_id` 的 `DeprecationWarning` 桩（违反「过期必删」）。
- 注：`dispatcher_node.py#L7` 的散文「NO task-id dispatch」**不在删除清单**（非标识符，
  语义仍正确）。

## 7. 实施步骤（P0 → P4 分期）

> 每期：范围 + 行为不变式 + 验收 + 回退。整体按「数据模型 → 准入/发现面 → ack/事件 →
> engine → 测试与 wire 丢弃」推进；每期结束跑 §8 对应门禁。

### P0 — 数据模型层去字段

- 范围：`tools/model.py`（去 `ToolCall.task_id`/`ToolSpec.task_id`）、`tools/registry.py::_specs()`（去 14 位置实参）。
- 行为不变式：`SkillCommand`/`ToolCommand` 字段与签名不变；工具**名字集合**不变。
- 验收：`py_compile` 全绿；`ToolRegistry.default().tool_for_name(name)` 仍按 14 名可解析。
- 回退：还原 `model.py`/`registry.py::_specs()`（`git checkout --`）。

### P1 — 准入面与发现面

- 范围：`registry.py`（删 `_by_task_id`/`tool_for_task_id`；`normalize_call` 去编号；唯一性校验收敛）、
  `model.py::public_dict()`（去 `lx.task_id`）。
- 行为不变式：`normalize_call` 对**不含**编号的 payload 行为逐点不变；`name` 解析不变。
- 验收：`list_tools()["revision"]` == §8 新值；`tool_for_task_id`/`_by_task_id` 零命中。
- 回退：还原 `registry.py`/`model.py` 相关块。

### P2 — ack 与事件

- 范围：`tools/runtime.py`（ack `#L136`、事件 `#L413`、合成 call `#L383`）。
- 行为不变式：ack/事件**除 `task_id` 外键集与类型不变**；`call_id` 关联逻辑不变。
- 验收：§8 的 ack/event 键集比对（去 `task_id`）；运行时单测通过。
- 回退：还原 `runtime.py` 三处。

### P3 — engine 与遥测

- 范围：`engine.py`（`#L185`/`#L437`/`#L443`/`#L509` + `#L180` 注释）。
- 行为不变式：FSM/分发语义不变；删除的 `current_task_id` 无读点（§2.5）；`_start_prompt_task`
  调用当前不可达（`#L461` 守卫），删 kwarg 不改可达行为。
- 验收：engine 负向 grep 零命中；slog `tool_call_received` 键集 = §4.6 片段。
- 回退：还原 `engine.py` 四处 + 恢复注释。

### P4 — 测试与 wire 丢弃落点

- 范围：`tests/tool-registry/*`（4 文件）、`tests/zenoh-bench/verify_routing.py`、`rpc_plane.py`（落点 + 叙述）。
- 行为不变式：`rpc_plane` 对合法 wire 的准入/outcome 行为**零变化**（本方案不新增任何 wire 处理行）。
- 验收：`pytest l3-dispatcher-planner/tests/tool-registry` 全绿；§8 的 G5/G23 grep 达标；
  `verify_routing.py` payload 按实际服务面复核。
- 回退：还原测试与 `rpc_plane.py` 四处。

## 8. 验收标准

- [ ] **A5 语法**：`python3 -m py_compile` 对 `PKG/**/*.py` 全绿。
- [ ] **G5 负向门禁（领域层零编号标识符）**：
  ```bash
  grep -rnE '\btask_id\b' PKG/dispatcher/tools/ PKG/dispatcher/core/   # 期望：零命中
  grep -nE  '\btask_id\b' PKG/dispatcher/engine.py                     # 期望：零命中
  ```
- [ ] **G5 适配层全域零命中**（§4.4 裁决撤销「入口丢弃」后，无白名单）：
  ```bash
  grep -rnE '\btask_id\b' PKG/dispatcher/utils/                        # 期望：零命中
  ```
- [ ] **G23 全局零引入**：
  ```bash
  grep -rniE '\btask_id\b' PKG/dispatcher/                             # 期望：仅上述白名单 1 处
  grep -rnE 'tool_for_task_id|_by_task_id|current_task_id|lx\.task_id|task_ids' PKG/dispatcher/ l3-dispatcher-planner/tests/   # 期望：零命中
  ```
- [ ] **发现面新 revision 断言（实测值）**：
  ```bash
  python3 -c "import sys; sys.path.insert(0,'PKG'); from dispatcher.tools.registry import ToolRegistry; r=ToolRegistry.default().list_tools()['revision']; print(r); assert r=='sha256:333e24d208bcdfa34efa75c45b2377761503dc401999433eb3ec891a82ea2276'"
  ```
  （退役前值 `sha256:cc1dcd1bcfa6f33fa10222042918a234ddcf2eddd7a79b96925194a981c0d69b`；长度仍 71。）
- [ ] **ack/event 键集比对**：`tool_call_ack` 与 `tool_event` 逐键等于 §4.5 片段（无 `task_id`）。
- [ ] **pytest**：`pytest l3-dispatcher-planner/tests/tool-registry` 全绿；
  `test_rpc_plane_navigation` 的 scene_graph 用例维持「因技能族未迁而失败」的既有预期
  （总纲 §8）。
- [ ] **`tests/zenoh-bench/verify_routing.py` payload 同步**：`admit()` 与全部 payload 字面量、
  发现面读法（`#L318`）不再引用 `task_id`；构造结构按执行时的实际服务面复核（§4.7 复核项）。
- [ ] **无调用方复核**：`grep -rn 'tool_for_task_id\|_by_task_id' PKG/ l3-dispatcher-planner/tests/`
  零命中（删除前实测唯一生产调用方不存在）。
- [ ] **契约一致性**：G5/G23 判绿；B2/B7/B8 逐条对照；未达成项在方案或 issue 登记。

## 9. 风险与对策

| # | 风险 | 影响 | 对策 |
|---|---|---|---|
| R1 | （已排除）发现面 `lx.task_id` 存在消费方 | — | 取证：l4 **不使用发现面**（`agent-station-rpc.spec.md`「Discovery is unnecessary」）→ 无消费方；E1 登记与 `revision` 断言保留，作为文档面闭环 |
| R2 | （已排除）ack/event 的 `task_id` 存在消费方 | — | 取证：l4 ack 只读 `accepted`、outcome 只读 `call_id`/`outcome` → 无消费方；关联键本就是 `call_id`/`name` |
| R3 | 仓外旧客户端在 `params` 多带 `task_id` | 注册表以 `unknown_argument` **显式拒绝** | 已取证 wire 无该字段；**不静默丢弃、不增兼容层**（`l3-migration-protocol` §4） |
| R4 | `/mission/task` 下游消息 `task_id` 字段 | 未来任务注入轮次可能以编号填充 | 登记：下游 ROS 消息字段不改（Non-Goals）；任务注入轮次迁入 `_start_prompt_task` 时**不得**引入任务编号参数（§4.6） |
| R5 | `verify_routing.py` 服务面已漂移（`tools/*` vs `rpc`） | 机械改 payload 不足以使其可跑 | §4.7 标注「按执行时实际服务面复核」；bench 的真实可用性归属其自身轮次，不在本方案内臆改服务面 |
| R6 | `revision` 值随执行环境变化（如字段序不同） | 断言失败 | 本方案已用**实测重算**给出 `sha256:333e24…`；若执行时按 §4/§5 落地仍不符，先核对 `public_dict` 键集是否与 §4.2 一致，再更新断言 |
| R7 | 误删 `task_generation`/`task_phase`（含 `task` 子串但非编号） | 破坏遥测/相位 | 门禁用词边界 `\btask_id\b` 与显式符号清单（`task_for_task_id`/`current_task_id` 等），不误伤 `task_generation`/`task_phase` |

回退路径：P0–P4 每期独立；纯删除/改写块用 `git checkout -- <path>` 还原，或执行前对
`PKG/` 全量快照（放主机本地，不入库）。工作区不留中间产物。

## 10. 修改点清单汇总

| 文件 | 动作 | 说明 |
|---|---|---|
| `PKG/dispatcher/tools/model.py` | 修改 | 删 `ToolCall.task_id`(#L31)、`ToolSpec.task_id`(#L82)、`_meta["lx.task_id"]`(#L108) |
| `PKG/dispatcher/tools/registry.py` | 修改 | 删 `_by_task_id`(#L244)、`tool_for_task_id`(#L273-L287)、准入编号校验(#L292/#L300-L307/#L341)、`_specs()` 14 位置实参(#L38…#L201) |
| `PKG/dispatcher/tools/runtime.py` | 修改 | 删 ack(#L136)/事件(#L413)/合成 call(#L383) 的 `task_id` |
| `PKG/dispatcher/rpc_plane.py` | 修改 | 删准入 payload `task_id`(#L387)；改叙述(#L20/#L347)；加唯一丢弃落点(#L354) |
| `PKG/dispatcher/engine.py` | 修改 | 删 `current_task_id`(#L185/#L437)、遥测键(#L443)、`task_ids`(#L509)；改注释(#L180) |
| `tests/tool-registry/test_tool_registry.py` | 修改 | 去编号构造/断言；删 `test_reserved_task_ids_are_not_callable`(#L323-L331) |
| `tests/tool-registry/test_connection_lease.py` | 修改 | `payload()`(#L84) 去编号 + 11 调用点 |
| `tests/tool-registry/test_rpc_plane_basic_flight.py` | 修改 | `CASES`(#L108)/parametrize(#L131)/断言(#L147/#L281)/docstring(#L7)/注释(#L277) |
| `tests/tool-registry/test_rpc_plane_navigation.py` | 修改 | 删 4 条 task_id 断言(#L146/#L228/#L317/#L345) |
| `tests/zenoh-bench/verify_routing.py` | 修改 | `admit()`(#L137)、payload 字面量(#L341/#L387/#L403/#L431/#L549)、发现面读法(#L318) 去编号 |
| `tests/zenoh-bench/mock_mission_action.py` | 不改 | `#L18` 属下游 ROS 消息字段面（Non-Goals） |
| `doc/l3-dispatcher-planner/iteration/design-dispatcher-taskid-retirement-full.md` | 新增 | 本方案 |

**登记的后续轮次待办**：① 任务注入轮次迁入 `_start_prompt_task` 时不得引入编号参数；
② 与 l4/站端确认 E1/E2 消费面切换（改用 `name`/`call_id`）；③ `verify_routing.py` 服务面
（`tools/*` → `rpc`）是否需同步归属其自身 bench 轮次——**其中「identity mismatch rejected」用例（现
L395-L408）为期币死断言**（`tool_identity_mismatch` 在生产代码已无抛出点，bench 复活必假 FAIL），
bench 轮次须删除或改写为「wire 携带 `task_id` 的 payload 被 `unknown_argument` 显式拒绝」（后者恰为
§4.4 负向裁决的 bench 级验证）；另「reserved task id rejected」用例（L389-L393）标签名不副实（实为
未注册名拒绝），随 bench 轮次一并正名；④ `utils/rpc_plane.py` `_execution_call` 内 `spec =` 赋值已成
死变量（存在性校验语义保留），待任务注入轮次重构该函数时改裸调用或移除。

**未核实项**（诚实标注）：本文 §4.7 对 `verify_routing.py` 的「服务面已漂移」为**静态阅读
所得**，其实验运行时行为未在本轮核实；`mock_mission_action.py` 的 `/mission/task` goal 是否
实际含 `task_id` 字段未核实（当前用 `getattr(..., 0)` 兜底），标为**需执行时复核**。

## 11. 附录：执行记录

### 2026-09-12 执行（S5 置 done）

- **执行者**：code-fixer 子智能体执行 P0–P4（P0 与 P1 合并验收——P0 单独态下 `_by_task_id` 仍引用 `spec.task_id` 会 AttributeError，方案分期时序缺口已登记）；SOLO Agent 独立复验门禁；deep-oracle 独立评审。
- **快照**：`/tmp/diffagent2-s5-snapshot-20260912-195005`（pkg + tests）。
- **锚点重锚说明**：方案 §2 的 engine.py 5 触点已随 S3 全部迁入 `core/workflow.py`（L42/L49/L70/L76/L143），`rpc_plane.py` 在 `utils/`（S2）；engine.py 本轮**零改动**（已零命中）。
- **门禁实测（主 Agent 独立复跑 + t+20s 延时复验稳定）**：G5（tools/core/engine/utils 的 `\btask_id\b`）**全域零命中**（§4.4 撤销白名单后的更强门禁）；G23（六类退役符号 PKG+tests）零命中；**revision == `sha256:333e24d208bcdfa34efa75c45b2377761503dc401999433eb3ec891a82ea2276`**（与 §4.2 预计算值逐字一致，长度 71、14 工具、`_meta` 仅剩 `lx.completion`/`lx.concurrency`）；py_compile 全绿；pytest 6 failed + 35 passed（失败集与基线逐条相同=scene_graph 既有；通过数 −9 = 删除的 `test_reserved_task_ids_are_not_callable` 9 个参数化实例，数目吻合）。
- **deep-oracle 评审结论**：**放行置 done**（置信度约 0.92）。七项复核：数据模型/发现面（SkillCommand/ToolCommand 零影响实证；revision 具结构必然性——canonical 序列化两版逐字相同、唯一变化为删 `lx.task_id` 序列化形态）、准入面（diff 恰为四块设计内删除，无意外改写）、ack/事件三段与 §4.5 逐字一致、workflow 遥测键集 `call_id/tool_name/frame_id/task_generation` 且不可达段零扰动、测试改写语义保真、§10 对齐无越界、无兼容垫片残留。附条件两项已当场完成：§8 G5/G23 的「白名单 1 处」旧期望改为全域零命中；§10 rpc_plane 行「加唯一丢弃落点」改为「不新增（§4.4 裁决）」；登记项 ③ 已具体化（见上）。
- **R7 事件记录**：执行期间遭遇 **4 波**间歇性外部回滚（波及 registry/runtime/workflow/rpc_plane/4 测试文件/verify_routing 的分散触点），每波立即重写并以 t+10/15/20/60s 多轮延时 grep 复验收敛。
- **运行时断言的环境回退（R9）**：`test_connection_lease.py` 缺 `zenoh` 无法运行（payload 改法与全绿的 `test_tool_registry` 同构，静态审查）；`verify_routing.py` 本身因服务面漂移不可运行（§9 R5）；均以静态 diff + grep 门禁替代。
- **登记的后续轮次待办**：见上方 ①–④（含 verify_routing 死断言用例的具体处置、rpc_plane 死变量）。

> 注：本附录与 §10 登记项 ③④ 曾于 2026-09-12 回写后被外部进程（Trae IDE 陈旧缓冲，含当晚 20:43 的一次保存）回滚丢失，2026-09-13 依据会话记录重建，内容与首次回写一致。

### 2026-09-13 修订（§4.4 下游字段裁决推翻 + 扩量清除）

- **触发**：用户裁决——mission-execute 后续已不存在，`/mission/task` goal 的 `task_id` 为无用内容；l3 按名分发（`basic_flight.*` 等 wire 名直接控制），不存在任何编号映射。
- **流程**：先修订方案（§4.4/§10 两处裁决改写，见上文「2026-09-13 修订（用户裁决）」）→ 同一改动内执行代码清除：删除 `tests/zenoh-bench/mock_mission_action.py` `goal_to_dict` 的 `"task_id"` 键（原 L18）。
- **验收实测（2026-09-13）**：`l3-dispatcher-planner/` 全树 **Python 零命中** `\btask_id\b`；剩余命中仅 `ros_packages/planner/{ego_planner/plan_manage/src/ego_replan_fsm.cpp, super_planner/planner/include/ros_interface/ros1/fsm_ros1.hpp}` 的 `source_task_id`——**2026-09-13 二次裁决：范围外不清除**（来源枚举标签，与 l3 编号无派生关系，见 §4.4 二次裁决）；`py_compile` 通过；pytest 6 失败/35 通过（S5 基线不变）；R7 延时回读（t+25s，该文件当时开在 IDE 中）零回滚。
- **清除口径钉死（用户原话归纳）**：只清除「名字直接叫 `task_id` 的标识符/字段/键」及其**直接前序与后续产物**（映射索引、准入校验、ack/事件键、遥测键、注入点、测试构造）；语义不同名的相邻概念（如 `source_task_id` 来源枚举）与冻结历史文档中的叙述性提及不在其内。
# dispatcher 包拓扑归位（S2 执行版）方案

> 摘要：本方案是《l3 dispatcher 架构稳定总纲》
> （`design-dispatcher-architecture-stabilization.md`，下称**总纲**）**S2 期（包拓扑归位）的执行版**，
> 逐字落地总纲 **§4.1 目标目录树**与 **§4.2 平面定义与一层依赖矩阵**。它把
> `l3-dispatcher-planner/ros_packages/dispatcher/dispatcher/` 一包的现状收敛为**显式三层拓扑**
> ——`tools/`（agent 技能执行平面）、`utils/`（系统支撑平面）、`perception/`（独立感知层）
> ——并消解 `tools/ ↔ 支撑面` 的双向耦合、裁决 `skill_api.py` 归属、单点化共享协议词表。
>
> **目标形态的唯一权威是总纲 §4.1/§4.2**：本方案**不得自行改目标树，改树须先改总纲**。
> 本方案为**纯拓扑/职责归位，零行为改写**：FSM 语义、slog 事件名/键、zenoh topic/queryable
> 字节级不变；不新增 adapter、不留旧接口桩。依据：现状代码逐行复核（行号均已于 2026-09-12
> 用 Read/Grep 在本工作区重锚）。

## 0. 元信息

| 项 | 值 |
|----|----|
| 日期 | 2026-09-12 |
| 期 | **S2**（总纲 §4.7：包拓扑归位（tools/utils/perception），前置 S1，零行为，不需显式放行） |
| 目标路径 | `l3-dispatcher-planner/ros_packages/dispatcher/dispatcher/`（`PKG`）、`l3-dispatcher-planner/ros_packages/dispatcher/dispatcher_node.py`（`NODE`）、`l3-dispatcher-planner/tests/tool-registry/`（`TESTS`） |
| 状态 | done（2026-09-12 执行完毕，见 §11 附录） |
| 关联文档 | 总纲：`design-dispatcher-architecture-stabilization.md`（约束性权威，§4.1/§4.2/§4.3/§4.4/§4.7）；模板：`doc/l3-dispatcher-planner/iteration/_TEMPLATE.md`；姊妹篇：`design-dispatcher-engine-relocate-non-core.md`（S3 子方案，其目标树须服从本总纲，改写归 S3）、`design-dispatcher-zenoh-transport-migration.md`（done，历史记录）、`design-dispatcher-taskid-retirement-deps-migration.md`（done，历史记录） |
| 契约依据 | `specs/implemented/l3-dispatcher.spec.md` 及其叶契约（`inner/l3-core-boundary.spec.md`、`inner/l3-ros-adapter-boundary.spec.md`） |
| 对照基准 | `PKG` = `l3-dispatcher-planner/ros_packages/dispatcher/dispatcher`；`NODE` = `l3-dispatcher-planner/ros_packages/dispatcher/dispatcher_node.py`；`TESTS` = `l3-dispatcher-planner/tests/tool-registry/` |
| 路径约定 | 本文档一律用**相对路径**；不写主机绝对路径与个人标识（沿用总纲 §0） |

## 1. 背景与动机

总纲 §1 已裁定：dispatcher 代码层处于「迁移中途态」，且两份未执行的 `proposed` 方案在**目标拓扑上互相冲突**
（总纲 §2.B、§4.8）。总纲据此**先钉死唯一目标形态**（§4.1 目标树 + §4.2 依赖矩阵），再把各轮方案收敛为
「同一目标树下的执行版」。**S2 就是这场收敛的第一期：把包内模块按目标平面归位，零行为改写。**

用户对 `dispatcher/dispatcher` 包的三点定位（沿用既有方案，已被总纲 §4.1/§4.2 的平面定义吸收）：

1. **tools** = 注册进来的「特殊技能」（agent 技能执行平面），与 rpc-json 引入的 agent 技能一一对应；
2. **utils** = 维持 dispatcher 正常运行的系统级支撑工具（如 zenoh 网络通讯），**不作为 agent 执行工具**；
3. **perception** = 独立感知层（定位由本方案落地为总纲 §4.1 的 `perception/` 平面）。

现状问题（证据见 §2）：包根 8 个 `.py` + `perception/` + `tools/` 混居、**无 `utils/`**；`tools/` 与支撑面
**双向耦合**（`tools/control_plane.py` → `zenoh_rpc`，而 `zenoh_rpc`/`connection_lease`/`rpc_plane` → `tools`）；
共享协议词表散落在 `tools/model.py`（异常）与 `tools/registry.py`/`tools/runtime.py`（错误码）；
`skill_api.py`（core↔技能契约）归属未定；`perception/` 既被执行面经 host 消费、又被 engine 继承，层次不明。

本方案交付的是**总纲目标形态在 S2 期的执行版**：把工具面归 `tools/`、支撑面归 `utils/`、感知面保持独立层，
把上述耦合消解为**单向依赖**（支撑面 → 执行平面），并把共享协议词表单点化为 `tools/protocol.py`，
全程不引入任何 adapter 或转接桩。

## 2. 现状事实（问题清单）

> 相对路径；`PKG = l3-dispatcher-planner/ros_packages/dispatcher/dispatcher/`。
> 每条为「相对路径 + 行号 + 现象」，行号已在本工作区用 Read/Grep 重锚（对照旧文档的偏移已在 §2.6 登记）。

### 2.1 tools/ = 执行平面（agent 技能）证据

- `PKG/tools/registry.py#L31` — `def _specs() -> tuple[ToolSpec, ...]`；共 **14 个 `ToolSpec` 构造**
  （L36/55/65/75/85/95/111/130/140/150/162/172/182/199），即「注册进来的特殊技能」的规范清单。
- `PKG/tools/registry.py#L249-L261` — `default()`（L249）/`list_tools()`（L252）；`revision = "sha256:" + sha256(canonical)`
  （L254-L255），是工具发现面的字节级契约锚点。
- `PKG/tools/registry.py#L263-L271` — `tool_for_name()`：未注册即 `raise ToolProtocolError(METHOD_NOT_FOUND, ...)`（L266-L270）。
- `PKG/tools/model.py#L26-L52` — `ToolCall`（类 L26，`frame_id` 属性 L41）。
- `PKG/tools/model.py#L55-L65` — `SkillCommand`（类 L55，直接携带原生 `ToolCall` L64 + `requires_perception` L65）
  ——**工具↔技能的执行桥**。
- `PKG/tools/model.py#L78-L112` — `ToolSpec`（类 L78）与 `public_dict()`（L96-L112，`_meta["lx.task_id"]` L108），
  是 agent 技能发现面。
- `PKG/tools/executor.py#L15-L42` — `ToolExecutor`（类 L15）；`execute`（L22）：`flight.takeoff/land/emergency_stop`
  三条**直发** `host.forward_*_tool`（L26-L34）；其余经 `registry.tool_for_name`（L38）构造 `SkillCommand` →
  `host.start_tool_workflow`（L39-L42）。
- `PKG/engine.py#L197` — `self._skills: dict = {}`；`engine.py` 中多处以 `call.name`/`_active_tool_name` 为键查表
  （L488/L521/L562/L648/L730/L943）——**注册表键空间 = `ToolSpec.name` = 技能实例键**。
- `PKG/engine.py#L493` — `if command.requires_perception:` 感知门；需求来源是 `ToolSpec.requires_perception`。
- `PKG/tools/__init__.py#L3-L14` — 当前导出 `ToolCall/ToolCommand/ToolProtocolError/ToolRegistry/ToolRuntime/ToolSpec`
  （L3-L5 导入、L7-L14 `__all__`）（执行平面公开面雏形）。
- LS 实测：`PKG/tools/` 仅 `__init__.py/control_plane.py/executor.py/model.py/registry.py/runtime.py`；
  **`tools/vla`、`tools/scene_nav`、`tools/flight`、`tools/grasp` 技能族子包均不存在，尚未迁入**。

### 2.2 支撑面现状（应归 `utils/`）证据

- `PKG/zenoh_rpc.py#L25-L28` — 支撑面 → tools：`from dispatcher.tools import ToolProtocolError, ToolRegistry, ToolRuntime`
  + `tools.registry.{INVALID_PARAMS,METHOD_NOT_FOUND}` + `tools.runtime.{BUSINESS_REJECTED,LEASE_IDENTITY_FIELDS}`。
- `PKG/zenoh_rpc.py#L111-L116` — `queryable_suffixes()`（def L111）；注释写明 task plane 归 `RpcPlane`、
  "only resources remain here"（L115）。
- `PKG/zenoh_rpc.py#L125-L127` — `presence_token_key`（def L125，liveliness token，传输资源）。
- `PKG/zenoh_rpc.py#L175-L179` — `from dispatcher.rpc_plane import RpcPlane`（L175）、`self.rpc_plane = RpcPlane(self)`（L177）、
  presence token 声明（L179）——`RpcPlane` 随 `start()` 恒启动。
- `PKG/connection_lease.py#L6-L8` — 模块 docstring 自述 **"Transport-independent: time is an injected monotonic clock..."**
  （L6）——连接租约属支撑面。
- `PKG/connection_lease.py#L19-L20` — 支撑面 → tools：`tools.model.ToolProtocolError` + `tools.registry.INVALID_PARAMS`
  （**宽度问题**：仅为两个符号依赖 455 行 registry）。
- `PKG/rpc_plane.py#L1-L29` — 模块 docstring：`RpcPlane` 为 `lx/<stack-id>/rpc` 的**传输/锁步面**；
  `class RpcPlane` 定义在 L177；`_WIRE_ALIASES` 为 l4 兼容词表（L53）。
- `PKG/rpc_plane.py#L36-L38` — 支撑面 → tools：`tools.model` + `tools.registry` + `tools.runtime`。
- `PKG/config.py#L5-L6` — docstring：*"The former `utils/policy` vocabulary helpers are removed — nothing references them."*
  ——**旧仓库曾有 `utils/`，本方案需回答其归位**。
- `PKG/state.py#L1-L5` — 枚举词表（`COMMAND_TYPE/DISPATCHER_STATE/COMMAND_STATUS/MISSION_TYPE`），
  被 engine 与 perception 共用，属系统级常量。
- `PKG/slog.py#L38` — `class StructuredLogger`（双 sink 结构化日志）；`close()`（L151）幂等，属观测支撑。
- `PKG/tools/control_plane.py#L1` — docstring *"Compose the tool runtime, zenoh transport, and ROS execution host."*；
  `#L9` `from dispatcher.zenoh_rpc import ZenohTaskMiddleware`；`#L11` `from dispatcher.tools.executor import ToolExecutor`；
  `class ToolControlPlane`（L14）装配 runtime+executor+双守护线程（`tool-command-consumer` L29 / `zenoh-tool-server` L34）
  ——**装配/支撑职责，非 agent 工具**。

### 2.3 perception/ = 感知层证据

- `PKG/perception/__init__.py#L1` — docstring：*"Perception layer: base policy node and point cloud accumulation."*
- `PKG/engine.py#L75-L77` — `class DispatcherEngine(BasePolicyNode,)`；`engine.py#L83` `super().__init__()`
  ——**engine 直接继承感知基类**，感知是引擎的基座而非工具。
- `PKG/perception/base_policy.py#L244` — `class BasePolicyNode(object)`；`base_policy.py#L704` `get_fast_rgb()`；
  `base_policy.py#L2820` `publish_image(self, image, pub)`（`pub` 为参数）。
- `PKG/skill_api.py#L154-L155` — `SkillHost.latest_frame()` / `get_fast_rgb()`：感知**经 host 端口暴露给技能**
  （执行面消费感知）。
- `PKG/perception/pointcloud_accumulator.py#L18` / `#L97` — `PointCloudTimeWindow` / `PointCloudAccumulator`。
- `PKG/perception/base_policy.py#L35-L36` — 包内依赖仅 `dispatcher.state`（`MISSION_TYPE`）与
  `dispatcher.perception.pointcloud_accumulator`。

### 2.4 耦合、孤儿与断裂（本方案必须裁决）

- `PKG/tools/control_plane.py#L9` — **tools → 支撑面**（`dispatcher.zenoh_rpc`），是全包唯一一条「执行平面反依赖支撑面」的边。
- `PKG/zenoh_rpc.py#L25-L28` — **支撑面 → tools**（见 §2.2）。
- `PKG/connection_lease.py#L19-L20` — 支撑面 → tools（见 §2.2）。
- `PKG/rpc_plane.py#L36-L38` — 支撑面 → tools（见 §2.2）。
- `PKG/rpc_plane.py#L122-L126` — 懒引用 `dispatcher.tools.scene_nav.graph_source.load_objects_summary`（L123 import、L125 调用）
  ——**该子包当前不存在**，被 `try/except` 吞为 `return None`（L126-L127）；属「技能族未迁」的悬空引用。
- `PKG/engine.py#L494` — `self._decision_chain_not_ready_reason()` 被调用，但全包 grep **无该 `def`**
  （`engine.py#L461` 的 `hasattr(self, "_start_prompt_task")` 守卫使其当前不可达）——**既有孤儿引用**，非本方案引入。
- `PKG/skill_api.py#L38-L41` — `if TYPE_CHECKING:` 引用 `dispatcher.recording.RecordingService`（L39）、
  `dispatcher.tools.model.SkillCommand`（L40）、`dispatcher.tools.vla.vlm_facade.VlmFacade`（L41）
  （**前后两模块当前均不存在**）；文件另含 `SkillVerdict`（L44）/ `SkillBase`（L83）/ `SkillHost`（L138）。
- `PKG/engine.py#L26-L43` — 包根 engine 的包内 import：`state`（L26）/`config`（L27）/`skill_api`（L39）/
  `slog`（L40）/`tools.model`（L41）/`perception.base_policy`（L43）；`engine.py` 内 `create_dispatcher_engine`（L1020）/
  `start_dispatcher_workers`（L1063）。
- `NODE#L18-L21` / `NODE#L33-L38` — composition root：`from dispatcher.tools.control_plane import ToolControlPlane`（L18）
  → `ToolControlPlane(engine)`（L35）→ `start_dispatcher_workers(engine)`（L38）。

### 2.5 对外消费面（迁移影响面）

- `TESTS/test_connection_lease.py#L23-L31` — `from dispatcher import zenoh_rpc`（L23）/ `dispatcher.connection_lease`（L24）/
  `dispatcher.tools.model import ToolProtocolError`（L29）/ `registry`（L30）/ `runtime`（L31）。
- `TESTS/test_tool_registry.py#L18-L24` — `dispatcher.connection_lease`（L18）/ `dispatcher.tools.executor`（L19）/
  `dispatcher.tools.registry`（L20）/ `runtime`（L24）。
- `TESTS/test_rpc_plane_navigation.py#L25-L29` — `dispatcher.connection_lease`（L25）/ `dispatcher.rpc_plane`（L26）/
  `dispatcher.tools.model`（L27）/ `registry`（L28）/ `runtime`（L29）。
- `TESTS/test_rpc_plane_basic_flight.py#L23-L27` — 同族（`connection_lease` / `rpc_plane` / `tools.model` / `registry` / `runtime`）。
- `TESTS/test_rpc_plane_navigation.py#L118`、`#L253` — 以字符串 patch `dispatcher.tools.scene_nav.graph_source.load_objects_summary`
  （与 §2.4 悬空引用同源）。

### 2.6 行数复核与勘误

- `PKG/engine.py` 实测 **1067 行**；`PKG/state.py` **45**；`PKG/skill_api.py` **200**；`PKG/tools/registry.py` **455**；
  `PKG/tools/runtime.py` **439**；`PKG/zenoh_rpc.py` **612**；`PKG/connection_lease.py` **379**；`PKG/rpc_plane.py` **396**；
  `PKG/config.py` **241**；`PKG/slog.py` **157**；`PKG/perception/pointcloud_accumulator.py` **198**；
  `PKG/tools/executor.py` **46**；`PKG/tools/control_plane.py` **86**；`PKG/tools/model.py` **112**；
  `PKG/perception/base_policy.py` **3077**；`NODE` **48**。
- **勘误（相对旧文档）**：旧文档 §2.6 记 `executor.py` 为 47 行，实测 **46**；旧文档多处行区间有 ±1~2 偏移
  （如 `registry.default/list_tools` 旧记 L247-L260、实测 L249-L261；`tool_for_name` 旧记 L262-L270、实测 L263-L271；
  `zenoh_rpc.presence_token_key` 旧记 L124-L127、实测 L125；`rpc_plane` 悬空引用旧记 L122-L126、实测 L122-L126 区间内
  import 在 L123）。**执行一律以本方案 §2 重锚行号为准**。

## 3. 目标与约束

- **目标**：
  1. 按总纲 §4.1 **逐字落地 S2 目标树**：建 `tools/`（执行平面）/ `utils/`（支撑平面）/ `perception/`（感知层）三层，
     把包根 8 个模块与 `tools/control_plane.py` 逐一归位（§4、§5）。
  2. 消解 `tools/ ↔ 支撑面` 双向耦合为**单向** `支撑面 → 执行平面`，不新增 adapter、不留桩（§4.6）。
  3. 共享协议词表（`ToolProtocolError` + `METHOD_NOT_FOUND/INVALID_PARAMS/BUSINESS_REJECTED`）单点化（§4.7）。
  4. 裁决 `skill_api.py` 归属（§4.8）与 `perception/` 定位/边界（§4.4）。
  5. 输出可执行的迁移映射、删除清单、分期与验收（§5–§10），且验收含总纲 §4.4 的 **A1/A3**。
- **Non-Goals**：
  - **不改行为**：不得改动 FSM 转移逻辑、方法体、slog 事件名/键、zenoh topic/queryable 名、`registry` 规格字段。
    本方案是**纯位置迁移 + import 改写**。
  - **不在 S2 创建 `core/` 与 `ros_adapter/`**：总纲 §4.1 已裁定「避免空包=桩」，二者在 S3/S4 有实际内容时创建；
    本方案只在 §4.2 用注释标明其目标落点。
  - 不迁技能族实现（`vla/scene_nav/flight/grasp`）与 `recording`/`vlm_facade`——只**登记其归位规则**。
  - 不修复 §2.4 的既有孤儿引用（`_decision_chain_not_ready_reason`）与悬空引用（`scene_nav.graph_source`）——仅登记。
  - 不动 `base_policy.py` 的方法体、不动 `dispatcher_node.py` 的启动序列语义。
- **硬边界**：
  - **禁止转接器（anti-adapter）**：不新增 adapter/port/shim 桥接新旧接口；只做文件位置迁移与 import 路径改写。
  - **过期必删（no legacy shim）**：模块迁走后**旧路径不保留任何 re-export 别名或注释桩**；被搬迁的常量在旧模块中的
    定义**直接删除**。
  - **目标树唯一、不得自行改树**：改树须先改总纲（总纲 §4.1/§4.2 是唯一权威）。
  - 文档一律简体中文（代码标识符/路径/URL 保持原样）。

## 4. 方案决策

### 4.1 三点定位（总纲 §4.2 平面定义的执行表述）

> **tools/ = agent 技能执行平面（execution plane，叶子平面）**
> 承载「注册进来的特殊技能」：`registry`（注册表/发现面）→ `runtime`（准入/独占/取消/事件账本）→ `executor`（路由）
> → `skill_api`（技能契约）→ `model`/`protocol`（传输无关模型与协议词表）。**一个 `ToolSpec`（注册工具）对应一个
> agent 技能（`Skill` 实例），键同为 `name`**；rpc-json 引入的 agent 技能在此注册与执行。**不作为系统支撑**，
> **零包内出边**（不依赖 `utils/`、`perception/`、`engine`）。

> **utils/ = 系统支撑平面（support plane）**
> 维持 dispatcher 正常运行的系统级支撑：网络通讯（`zenoh_rpc`）、RPC 传输（`rpc_plane`）、连接租约（`connection_lease`）、
> 结构化日志（`slog`）、配置装载（`config`）、状态枚举（`state`）、传输/执行装配（`control_plane`）。
> **这些不是 agent 可执行工具**，不进入工具发现面。允许依赖 `tools/`（作为执行平面的消费者），
> **禁止**依赖 `engine`/`perception`/`core`/`ros_adapter`。

> **perception/ = 独立感知层（perception layer，非 utils 子集）**
> 定位于**数据语义层**：传感器订阅/同步、帧缓存与快通道 RGB、点云时间窗累积、像素→世界反投影与航点候选估计、
> 感知图像发布。它是**能力提供方**，经 `SkillHost` 端口（`latest_frame`/`get_fast_rgb`）被执行平面（技能）消费，
> 并被 core（`engine` 继承 `BasePolicyNode`）承载。**与 utils 的边界**：`perception` = 传感器数据的获取与几何换算；
> `utils` = 进程/通信/日志/配置/状态等运行时基础设施。唯一允许的包内依赖是 `perception → utils.state`（仅枚举）；
> `utils` 不得依赖 `perception`。

### 4.2 目标目录树（**逐字对齐总纲 §4.1**，仅展开 S2 增量）

> ★ = 该期新建。**S2 不创建 `core/` 与 `ros_adapter/`**（总纲 §4.1：避免空包=桩），二者在 S3/S4 有内容时创建；
> 下方用注释标明其目标落点。`tools/` 与 `utils/` 的模块清单、顺序与总纲 §4.1 完全一致。

```
l3-dispatcher-planner/ros_packages/dispatcher/
  dispatcher_node.py                    # composition root（不动位置；S2 仅改 control_plane 导入路径）
  dispatcher/
    __init__.py
    engine.py                           # core 门面：FSM 主循环 + 全局状态 + 任务编排 + 动作裁定（领域逻辑，零 ROS）
    # core/                        ★ S3  # 目标落点：core 私有协作模块（telemetry / task_phase / skill_router / actuators / ports）——S2 不创建
    # ros_adapter/                 ★ S3  # 目标落点：唯一允许 rospy / ROS 消息类型的位置（core_channels_ros / params_ros / clock_ros / feedback_ros / perception_ros）——S2 不创建
    utils/                       ★ S2  # 支撑平面
      __init__.py
      state.py  config.py  slog.py
      connection_lease.py  zenoh_rpc.py  rpc_plane.py
      control_plane.py                  # 自 tools/ 移入（装配职责归位，消解双向耦合）
    tools/                              # 执行平面（叶子平面）
      __init__.py
      protocol.py                 ★ S2  # 新增：共享协议词表（定义自 model / registry / runtime 移入）
      model.py  registry.py  runtime.py  executor.py  skill_api.py   # skill_api.py 自包根移入
      <family>/                         # vla / scene_nav / flight / grasp（后续轮次迁入；S2 只登记规则）
    perception/                         # 感知层（位置不变）
      __init__.py  base_policy.py  pointcloud_accumulator.py
```

**S2 增量（相对现状）**：新建 `utils/`（`state.py` `config.py` `slog.py` `connection_lease.py` `zenoh_rpc.py`
`rpc_plane.py` `control_plane.py`）；新建 `tools/protocol.py`；`skill_api.py` 自包根移入 `tools/`。
**S2 完成后包根只剩 `engine.py` + `__init__.py`。**

### 4.3 模块职责矩阵（「更详细的描述」）

| 模块（目标路径） | 平面 | 关键符号 | 职责（一句话） | 目标依赖 |
|---|---|---|---|---|
| `tools/protocol.py` ★ | 执行 | `ToolProtocolError`/`METHOD_NOT_FOUND`/`INVALID_PARAMS`/`BUSINESS_REJECTED` | 工具/RPC 协议词表单一来源 | stdlib |
| `tools/model.py` | 执行 | `ToolCall`/`SkillCommand`/`ToolCommand`/`ToolSpec` | 传输无关数据模型 | `tools.protocol` |
| `tools/registry.py` | 执行 | `ToolRegistry`/`_specs` | agent 工具发现面与参数校验的唯一规范源 | `tools.protocol`/`model` |
| `tools/runtime.py` | 执行 | `ToolRuntime` | 调用准入、飞行独占、取消、可重放事件账本 | `tools.protocol`/`model`/`registry` |
| `tools/executor.py` | 执行 | `ToolExecutor` | 注册工具 → 执行缝（直发 / 工作流）路由 | `tools.model`/`registry` |
| `tools/skill_api.py` | 执行 | `Skill`/`SkillBase`/`SkillHost`/`SkillVerdict` | 技能契约（技能↔宿主双向接口） | `tools.model`（TYPE_CHECKING） |
| `utils/state.py` | 支撑 | `DISPATCHER_STATE` 等 4 枚举 | 系统级状态/指令/任务枚举 | stdlib |
| `utils/config.py` | 支撑 | `load_yaml`/`apply_config`/`UAV_POLICY_DEFAULTS` | YAML 配置装载与 ROS 私有参数应用 | stdlib/rospy/yaml |
| `utils/slog.py` | 支撑 | `StructuredLogger` | 双 sink 结构化日志 | stdlib |
| `utils/connection_lease.py` | 支撑 | `ConnectionLeaseManager` | 站-栈独占连接租约与失效状态机 | `tools.protocol` |
| `utils/zenoh_rpc.py` | 支撑 | `ZenohTaskMiddleware` | zenoh 会话 + 资源 queryable + agent_log 上行 | `utils.connection_lease`、`utils.rpc_plane`、`tools.protocol`/`registry`/`runtime` |
| `utils/rpc_plane.py` | 支撑 | `RpcPlane` | `lx/<stack>/rpc` 锁步传输面 | `tools.protocol`/`registry`/`runtime` |
| `utils/control_plane.py` | 支撑 | `ToolControlPlane` | 装配 runtime+transport+双守护线程 | `utils.zenoh_rpc`、`tools.executor` |
| `engine.py` | core | `DispatcherEngine` | FSM 主状态机 + 全局状态 + 工具缝 | `tools.*`、`utils.*`、`perception.*` |
| `perception/base_policy.py` | 感知 | `BasePolicyNode` | 传感器订阅/同步、帧缓存、反投影、图像发布 | `utils.state`、`perception.pointcloud_accumulator` |
| `perception/pointcloud_accumulator.py` | 感知 | `PointCloudTimeWindow`/`PointCloudAccumulator` | 时间窗点云累积 | stdlib/三方 |

### 4.4 perception 裁决：独立层（非 utils 子集）

- **裁决**：`perception/` 保持**独立顶层子包**，不并入 `utils/`、不属于 `tools/`（与总纲 §4.1 一致）。
- **理由**：① 语义不同——感知是「传感器数据的获取与几何换算」，utils 是「进程/通信/日志/配置/状态」（§2.3/§2.2 证据）；
  ② 消费关系不同——感知经 `SkillHost` 被执行面消费（`PKG/skill_api.py#L154-L155`），utils 被执行面**依赖但不经 host 暴露**；
  ③ 承载关系不同——`engine` **继承** `BasePolicyNode`（`PKG/engine.py#L75-L77`），感知是 core 的基座，
  而 utils 是 core 的旁挂支撑。
- **与 utils 的边界**：唯一允许的依赖是 `perception → utils.state`（`MISSION_TYPE`，`PKG/perception/base_policy.py#L35`）；
  `utils` 任何模块**禁止** import `perception`。
- **与 tools 的关系**：感知需求由执行面声明（`ToolSpec.requires_perception` → `SkillCommand.requires_perception` →
  engine 感知门 `PKG/engine.py#L493`），感知数据由执行面经 host 读取——**执行面是消费者，感知面是提供方**，
  不存在感知→tools 的依赖。

### 4.5 一层依赖矩阵（**与总纲 §4.2 一致，不自行发明方向**）

> S2 只判下表已存在的平面（`engine.py`、`tools/`、`utils/`、`perception/`、`dispatcher_node.py`）；
> `core/`、`ros_adapter/` 两行是总纲 §4.2 的既定裁决，S2 尚未创建，待 S3/S4 生效后纳入判定。

| 层 / 单元 | 定位（一句话） | 允许的**包内**依赖 | 禁止的包内依赖 |
|---|---|---|---|
| `engine.py` | core 门面：FSM + 全局状态 + 编排 + 动作裁定 | `core/`、`tools/`、`utils/`、`perception/`、`ros_adapter/`（S2 未创建项不适用，判 `tools/`/`utils/`/`perception/`） | — |
| `core/`（★ S3，S2 未创建） | core 私有协作模块（领域逻辑） | `core/` 内部、`tools/model`+`tools/skill_api`（模型与技能契约）、`utils/state`+`utils/slog` | `utils` 传输类、`perception/`、`ros_adapter/`、`engine` |
| `ros_adapter/`（★ S3/S4，S2 未创建） | ROS 收发适配（唯一允许 `rospy` 与消息类型处） | `core/`（端口 Protocol）、`utils/`、`perception/`、`rospy`/ROS 消息 | `tools/`、`engine` |
| `tools/` | 执行平面：注册表 / 准入 / 路由 / 技能契约 / 模型与协议词表 | `tools/` 内部 + stdlib/三方 | `utils/`、`perception/`、`core/`、`engine`、`ros_adapter/` |
| `utils/` | 支撑平面：传输 / 租约 / 日志 / 配置 / 状态 / 装配 | `utils/` 内部、`tools/`（作为执行平面的消费者） | `perception/`、`core/`、`engine`、`ros_adapter/` |
| `perception/` | 感知层：传感器数据获取与几何换算 | `perception/` 内部、`utils/state` | `tools/`、`core/`、`engine`、`utils`（除 `state`）、`ros_adapter/` |
| `dispatcher_node.py` | composition root | `engine`、`utils/control_plane`、`ros_adapter/`（S2 未创建项不适用，判 `engine`/`utils.control_plane`） | — |

- 依赖方向：**支撑面 → 执行平面**、**core → 三个平面**；`tools/` 是叶子平面（零包内出边）。
- ROS 面方向：**`core/` 只声明端口，`ros_adapter/` 实现端口**（S3/S4 起生效）；`core/` 与其消费者不 import `ros_adapter/`。

### 4.6 双向耦合消解裁决（不用 adapter）

**问题**：`tools/control_plane.py#L9`（tools → utils）与 `zenoh_rpc/connection_lease/rpc_plane`（utils → tools）构成双向。

**裁决**：把 `ToolControlPlane` 从 `tools/` **迁出到 `utils/control_plane.py`**。

- **理由**：`ToolControlPlane` 的 docstring 自述为「装配 runtime + zenoh 传输 + ROS 执行宿主」（`PKG/tools/control_plane.py#L1`），
  其职责是**装配与线程支撑**，不是 agent 工具；迁出后 `tools/` 成为零包内出边的叶子平面，
  `utils/` 单向消费执行平面——依赖方向 `支撑面 → 执行平面` 与「传输服务于工具」的语义一致。
- **不采纳的替代**：① 在 `tools/` 定义抽象传输端口、在 `utils/` 实现——这是**新造 adapter**，违反硬边界；
  ② 保留 `tools/control_plane.py` 而把 `zenoh` 引用改成延迟导入/注入——同样是转接，且把装配责任留在执行平面。两条均否决。
- **无残留**：`tools/control_plane.py` 直接删除（§6），旧路径不留桩。

### 4.7 共享协议词表单点化裁决

**裁决**：新增 `tools/protocol.py`，集中承载 `ToolProtocolError`（现 `PKG/tools/model.py#L9-L22`）与错误码
`METHOD_NOT_FOUND`/`INVALID_PARAMS`（现 `PKG/tools/registry.py#L12-L13`）、`BUSINESS_REJECTED`（现 `PKG/tools/runtime.py#L17`）；
`LEASE_IDENTITY_FIELDS`（现 `PKG/tools/runtime.py#L20`）作为同一词表候选一并登记（可同迁，非强制）。

- **理由**：`connection_lease.py#L19-L20` 仅为 `ToolProtocolError` + `INVALID_PARAMS` 两个符号就依赖 455 行的 `registry.py`
  （§2.4），是**依赖宽度**问题；单点化后支撑面仅依赖一个零出边的词表模块，支撑面与执行平面的耦合面收窄为一个显式契约模块。
- **非转接器论证**：`protocol.py` 只承载既有异常类与常量定义，**不桥接任何新旧接口、不做任何转换**；
  其建立方式是「移动定义 + 更新导入」，非新增抽象层。
- **移除清单**：`model.py`/`registry.py`/`runtime.py` 中的旧定义**直接删除**，不保留 `from ... import` 转发别名（no shim）。
- **备选（低改动，不推荐）**：仅把三处常量移入 `tools/model.py`（不新增文件），代价是 `model.py` 语义扩宽为「模型+协议」；
  若评审偏好减少文件数，可回退至此，但本方案推荐 `protocol.py`。

### 4.8 skill_api.py 归属裁决

**候选**：① `tools/` 平面契约；② `utils/`；③ 保持包根契约。

**裁决：① → `tools/skill_api.py`（执行平面契约）**。

- **证据/理由**：`Skill` 的实例键空间与 `ToolSpec.name` 完全一致（`engine.py` 内多处以工具名为键查 `_skills`，§2.1），
  即「技能 = 注册工具的执行体」；`Skill`/`SkillBase`/`SkillVerdict` 是这些执行体的契约；把契约与执行体同置一棵树，
  使 `tools/` 成为自洽的执行平面。`SkillHost` 是该平面的**宿主 SPI**（由 core 的 engine 实现），放在平面内是常见且正确的做法。
- **否决 ②（utils）**：`Skill`/`SkillVerdict` 是 agent 执行语义，不是「系统支撑」；放 utils 会造成执行平面反依赖支撑面取契约，方向倒错。
- **否决 ③（保持包根）**：包根只应保留 core（`engine.py`）与包骨架；把执行平面契约留在包根会让「包根=多平面混合」的现状固化，
  与本方案目标相悖。
- **TYPE_CHECKING 引用说明**：`PKG/skill_api.py#L38-L41` 类型注解引用的 `dispatcher.recording.RecordingService`（未来支撑服务，
  建议落 `utils/recording.py`）与 `dispatcher.tools.vla.vlm_facade.VlmFacade`（技能族私有，落 `tools/vla/vlm_facade.py`）。
  二者均**仅类型期**引用（PEP 563），不影响运行期依赖图；归位为「待确认」项（§9）。
- **强制**：迁移后**不得**在包根保留 `dispatcher/skill_api.py` 转发模块（no shim）。

### 4.9 engine.py 与 composition root 归属裁决

- `engine.py` **保持包根**：它是 core 门面（FSM + 全局状态 + 编排 + 动作裁定），既不属于 tools/utils/perception；
  包根保留 `engine.py` + `__init__.py` 作为「core 层」（与总纲 §4.1 一致）。
- `dispatcher_node.py` **保持包外**（`ros_packages/dispatcher/` 下）：它是 composition root，本方案只改其
  `control_plane` 导入路径，不改启动序列语义；`create_dispatcher_engine`/`start_dispatcher_workers` 的吸收归 **S3**。

### 4.10 与总纲的一致性声明（替代原「与姊妹篇决策的差异」）

- **唯一权威**：目标形态已由**总纲 §4.1（目标树）/ §4.2（依赖矩阵）唯一钉死**，本方案只是其 **S2 执行版**：
  §4.2/§4.5 逐字对齐总纲，不自设平面、不发明依赖方向。
- 原先旧文档中「本设计对姊妹篇两处位置裁决做了收敛」（将 `skill_api.py` 移出包根、将 `control_plane` 移出 `tools/`）的说法，
  在总纲生效后**不再成立**——这些位置裁决已升格为总纲的**统一目标形态**，不再是本方案对姊妹篇的「收敛」。
- `design-dispatcher-engine-relocate-non-core.md` 的目标树（把新协作模块与 `state/config/slog` 留在包根、把 `control_plane`
  留在 `tools/`）**须服从本总纲**：其目标路径改为 `core/` + `ros_adapter/`、`control_plane` 归 `utils/`、行号按 1067 行版重锚。
  **其改写归 S3**，不在本方案内。
- 已 done 的历史记录（`design-dispatcher-zenoh-transport-migration.md`、`design-dispatcher-taskid-retirement-deps-migration.md`）
  **不改写**；其文档中曾把 `zenoh_rpc/connection_lease/rpc_plane`、`state/config/slog` 置于包根的表述，以本方案/总纲为准。

### 4.11 命名规范表（与总纲 §4.3 一致）

| 类型 | 规范 | 示例 |
|---|---|---|
| 平面目录 | 小写单词、语义化，层级即平面 | `tools/`、`utils/`、`perception/`（S3 起另有 `core/`、`ros_adapter/`） |
| 支撑模块 | 小写下划线，按「系统角色」命名 | `zenoh_rpc.py`、`connection_lease.py`、`rpc_plane.py`、`control_plane.py`、`slog.py`、`config.py`、`state.py` |
| 执行模块 | 小写下划线，按「执行平面词汇」命名 | `protocol.py`、`model.py`、`registry.py`、`runtime.py`、`executor.py`、`skill_api.py` |
| 技能族目录 | `tools/<family>/`，`__init__.py` + `<family>_skill.py` + 族私有模块 | `tools/scene_nav/scene_nav_skill.py`、`tools/scene_nav/graph_source.py`、`tools/vla/vla_skill.py`、`tools/vla/vlm_facade.py`、`tools/grasp/workflow.py` |
| 适配文件（S3 起） | `*_ros.py`；仅此命名可含 `rospy` 与 ROS 消息类型 | `core_channels_ros.py`、`params_ros.py`、`perception_ros.py` |
| 类 | 大驼峰、职责名词 | `ToolRegistry`、`ToolRuntime`、`ToolControlPlane`、`ZenohTaskMiddleware`、`ConnectionLeaseManager`、`RpcPlane`、`BasePolicyNode` |
| 常量 / 错误码 | 大写下划线 | `METHOD_NOT_FOUND`、`INVALID_PARAMS`、`BUSINESS_REJECTED` |
| 函数 / 方法 | snake_case（迁移非重构，一律沿用原名） | `tool_for_name`、`queryable_suffixes`、`get_fast_rgb` |
| 方案文档 | `design-dispatcher-*.md` | 本文档 |

### 4.12 接口形态与旧接口删除

- **`tools/` 平面公开面**（`tools/__init__.py` 重写 `__all__`）：`ToolProtocolError, ToolCall, ToolCommand, ToolSpec,
  SkillCommand, ToolRegistry, ToolRuntime, ToolExecutor, Skill, SkillBase, SkillVerdict, SkillHost`。
- **支撑面公开面**：无正式 `__all__` 契约（内部支撑），按模块直接引用。
- **感知面公开面**：`BasePolicyNode`、`PointCloudTimeWindow`、`PointCloudAccumulator`。
- **旧接口 → 删除**：见 §6；旧路径一律不留 re-export/别名/注释桩。

## 5. 迁移映射表

> 全部动作均为 **move（位置迁移）+ import 改写**；模块内容与方法体**零行为改写**。

| 旧路径/命名 | 新路径/命名 | 动作 | 备注 |
|---|---|---|---|
| `PKG/skill_api.py` | `PKG/tools/skill_api.py` | move | 内容逐字不变；TYPE_CHECKING 路径核实为 no-op（勘误 #3：其 `tools.model` 引用本就是 `dispatcher.tools.model`，无需改写） |
| `PKG/state.py` | `PKG/utils/state.py` | move | 逐字不变 |
| `PKG/config.py` | `PKG/utils/config.py` | move | 逐字不变 |
| `PKG/slog.py` | `PKG/utils/slog.py` | move | 逐字不变 |
| `PKG/connection_lease.py` | `PKG/utils/connection_lease.py` | move + import 改写 | `#L19-L20` 改指 `tools.protocol`（`ToolProtocolError`/`INVALID_PARAMS`） |
| `PKG/zenoh_rpc.py` | `PKG/utils/zenoh_rpc.py` | move + import 改写 | `#L25` 改指 `utils.connection_lease`；`#L26-L28` 改指 `tools.protocol`/`registry`/`runtime` |
| `PKG/rpc_plane.py` | `PKG/utils/rpc_plane.py` | move + import 改写 | `#L36-L38` 改指 `tools.protocol`/`registry`/`runtime`；`#L123` 懒引用路径不变（技能族未迁） |
| `PKG/tools/control_plane.py` | `PKG/utils/control_plane.py` | move + import 改写 | `#L9` 改指 `utils.zenoh_rpc`；`#L11` 改指 `tools.executor` |
| `PKG/tools/model.py::ToolProtocolError`（现 `#L9-L22`） | `PKG/tools/protocol.py::ToolProtocolError` | move（同平面） | 旧定义删除；`model.py` 保留数据模型 |
| `PKG/tools/registry.py::METHOD_NOT_FOUND/INVALID_PARAMS`（现 `#L12-L13`） | `PKG/tools/protocol.py` | move（同平面） | 旧定义删除 |
| `PKG/tools/runtime.py::BUSINESS_REJECTED`（现 `#L17`；`LEASE_IDENTITY_FIELDS` `#L20` 可选） | `PKG/tools/protocol.py` | move（同平面） | 旧定义删除 |
| `PKG/tools/__init__.py` | `PKG/tools/__init__.py` | rewrite | 按 §4.12 重写导出 |
| `PKG/engine.py#L26-L43` | 同文件 | rewrite（import 路径） | `utils.state/config/slog`、`tools.model`、`tools.skill_api`、`perception.base_policy` |
| `PKG/perception/base_policy.py#L35` | 同文件 | rewrite（import 路径） | `dispatcher.state` → `dispatcher.utils.state` |
| `NODE#L18` | 同文件 | rewrite（import 路径） | `dispatcher.tools.control_plane` → `dispatcher.utils.control_plane` |
| `TESTS/*.py`（§2.5 行号） | 同文件 | rewrite（import 路径 + patch 目标串） | `dispatcher.zenoh_rpc/connection_lease/rpc_plane` → `dispatcher.utils.*`；`dispatcher.tools.model.ToolProtocolError` → `dispatcher.tools.protocol.ToolProtocolError` |
| `tools/<family>/`（vla/scene_nav/flight/grasp） | 同路径 | 规则登记（无代码） | 族迁入归技能轮次；布局见 §4.11 |

## 6. 删除清单

| 删除项 | 理由 |
|---|---|
| `PKG/skill_api.py`（包根旧路径） | 迁入 `tools/skill_api.py`；禁止留转发桩 |
| `PKG/state.py`、`PKG/config.py`、`PKG/slog.py`（包根旧路径） | 迁入 `utils/`；禁止留转发桩 |
| `PKG/connection_lease.py`、`PKG/zenoh_rpc.py`、`PKG/rpc_plane.py`（包根旧路径） | 迁入 `utils/`；禁止留转发桩 |
| `PKG/tools/control_plane.py` | 迁入 `utils/control_plane.py`（装配/支撑职责归位）；旧路径删除是消除 `tools→utils` 反向边的**必要动作** |
| `PKG/tools/model.py` 中 `ToolProtocolError` 定义（`#L9-L22`） | 迁入 `tools/protocol.py`；`model.py` 只留数据模型 |
| `PKG/tools/registry.py` 中 `METHOD_NOT_FOUND`/`INVALID_PARAMS` 定义（`#L12-L13`） | 迁入 `tools/protocol.py`；收窄支撑面对 registry 的依赖宽度 |
| `PKG/tools/runtime.py` 中 `BUSINESS_REJECTED` 定义（`#L17`） | 迁入 `tools/protocol.py` |
| `PKG/tools/__init__.py` 旧导出列表 | 按 §4.12 重写（原列表缺失 `ToolExecutor`/`skill_api` 符号） |

> 说明：本清单全部为「位置替代后的旧位置删除」，**不含任何功能删除**；被替代项一律直接删除，不注释、不留 alias。

## 7. 实施步骤（P0–P4 分期）

> 总行为不变式（每期适用）：**不改任何方法体与外部协议**——slog 事件名/键、zenoh topic/queryable/presence token、
> `registry.list_tools()` 的 `revision`、`SkillHost` 端口签名、`ToolSpec` 字段一律**字节级不变**。所有 import 改写为纯路径替换。

### P0 — 执行平面协议词表单点化（`tools/protocol.py`）

- 范围：新增 `PKG/tools/protocol.py`；把 `ToolProtocolError`（model）、`METHOD_NOT_FOUND`/`INVALID_PARAMS`（registry）、
  `BUSINESS_REJECTED`（runtime）移入；更新 `tools/` 内部导入；更新 `TESTS/test_connection_lease.py#L29`、
  `test_rpc_plane_navigation.py#L27`、`test_rpc_plane_basic_flight.py#L25`、**`test_tool_registry.py#L20-L21`**（勘误 #1：
  原漏列第 4 处，该文件也从 `registry` 导入 `ToolProtocolError`）的 import；并把 §5 中 `connection_lease.py`/`zenoh_rpc.py`/
  `rpc_plane.py` 的**词表 import 改写从 P2 提前至本期**（勘误 #2：否则旧定义删除瞬间包根三模块导入断裂，
  P0 验收的 pytest 无法通过；P2 仅做文件 move，终态不变）。
- 行为不变式：`list_tools()["revision"]` 逐字不变；异常 `code/message/data` 语义不变。
- 验收：`py_compile`；`pytest l3-dispatcher-planner/tests/tool-registry` 全绿；`revision` 断言（§8）。
- 回退：删除 `protocol.py`，把定义还原至三模块并还原导入（纯增量+替换，可逆）。

### P1 — `utils/` 骨架 + 无包内依赖支撑模块迁入（state / slog / config）

- 范围：新增 `PKG/utils/__init__.py`；`state.py`/`slog.py`/`config.py` move 入 `utils/`；
  改写 `engine.py#L26-L43`、`perception/base_policy.py#L35` 等相关导入。
- 行为不变式：三文件逐字不变；`UAV_POLICY_DEFAULTS`/枚举取值不变。
- 验收：`py_compile`；L1/L2 import 冒烟（§8）；grep 零 `dispatcher.state`/`dispatcher.config`/`dispatcher.slog` 旧路径。
- 回退：三文件移回包根 + 还原导入。

### P2 — 传输支撑迁入 `utils/`（connection_lease / zenoh_rpc / rpc_plane）

- 范围：三文件 move 入 `utils/`；内部导入改 `utils.*`/`tools.protocol`；`TESTS` 四处 import 改写（§2.5）。
- 行为不变式：`queryable_suffixes()` 元组、`presence_token_key` 字符串、`RpcPlane` 恒启动语义、`_WIRE_ALIASES` 逐字不变；
  `ZenohTaskMiddleware.__init__` 缺 `LX_STACK_ID` 仍抛 `RuntimeError`。
- 验收：`py_compile`；`pytest l3-dispatcher-planner/tests/tool-registry` 全绿；`TESTS/test_rpc_plane_navigation.py`
  的 scene_graph 用例维持「因 `scene_nav` 未迁而失败」的既有预期（非本轮引入）。
- 回退：三文件移回包根 + 还原导入。

### P3 — 控制面归位（消除双向耦合）

- 范围：`tools/control_plane.py` → `utils/control_plane.py`；`NODE#L18` 导入改写；删除 `tools/control_plane.py`。
- 行为不变式：`ToolControlPlane` 线程名（`tool-command-consumer`/`zenoh-tool-server`）、`_serve` 5s 重连、`_consume` 兜底 `emit(fail)` 语义不变。
- 验收：`py_compile`；**依赖方向 grep（A1）**：`tools/` 内零 `dispatcher.utils`/`dispatcher.zenoh_rpc`/`dispatcher.perception`（§8）；
  `NODE` 可导入（L3 或静态）。
- 回退：文件移回 `tools/` + 还原 `NODE` 导入。

### P4 — 技能契约归位（`tools/skill_api.py`）+ 技能族归位规则登记

- 范围：`skill_api.py` → `tools/skill_api.py`；`engine.py#L39` 导入改写；`tools/__init__.py` 重写导出；
  TYPE_CHECKING 引用路径更新（`tools.model`）；在文档层面固化 `tools/<family>/` 布局与命名（§4.11），
  登记 `tools/scene_nav/graph_source.py`、`tools/vla/vlm_facade.py`、`tools/grasp/workflow.py` 的预期落点
  （对应 §2.4 的两处悬空/未迁引用）。
- 行为不变式：`Skill`/`SkillBase`/`SkillHost`/`SkillVerdict` 定义逐字不变；运行期 import 面不变（仍只有 `enum`/`typing`）。
- 验收：`py_compile`；L1 import 冒烟包含 `dispatcher.tools.skill_api`；grep 零 `dispatcher.skill_api`（含 tests）；
  §4.11/§5 规则条目齐备且无新增代码文件。
- 回退：文件移回包根 + 还原导入与 `tools/__init__`。

## 8. 验收标准

> 可执行判断（测试命令、契约对比、字节级一致性、门禁 grep）。每项通过即打勾。

- [ ] **语法**：`python3 -m py_compile` 对 `PKG/**/*.py` 与 `NODE` 全部通过。
- [ ] **L1 冒烟（零 ROS 子集，主机必跑）**：
      `PYTHONPATH=l3-dispatcher-planner/ros_packages/dispatcher python3 -c "import dispatcher.tools.protocol, dispatcher.tools.model, dispatcher.tools.registry, dispatcher.tools.runtime, dispatcher.tools.executor, dispatcher.tools.skill_api; print('SMOKE-L1-OK')"`
- [ ] **L2 冒烟**（判定：`python3 -c 'import rospy, yaml, numpy'` 退出码为 0）：
      `import dispatcher.utils.state, dispatcher.utils.config, dispatcher.utils.slog, dispatcher.perception.pointcloud_accumulator`。
- [ ] **L3 冒烟**（判定：ROS1 消息包可导入）：
      `import dispatcher.engine, dispatcher.utils.zenoh_rpc, dispatcher.utils.connection_lease, dispatcher.utils.rpc_plane, dispatcher.utils.control_plane`。
- [ ] **既有测试**：`pytest l3-dispatcher-planner/tests/tool-registry` 全绿（`test_connection_lease`/`test_tool_registry`/
      `test_rpc_plane_basic_flight`；`test_rpc_plane_navigation` 的 scene_graph 用例维持既有预期失败）。
- [ ] **字节级契约不变**：`ToolRegistry.default().list_tools()["revision"]` 与迁移前逐字一致（`sha256:` 值不变）。
- [ ] **传输契约不变**：`ZenohTaskMiddleware.queryable_suffixes()` 与迁移前逐字一致。
- [ ] **A1（总纲 §4.4）依赖方向门禁**——**明确判定命令**：
      ```
      grep -rn "dispatcher\.\(utils\|perception\|core\|ros_adapter\)" l3-dispatcher-planner/ros_packages/dispatcher/dispatcher/tools/   # 期望零命中（S2 仅 utils|perception 已存在）
      grep -rn "dispatcher\.engine" l3-dispatcher-planner/ros_packages/dispatcher/dispatcher/utils/ l3-dispatcher-planner/ros_packages/dispatcher/dispatcher/perception/   # 期望零命中
      ```
      （S2 后 `core/`、`ros_adapter/` 尚未创建，第一条命令的实际命中面为 `utils|perception`；S3/S4 创建后按总纲 §4.4 全量判定。）
- [ ] **A3（总纲 §4.4）旧路径清零 / 无 re-export 转发桩**——**明确判定命令**：
      ```
      ls l3-dispatcher-planner/ros_packages/dispatcher/dispatcher/skill_api.py \
         l3-dispatcher-planner/ros_packages/dispatcher/dispatcher/state.py \
         l3-dispatcher-planner/ros_packages/dispatcher/dispatcher/config.py \
         l3-dispatcher-planner/ros_packages/dispatcher/dispatcher/slog.py \
         l3-dispatcher-planner/ros_packages/dispatcher/dispatcher/connection_lease.py \
         l3-dispatcher-planner/ros_packages/dispatcher/dispatcher/zenoh_rpc.py \
         l3-dispatcher-planner/ros_packages/dispatcher/dispatcher/rpc_plane.py \
         l3-dispatcher-planner/ros_packages/dispatcher/dispatcher/tools/control_plane.py   # 期望每个均 "No such file or directory"
      grep -rn "dispatcher\.skill_api\|dispatcher\.state\|dispatcher\.config\|dispatcher\.slog\|dispatcher\.zenoh_rpc\|dispatcher\.connection_lease\|dispatcher\.rpc_plane\|dispatcher\.tools\.control_plane" l3-dispatcher-planner/ros_packages/dispatcher l3-dispatcher-planner/tests/tool-registry   # 期望零命中（dispatcher.utils.* 除外）
      ```
      并人工确认：包根与 `tools/` 下**不存在仅做 import 转发的模块**（无 re-export shim、无注释桩）。
- [ ] **slog/topic 不变**：`dispatcher_started`、`task_phase_published`、`tool_call_received` 等事件名与键集、
      topic 名与 payload 字节级一致（本方案不改逻辑，作为回归红线）。
- [ ] **契约一致性**：总纲 §4.4 中与 S2 相关的门禁（G1 相关、A1、A3、A5）逐条判定；未达成项在方案或 issue 中登记，无静默漂移。

## 9. 风险与对策

| 风险 | 影响 | 对策 |
|---|---|---|
| 迁移面广（13 个模块 + 4 处测试），import 漏改 | 运行期 ImportError | 分期（P0-P4）逐期 `py_compile` + L1/L2/L3 冒烟 + 负向 grep（A1/A3）三闸 |
| `tools/` 与支撑面的依赖方向再次被打破 | 双向耦合复发 | §4.5 依赖矩阵（=总纲 §4.2）+ §8 A1 作为门禁；任何新 import 需按矩阵判定 |
| `tools/protocol.py` 新增文件被质疑「是否转接器」 | 评审返工 | §4.7 非转接器论证：仅移动既有异常/常量定义，不转换接口；备选（并入 `model.py`）已给出 |
| 测试路径改写引入 case 收集失败 | 验收误判 | §2.5 逐文件行号锚定；`pytest` 收集数与迁移前对比 |
| `skill_api` 迁入 `tools/` 后 TYPE_CHECKING 引用 `dispatcher.recording`/`vlm_facade` | 类型检查期 ImportError | 仅类型期引用（PEP 563）；归位登记：`recording`→建议 `utils/recording.py`，`vlm_facade`→`tools/vla/vlm_facade.py`（**待确认**） |
| `perception → utils.state` 成为感知层对支撑面的依赖 | 层次回退争议 | 仅枚举词表依赖，方向为「感知→支撑」，不构成环；已在 §4.4/§4.5 显式登记 |
| 既有孤儿/悬空引用（`_decision_chain_not_ready_reason` L494、`scene_nav.graph_source` L123）被误判为本轮引入 | 返工/误修 | §2.4 登记为非本轮引入；本方案零行为改写，不修不删 |
| 执行者沿用旧文档过期行号（如 executor 47 行、registry L247-L260） | 定位错误 | §2.6 勘误登记；执行一律以本方案 §2 重锚行号为准 |
| 旧路径转发桩被「方便起见的保留」 | 违反 anti-shim 硬边界 | §6 删除清单 + §8 A3 验收项 |
| 本方案被误用为「可自行改目标树」 | 目标形态分叉、二次搬迁 | §摘要与 §4.10 声明：改树须先改总纲；§4.2/§4.5 逐字对齐总纲 §4.1/§4.2 |

回滚路径：本方案为**纯移动 + import 改写**，回退 = 各期把文件移回原位并还原 import（每期独立可回退）；
执行前建议对 `PKG/` 全量快照（放主机本地区，不入库）。

## 10. 修改点清单汇总

| 文件 | 动作 | 说明 |
|---|---|---|
| `PKG/tools/protocol.py` | 新增 | 共享协议词表：`ToolProtocolError` + `METHOD_NOT_FOUND`/`INVALID_PARAMS`/`BUSINESS_REJECTED`（`LEASE_IDENTITY_FIELDS` 可选） |
| `PKG/tools/model.py` | 修改 | 删除 `ToolProtocolError` 定义；导入改指 `tools.protocol` |
| `PKG/tools/registry.py` | 修改 | 删除错误码定义；导入改指 `tools.protocol` |
| `PKG/tools/runtime.py` | 修改 | 删除 `BUSINESS_REJECTED` 定义；导入改指 `tools.protocol` |
| `PKG/tools/executor.py` | 修改 | 导入改指 `tools.protocol`（如引用） |
| `PKG/tools/skill_api.py` | 新增（move） | 自包根移入；TYPE_CHECKING 路径更新 |
| `PKG/tools/control_plane.py` | 删除（move 出） | 迁至 `PKG/utils/control_plane.py` |
| `PKG/tools/__init__.py` | 修改 | 重写导出（§4.12） |
| `PKG/utils/__init__.py` | 新增 | 支撑平面包骨架 |
| `PKG/utils/state.py` / `config.py` / `slog.py` | 新增（move） | 自包根移入，逐字不变 |
| `PKG/utils/connection_lease.py` / `zenoh_rpc.py` / `rpc_plane.py` | 新增（move） | 自包根移入；内部导入改指 `utils.*`/`tools.protocol` |
| `PKG/utils/control_plane.py` | 新增（move） | 自 `tools/` 移入；导入改指 `utils.zenoh_rpc`/`tools.executor` |
| `PKG/skill_api.py` / `state.py` / `config.py` / `slog.py` / `connection_lease.py` / `zenoh_rpc.py` / `rpc_plane.py` | 删除（move 出） | 旧路径不留桩 |
| `PKG/engine.py` | 修改 | 仅 import 路径改写（`utils.*`/`tools.*`/`perception.*`），方法体零改动 |
| `PKG/perception/base_policy.py` | 修改 | 仅 `dispatcher.state` → `dispatcher.utils.state` |
| `PKG/perception/__init__.py` / `pointcloud_accumulator.py` | 不动 | 感知层位置不变 |
| `NODE` | 修改 | 仅 `control_plane` 导入路径改写 |
| `TESTS/test_connection_lease.py` / `test_tool_registry.py` / `test_rpc_plane_navigation.py` / `test_rpc_plane_basic_flight.py` | 修改 | import 路径与 patch 目标串同步改写 |
| `PKG/tools/{vla,scene_nav,flight,grasp}/` | 登记（无代码） | 归位规则见 §4.11/§5；实际迁入归技能轮次 |
| `doc/l3-dispatcher-planner/iteration/design-dispatcher-package-topology.md` | 改写 | **本方案文件自身**（S2 执行版，对齐总纲 §4.1/§4.2） |

## 11. 附录：执行记录

### 2026-09-12 执行（S2 置 done）

- **执行者**：code-fixer 子智能体执行 P0–P4，SOLO Agent 独立复验门禁（§4.3 流水线第 4/6 步）。
- **本地准备**：PKG+TESTS 快照 `/tmp/diffagent2-s2-snapshot-20260912-161522`；基线契约值 `revision = sha256:cc1dcd1bcfa6f33fa10222042918a234ddcf2eddd7a79b96925194a981c0d69b`、工具数 14。
- **验收实测（主 Agent 独立复跑）**：语法 PKG+NODE+TESTS 全量 `py_compile` 通过；L1 冒烟 OK；L2 冒烟 OK；L3 冒烟（`utils.zenoh_rpc` 缺 zenoh、`dispatcher.engine` 因 cv2×NumPy2 不兼容——均已在迁移前快照复现同样失败，属既有环境问题，R9 回退静态验收：diff 逐字对照 + py_compile + import 链解析）；pytest 44 通过/6 既有失败（基线一致）；字节级契约 `revision` 复测与基线逐字一致、工具数 14，`queryable_suffixes`/`presence_token_key` 快照 diff 字节级一致；A1 双向零命中；A3 旧路径文件与源码引用清零、无转发桩、包根只剩 `engine.py`+`__init__.py`+三平面目录。
- **勘误（已回写 §5/§7-P0）**：#1 `test_tool_registry.py#L20-L21` 漏列（第 4 处词表导入改写）；#2 P0/P2 分期边界——包根三传输模块的词表 import 改写提前至 P0；#3 skill_api TYPE_CHECKING「路径更新」实为 no-op；#4 本主机 L2/L3 冒烟须 `source /opt/ros/noetic/setup.bash` 且 `PYTHONPATH` 用追加写法。
- **登记的后续轮次待办（本轮不修）**：`utils/connection_lease.py#L21` 本地 `BUSINESS_REJECTED = -32000`（快照证实为既有，与 `tools/protocol.py#L32` 重复同值）——词表单点化收尾候选；`_decision_chain_not_ready_reason` 孤儿引用；`scene_nav.graph_source` 悬空引用（技能族未迁）；TYPE_CHECKING 引用 `dispatcher.recording`/`tools.vla.vlm_facade` 未迁；旧位置 stale `__pycache__`（不入库，无运行期影响）。

> 注：本附录曾于 2026-09-12 回写后被外部进程（Trae IDE 陈旧缓冲）回滚丢失，2026-09-13 依据会话记录重建，内容与首次回写一致。

**登记的后续轮次（不在本方案内）**：`core/` + `ros_adapter/` 创建与 engine 非 core 职责迁出归 **S3**；
其余 ROS 面适配（`params_ros`/`clock_ros`/`perception_ros`）归 **S4**；技能族迁入（`tools/<family>/`）与
`SkillHost` 端口同轮落地；`recording` / `vlm_facade` 归位；`tasks` 注入轮次；`specs/tools/*` 门禁脚本迁移。

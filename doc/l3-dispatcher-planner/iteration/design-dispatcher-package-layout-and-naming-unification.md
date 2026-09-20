# dispatcher 目录架构与命名统一 方案

> 摘要：把 `dispatcher/` 的子包收敛为与 l3 契约术语一对一的七个平面
> （`core/` `toolplane/` `skills/` `execution/` `ros_adapter/` `perception/`
> `support/`），消除 `execution` 与 `executor` 的同词根歧义、`utils/` 与
> `tools/` 对工具面的劈分、`services/` 的无归属状态；并首次为 Python 侧
> 目录与命名建立权威规范。代码范围：`l3-dispatcher-planner/ros_packages/dispatcher/**`、
> `l3-dispatcher-planner/tests/**`（仅 import 路径同步）；契约范围：
> `specs/implemented/`。依据来源：用户 2026-09-19 指令「需要更明确的命名、
> 结构和统一规范」；姊妹篇 `design-dispatcher-vla-geometry-rename-and-migration-comment-cleanup.md`
> （命名口径一致，本次不修改）。

## 0. 元信息

| 项 | 值 |
|----|----|
| 日期 | 2026-09-19 |
| 目标路径 | `l3-dispatcher-planner/ros_packages/dispatcher/`、`l3-dispatcher-planner/tests/`、`specs/implemented/` |
| 状态 | done（AGENTS.md 归属表述待用户单独许可，见 §11） |
| 关联文档 | `specs/implemented/l3-dispatcher.spec.md`、`specs/implemented/inner/l3-core-boundary.spec.md`、`l3-skill-contract.spec.md`、`l3-execution-seam.spec.md`、`l3-tool-plane.spec.md`、`l3-ros-adapter-boundary.spec.md`、`l3-migration-protocol.spec.md`、`l3-coding-style.spec.md`、`doc/l3-dispatcher-planner/iteration/_TEMPLATE.md` |

## 1. 背景与动机

- **用户指令**：需要更明确的命名、结构与统一规范；目录架构与命名规范
  是本次优化对象（`AGENTS.md` 代码优化工作流 §4）。
- **契约与目录未一对一**：l3 契约的职责词汇是 core / 工具面 / 技能 /
  共享执行（执行缝）/ ROS 适配 / 感知 / 系统支撑，但代码目录是
  `core/ tools/ execution/ services/ perception/ ros_adapter/ utils/`——
  工具面被 `tools/` 与 `utils/` 两处劈分，`services/` 不在任何契约词汇里。
- **同词根歧义**：`tools/executor.py::ToolExecutor` 与 `execution/` 同词根、
  不同层、无调用关系，讨论与检索时无法区分。
- **规范缺归属**：`l3-coding-style.spec.md` 标题即「l3 **C++** 编码规范」
  （`l3-coding-style.spec.md:1,10`），Python 侧目录与命名无契约承担；
  `AGENTS.md` 却把「编码风格与命名」笼统归给它。

## 2. 现状事实（问题清单）

> 每条带「文件路径 + 行号」证据。行号基于 2026-09-19 工作区状态。

### 2.1 命名歧义

- [ ] `ros_packages/dispatcher/dispatcher/tools/executor.py#L9` — `class ToolExecutor`，与 `dispatcher/execution/` 目录同词根、不同平面。
- [ ] `tools/executor.py#L16-L21` — `execute()` 仅两行：`registry.tool_for_name` + `host.start_tool_workflow`，是纯转发层。
- [ ] `execution/__init__.py#L1` 与 `services/__init__.py#L1` — **完全相同**的 docstring「dispatcher 内部领域能力。」，两目录均无法自述职责。
- [ ] `dispatcher/__init__.py#L1` — docstring「Mixins for the UAV policy node.」与现包职责不符（遗留）。
- [ ] `tools/__init__.py#L1` — docstring「Executable tool registry and runtime for the zenoh control plane.」，但同目录含技能实现（`tools/flight/`、`tools/vla/`）。

### 2.2 工具面被劈成 `tools/` 与 `utils/` 两处

- [ ] `utils/control_plane.py#L1` — 自述「Compose the tool runtime, zenoh transport, and ROS execution host.」→ 工具面装配。
- [ ] `utils/rpc_plane.py#L1-L5` — 自述「单入口 RPC 控制面」→ 工具面协议面。
- [ ] `utils/zenoh_rpc.py#L3-L7` — 自述「Zenoh transport adapter for the in-process executable tool runtime」→ 工具面传输。
- [ ] `utils/connection_lease.py#L1-L9` — 自述「connection lease manager」→ 工具面连接租约。
- [ ] `utils/zenoh_rpc.py#L26`、`utils/control_plane.py#L11`、`utils/connection_lease.py#L20` — `utils/` import `tools/`；反向零命中（`tools/` 从不 import `utils/`）→ `utils/` 实为工具面上层，不是「工具函数」。
- [ ] `utils/__init__.py#L1-L8` — 自述「系统支撑平面（support plane）」，但成员一半是工具面/传输职责。

### 2.3 技能层与工具面基础设施混在同一目录

- [ ] `tools/registry.py`、`tools/runtime.py`、`tools/protocol.py`、`tools/model.py` — 工具面基础设施，与 `tools/flight/`、`tools/vla/` 同级。
- [ ] `specs/implemented/inner/l3-core-boundary.spec.md#L26-L27` — B1 同时写 `skills/*` 与 `tools/vla`、`tools/flight`、`tools/scene_nav` 两种路径形态，契约自身不一致（`tools/scene_nav` 目录并不存在）。
- [ ] `specs/implemented/inner/l3-skill-contract.spec.md#L10` — 引用 `dispatcher/dispatcher/skill_api.py`，实际路径为 `dispatcher/tools/skill_api.py`，契约路径漂移。

### 2.4 `services/` 无契约归属

- [ ] `services/flight_motion.py#L5` — `class FlightMotion(SkillBase)` 是**技能基类**，不是服务；被 `tools/flight/translate_skill.py#L3`、`return_skill.py#L2`、`rotate_skill.py#L3` 引用。
- [ ] `services/flight_session.py#L7` — `class FlightSession`（飞行原点/会话状态），被 `execution/composition.py#L5` 引用。
- [ ] `specs/implemented/l3-dispatcher.spec.md#L15-L19` 与 `l3-migration-protocol.spec.md#L28-L33` — 归属裁决词汇只有 core / 技能 / 共享服务 / 执行缝 / 规划，无「services」目录概念。

### 2.5 执行缝端口错放在飞行家族内

- [ ] `tools/flight/ports.py#L44-L70` — `Goal`、`Progress`、`ActionResult`、`FlightState`、`FlightConfig`、`FlightPorts` 是**跨家族共享**的动作端口（`execution/waypoint_execution.py#L6`、`execution/skill_host.py#L4`、`ros_adapter/planner_execution_ros.py#L12`、`skills/vla` 侧动作出海同用），却位于 `tools/flight/`。
- [ ] `specs/implemented/inner/l3-skill-contract.spec.md#L127-L128` — 契约已把 `FlightPorts` 归到 execution 一侧（「由 FlightPorts 承载 planner 通信」），代码位置与契约不符。
- [ ] `tools/flight/ports.py#L73-L85` — `class FlightHost(Protocol)` 全仓**无任何引用**（仅自身定义），属无调用方声明。

### 2.6 core 内含工具面入口

- [ ] `core/tool_workflow.py#L42-L69` — `ToolWorkflowHost.start_tool_workflow` 做「准入技能 / 入队 / 取消」，语义偏工具面，却列在 `l3-core-boundary.spec.md#L82` 白名单内；`core/tool_workflow.py#L7` 亦 import `dispatcher.tools.model`。

### 2.7 结构尺度

- [ ] `perception/base_policy.py` — 单文件约 121 KB，同时承担感知节点与 VLA 几何原语源。
- [ ] `l3-dispatcher-planner/tests/` — 子目录按契约/主题命名（`core-boundary/`、`tool-registry/`、`basic-flight/`），与源码平面名不对应。

## 3. 目标与约束

- **目标**：
  1. `dispatcher/` 子包与契约术语**一对一**：`core/` `toolplane/` `skills/`
     `execution/` `ros_adapter/` `perception/` `support/`。
  2. 消除同词根跨层命名（`execution` vs `executor`），消除泛名目录
     （`utils/`）与无归属目录（`services/`）。
  3. 为 Python 侧目录与命名建立**有权威归属**的统一规范（新叶契约）。
- **Non-Goals**：
  - 不改任何行为契约：topic 名、param 名、消息字段名、RPC 方法名、
    工具 wire 名、结构化日志事件名、状态迁移 reason 字符串一律不变。
  - 不改 `core/`、`ros_adapter/`、`perception/` 的**内部实现逻辑**。
  - 不改 C++、planner、l4。
  - 不重命名 `tests/` 子目录（仅同步 import 路径；测试执行按 §8 统一声明跳过）。
- **硬边界**：
  - **契约先行**：目标形态必须先落 `specs/`（`proposed` 及以上），否则不得动代码（`l3-migration-protocol.spec.md#L17-L18`，门禁 G18）。
  - 禁止新设计转接器来转接新旧路径（`AGENTS.md` 代码优化工作流 §5；`l3-migration-protocol.spec.md#L54`）。
  - 被替代的旧路径直接删除，不得保留 shim/转发模块或注释桩（`AGENTS.md` 代码优化工作流 §6；`l3-migration-protocol.spec.md#L55-L56`）。

## 4. 方案决策

### 4.1 目标目录树

```
ros_packages/dispatcher/dispatcher/
  __init__.py
  engine.py                 # 装配根 + 六态 FSM 入口（保持，内容不动）
  core/                     # 六态 FSM 与任务队列（契约白名单 core/**，内部不动）
  toolplane/                # 工具面：调用模型/协议/注册/运行时/准入/事件/租约/传输/RPC/控制面
    __init__.py
    model.py                # 原 tools/model.py
    protocol.py             # 原 tools/protocol.py
    registry.py             # 原 tools/registry.py
    runtime.py              # 原 tools/runtime.py
    intake.py               # 原 tools/executor.py（ToolExecutor → ToolIntake）
    connection_lease.py     # 原 utils/connection_lease.py
    zenoh_transport.py      # 原 utils/zenoh_rpc.py
    rpc_plane.py            # 原 utils/rpc_plane.py
    control_plane.py        # 原 utils/control_plane.py
  skills/                   # 技能层：协议 + 家族实现
    __init__.py
    api.py                  # 原 tools/skill_api.py（Skill/SkillBase/SkillHost/SkillVerdict）
    flight/
      __init__.py
      catalog.py            # 原 tools/flight/catalog.py
      motion.py             # 原 services/flight_motion.py
      session.py            # 原 services/flight_session.py
      takeoff_skill.py land_skill.py translate_skill.py
      rotate_skill.py return_skill.py emergency_stop_skill.py
    vla/
      __init__.py
      catalog.py ports.py vla_geometry.py vla_skill.py   # 原地迁入
  execution/                # 共享执行（执行缝）
    __init__.py
    ports.py                # 原 tools/flight/ports.py 的共享动作端口部分
    waypoint.py             # 原 execution/waypoint_execution.py
    skill_host.py           # 保持
    composition.py          # 保持（装配模块，见 §4.3 例外）
  ros_adapter/              # ROS 收发（不动）
  perception/               # 感知（不动）
  support/                  # 系统支撑：状态/配置/日志
    __init__.py
    state.py config.py slog.py     # 原 utils/ 同名文件
```

删除的目录名：`tools/`、`utils/`、`services/`（三者均不保留 shim）。

### 4.2 命名规范表（Python）

| 类型 | 规范 | 示例 |
|------|------|------|
| 子包（平面） | 契约术语的单一英文名；禁 `utils`/`helpers`/`misc`/`common` 泛名 | `core/` `toolplane/` `skills/` `execution/` `ros_adapter/` `perception/` `support/` |
| 模块（家族内） | 家族前缀，`__init__` 除外 | `skills/vla/vla_geometry.py` |
| 模块（平面基础设施） | 领域名词，不带平面前缀（目录已表达平面） | `toolplane/registry.py` |
| 模块（执行缝） | 语义名词，不重复平面前缀 | `execution/waypoint.py`（非 `waypoint_execution.py`） |
| 类 | PascalCase，领域名词；类名不重复其所在平面的目录名 | `ToolIntake`、`WaypointExecution` |
| 函数/方法 | snake_case，动词开头 | `start_tool_workflow`、`can_execute` |
| 私有成员 | 单下划线前缀 | `_active_call_id` |
| 常量 | UPPER_SNAKE_CASE | `DISPATCHER_STATE` |
| 同词根纪律 | 同一词根（execute/execution）不得同时命名两个不同平面的实体 | `execution/`（平面）与 `ToolIntake`（工具面入口） |
| `__init__.py` | 每个子包必须有 docstring 声明**本平面职责**；导出面用 `__all__`，内部模块不导出 | 见 §4.5 |

### 4.3 依赖方向（分层表）

| 平面 | 允许 import | 禁止 import |
|------|------------|------------|
| `engine.py`（装配根） | 全部平面 | — |
| `core/` | `core/`、`support/`、`skills/api.py`（协议与四裁决词汇） | `skills/<family>/`、`execution/`、`toolplane/`、`ros_adapter/` |
| `toolplane/` | `toolplane/`、`support/`、`skills/api.py` | `core/`、`execution/`、`skills/<family>/` |
| `skills/<family>/` | `skills/<family>/`、`skills/api.py`、`execution/ports.py` | `core/`、`toolplane/`、其他家族 |
| `execution/` | `execution/`、`support/`、`skills/api.py` | `core/`、`toolplane/` |
| `ros_adapter/` | `execution/ports.py`、`support/`、ROS 消息包 | 领域逻辑 |
| `perception/` | `perception/`、`support/` | 技能/执行缝 |

例外：装配模块 `execution/composition.py` 与 `dispatcher_node.py` 可 import 任意平面（装配职责），此例外在契约中显式登记。

### 4.4 关键归属裁决

> 按 `l3-migration-protocol.spec.md#L26-L37` 的裁决顺序，逐项可追溯。

| 单元 | 裁决 | 依据 |
|------|------|------|
| `tools/{model,protocol,registry,runtime,executor}` | → `toolplane/` | 属下行调用准入/事件/取消，归工具面（`l3-tool-plane`） |
| `utils/{connection_lease,zenoh_rpc,rpc_plane,control_plane}` | → `toolplane/` | §2.2 依赖方向证明其为工具面上层；`l3-tool-plane` 拥有连接租约 |
| `utils/{state,config,slog}` | → `support/` | 系统支撑，非契约平面，`utils/__init__.py#L1` 自述即 support plane |
| `tools/skill_api.py` | → `skills/api.py` | 技能身份/生命周期/端口，归 `l3-skill-contract`（该契约 `#L10` 已声明其为参考实现） |
| `tools/flight/`、`tools/vla/` | → `skills/flight/`、`skills/vla/` | 只在某一任务流程中被调用 → 对应技能 |
| `services/flight_motion.py` | → `skills/flight/motion.py` | flight 家族共用技能基类 → 技能层 |
| `services/flight_session.py` | → `skills/flight/session.py` | 仅 flight 家族消费（`execution/composition.py#L5` 注入）→ 技能层 |
| `tools/flight/ports.py` 的共享动作端口 | → `execution/ports.py` | 跨家族共享的下行动作端口 → 执行缝（`l3-skill-contract#L127` 已如此归属） |
| `tools/flight/ports.py#L73` `FlightHost` Protocol | **删除** | 无任何调用方（§2.5），按「无调用方不迁」处理 |
| `core/tool_workflow.py` | **保留在 core** | 它写 `prompt_queue`/`ledger`/`task_phase` 等 core 状态，是工具面→core 的边界对象；移动需改 core 白名单与 B3，收益不足 |

### 4.5 `__init__.py` 规范

- 每个子包 docstring 声明**本平面职责**与契约归属，禁止「dispatcher 内部领域能力」这类无法区分的泛描述（§2.1）。
- `support/__init__.py` 保留现有 support plane 自述；`skills/__init__.py`、`toolplane/__init__.py`、`execution/__init__.py` 分别自述。
- 导出面：`toolplane/__init__.py` 保留现有 `__all__`（改名同步）；`skills/__init__.py` 不导出家族（避免技能被隐式 import）。
- `dispatcher/__init__.py` docstring 改为与本包职责一致（§2.1）。

### 4.6 旧接口 → 删除

- `dispatcher.tools.*`、`dispatcher.utils.*`、`dispatcher.services.*` 三个模块前缀在本次改动后**不再存在**，不保留转发模块或 `__getattr__` 兼容层。
- `ToolExecutor`、`FlightHost` Protocol 直接删除/改名，不留别名。

## 5. 迁移映射表

| 旧路径/命名 | 新路径/命名 | 动作 | 备注 |
|-------------|-------------|------|------|
| `tools/model.py` | `toolplane/model.py` | rename | 内容不变 |
| `tools/protocol.py` | `toolplane/protocol.py` | rename | 内容不变 |
| `tools/registry.py` | `toolplane/registry.py` | rename | 内容不变 |
| `tools/runtime.py` | `toolplane/runtime.py` | rename | 内容不变 |
| `tools/executor.py` | `toolplane/intake.py` | rename+rewrite | 类 `ToolExecutor`→`ToolIntake`；方法 `execute`→`start` |
| `utils/connection_lease.py` | `toolplane/connection_lease.py` | rename | 内容不变 |
| `utils/zenoh_rpc.py` | `toolplane/zenoh_transport.py` | rename | 模块名与传输职责对齐；类名 `ZenohTaskMiddleware` 不变 |
| `utils/rpc_plane.py` | `toolplane/rpc_plane.py` | rename | 内容不变 |
| `utils/control_plane.py` | `toolplane/control_plane.py` | rename+rewrite | 改 import（`tools.executor`→`toolplane.intake`） |
| `utils/state.py` | `support/state.py` | rename | 内容不变 |
| `utils/config.py` | `support/config.py` | rename | 内容不变 |
| `utils/slog.py` | `support/slog.py` | rename | 内容不变 |
| `tools/skill_api.py` | `skills/api.py` | rename | 内容不变 |
| `tools/flight/**` | `skills/flight/**` | rename | 六个技能 + `catalog.py` |
| `tools/vla/**` | `skills/vla/**` | rename | 五个模块 |
| `services/flight_motion.py` | `skills/flight/motion.py` | rename | 内容不变 |
| `services/flight_session.py` | `skills/flight/session.py` | rename | 内容不变 |
| `tools/flight/ports.py`（共享动作端口部分） | `execution/ports.py` | split+rename | `FlightHost` Protocol 删除（§4.4） |
| `execution/waypoint_execution.py` | `execution/waypoint.py` | rename | 去平面前缀重复 |
| `dispatcher.tools.*` / `dispatcher.utils.*` / `dispatcher.services.*` | `dispatcher.toolplane.*` / `dispatcher.support.*` / `dispatcher.skills.*` / `dispatcher.execution.*` | rewrite | 源码 + tests 全部 import 点 |

## 6. 删除清单

| 删除项 | 理由 |
|--------|------|
| `dispatcher/tools/` 目录名 | 被 `toolplane/` + `skills/` 取代，不保留 shim |
| `dispatcher/utils/` 目录名 | 被 `toolplane/` + `support/` 取代，泛名且职责混装 |
| `dispatcher/services/` 目录名 | 无契约归属；内容归位到 `skills/flight/` |
| `class ToolExecutor`（`tools/executor.py#L9`） | 同词根跨层歧义；改名 `ToolIntake` |
| `ToolExecutor.execute` 方法名 | 改名 `start`，与 `ToolRuntime.can_execute`/`admit` 区分 |
| `class FlightHost(Protocol)`（`tools/flight/ports.py#L73-L85`） | 全仓零引用，无调用方 |
| `execution/__init__.py#L1` 与 `services/__init__.py#L1` 的泛 docstring | 无法区分职责 |
| `dispatcher/__init__.py#L1`「Mixins for the UAV policy node.」 | 与现包职责不符 |

## 7. 实施步骤（P0–P4）

### P0 — 契约先行（spec 提案，不动代码）

- 范围：
  - 新增叶契约 `specs/implemented/inner/l3-package-layout.spec.md`
    （`Contract-ID: l3-dispatcher/package-layout`，`Parent: specs/implemented/l3-dispatcher.spec.md`），
    落 §4.1–§4.6：目标目录树、命名规范表、依赖方向表、`__init__.py` 规范、门禁。
  - 在 `specs/implemented/l3-dispatcher.spec.md` 的 `## Inner contracts` 表登记该叶。
  - 修订 `l3-core-boundary.spec.md#L26-L27` B1：把 `skills/*` 收窄为
    `skills/<family>/*`，显式允许 `skills/api.py`；移除 `tools/scene_nav`
    这类不存在的路径引用。
  - 修订 `l3-skill-contract.spec.md#L10` 的过期路径引用。
  - 修订 `l3-execution-seam.spec.md` §1 表与 §4 的路径引用（`execution/skill_host`、`FlightPorts` 归属）。
- 行为不变式：不动任何代码。
- 验收：新叶契约 `Status: proposed`；父契约 `## Inner contracts` 含该叶；被引用的路径在仓内可解析。
- 回退：`git checkout -- specs/`。

### P1 — 目录搬迁（纯 rename，零行为变更）

- 范围：按 §5 映射表 `git mv` 全部文件；新建 `toolplane/`、`skills/`、`support/`；
  删除 `tools/`、`utils/`、`services/`；`execution/ports.py` 拆分自 `tools/flight/ports.py`。
- 行为不变式：模块内类名/函数名/常量/字符串字面量不变；仅文件位置与 import 路径变。
- 验收：`grep -rn "dispatcher\.\(tools\|utils\|services\)\." l3-dispatcher-planner/` 零命中；
  `python -m compileall` 通过；`python -c "import dispatcher.engine"`（环境允许时）。
- 回退：单提交 `git revert`。

### P2 — 命名去歧义与 `__init__` 规范

- 范围：`ToolExecutor`→`ToolIntake`、`execute`→`start`（`toolplane/intake.py`）；
  `execution/waypoint_execution.py`→`execution/waypoint.py`；
  `utils/zenoh_rpc.py`→`toolplane/zenoh_transport.py`；
  按 §4.5 改写四个 `__init__.py`。
- 行为不变式：除符号名与 docstring 外零变化；`__all__` 内容与改名后符号一致。
- 验收：`grep -rn "ToolExecutor\|waypoint_execution\|zenoh_rpc" l3-dispatcher-planner/` 零命中。
- 回退：单提交 `git revert`。

### P3 — 归属归位与删除清单落地

- 范围：§6 删除项全部执行；`skills/flight/{motion,session}.py` 生效；
  `execution/ports.py` 生效；依赖方向按 §4.3 自检。
- 行为不变式：不改任何字符串契约（§3 Non-Goals）。
- 验收：§4.3 分层表逐行 grep 自检（如 `core/` 不 import `skills/` 家族与 `execution/`）。
- 回退：单提交 `git revert`。

### P4 — 文档与台账同步

- 范围：`doc/l3-dispatcher-planner/rest/README.md` 与
  `dispatcher-deferred-dependencies.md` 的路径引用；
  `doc/rest/task-id-to-tool-name-deferred.md` 的路径引用；
  `AGENTS.md` 的「编码风格与命名」归属表述（**需用户明确许可**，该文件不在默认目标树内）。
- 行为不变式：只改路径与归属表述，不改保留项状态。
- 验收：`grep -rn "dispatcher/\(tools\|utils\|services\)/" doc/ AGENTS.md` 零命中或已显式登记。
- 回退：`git checkout -- doc/ AGENTS.md`。

## 8. 验收标准

> **统一声明**：除非使用者明确许可，否则跳过验收测试工作（`AGENTS.md` 硬性约束 §9）。

- [ ] `grep -rn "dispatcher\.\(tools\|utils\|services\)\." l3-dispatcher-planner/` 零命中
- [ ] `ls ros_packages/dispatcher/dispatcher/` 恰为 `core toolplane skills execution ros_adapter perception support engine.py __init__.py`
- [ ] `grep -rn "ToolExecutor\|waypoint_execution\|zenoh_rpc\|flight_motion\|flight_session\|skill_api" l3-dispatcher-planner/` 零命中
- [ ] 分层门禁：`core/` 不 import `skills/<family>`、`execution/`、`toolplane/`；`toolplane/` 不 import `core/`、`execution/`
- [ ] 每个子包 `__init__.py` 有区分性 docstring
- [ ] 行为契约字节级一致：topic 名、param 名、消息字段名、RPC 方法名、工具 wire 名、slog 事件名、状态 reason 字符串零变化
- [ ] 新叶契约 `l3-package-layout.spec.md` 存在且被父契约 `## Inner contracts` 收录
- [ ] `python -m compileall ros_packages/dispatcher` 通过

## 9. 风险与对策

| 风险 | 影响 | 对策 |
|------|------|------|
| 搬迁遗漏 import 点 | 运行期 `ModuleNotFoundError` | 双模式 grep（`dispatcher.tools` + `tools/`）全覆盖；`compileall` 自检 |
| `core/` 因 `skills/api.py` 而违反 B1 字面表述 | 契约门禁判负 | P0 先把 B1 收窄并显式允许 `skills/api.py`，再动代码 |
| 移动 `ports.py` 误伤 VLA 与 ros_adapter | 端口类型解析失败 | `execution/ports.py` 只承接共享动作端口；`FlightHost` 按 §4.4 删除；VLA 侧 `skills/vla/ports.py` 原地不动 |
| `tests/` import 未同步 | 测试收集失败 | P1 同一改动内同步 tests 的 import 路径（不运行测试，按 §8 声明） |
| `find_packages()` 对新增/删除子包的行为 | 打包缺包 | `setup.py` 用 `find_packages()` 自动发现；确认新子包均有 `__init__.py` |
| 一次性大改难以评审 | 回滚成本高 | 按 P1/P2/P3 分提交，每期可独立 revert |
| `AGENTS.md` 归属表述未同步 | 文档与契约冲突 | P4 单列，需用户明确许可后再改（AGENTS 不在默认目标树内） |

## 10. 修改点清单汇总

| 文件 | 动作 | 说明 |
|------|------|------|
| `specs/implemented/inner/l3-package-layout.spec.md` | 新增 | P0：目录与命名权威 |
| `specs/implemented/l3-dispatcher.spec.md` | edit | P0：登记新叶契约 |
| `specs/implemented/inner/l3-core-boundary.spec.md` | edit | P0：B1 收窄 + 清理不存在路径 |
| `specs/implemented/inner/l3-skill-contract.spec.md` | edit | P0：修正 `skill_api.py` 路径 |
| `specs/implemented/inner/l3-execution-seam.spec.md` | edit | P0：路径引用与端口归属 |
| `dispatcher/tools/**` → `toolplane/**` + `skills/**` | rename/split | P1/P2/P3 |
| `dispatcher/utils/**` → `toolplane/**` + `support/**` | rename | P1 |
| `dispatcher/services/**` → `skills/flight/**` | rename | P1 |
| `dispatcher/execution/waypoint_execution.py` → `waypoint.py` | rename | P2 |
| `dispatcher/execution/ports.py` | 新增 | P1：拆分自 `tools/flight/ports.py` |
| `dispatcher/__init__.py`、四个子包 `__init__.py` | edit | P2：职责 docstring |
| `tests/**/*.py` | edit | P1：import 路径同步 |
| `doc/l3-dispatcher-planner/rest/{README,dispatcher-deferred-dependencies}.md` | edit | P4：路径引用 |
| `doc/rest/task-id-to-tool-name-deferred.md` | edit | P4：路径引用 |
| `AGENTS.md` | edit（待许可） | P4：命名归属表述 |

## 11. 执行记录（2026-09-19）

> 本节登记实际执行、与方案的偏差及验收实测；测试执行按 §8 统一声明跳过。

### P0 契约先行

- 新增 `specs/implemented/inner/l3-package-layout.spec.md`（先落 `specs/proposed/inner/`，代码同步完成后按 `specs/README` 生命周期规则晋级 `implemented` 并随空解散 `proposed/` 目录）。
- `l3-dispatcher.spec.md`：Inner contracts 表登记新叶；边界条目拆分为「C++ 编码风格归 `l3-coding-style`；dispatcher Python 子包目录与命名归 `package-layout`」。
- `l3-core-boundary.spec.md` B1 收窄：禁 `skills/<family>/*`，显式豁免 `skills/api.py`；移除不存在的 `tools/scene_nav` 引用。
- `l3-skill-contract.spec.md`：参考实现路径改为 `dispatcher/dispatcher/skills/api.py`；§9 改写——`FlightHost` 不再单独保留 Protocol 声明，端口成员集仍由该节定义，`FlightPorts` 归属 `execution/ports.py`。
- `l3-execution-seam.spec.md` §4：登记通用动作端口定义位置 `dispatcher/dispatcher/execution/ports.py`。

### P1 目录搬迁（git mv，rename 检测保留）

- §5 映射表全量执行；`services/__init__.py` 删除，`tools/`、`utils/`、`services/` 目录解散（连同未跟踪 `__pycache__`）。
- 实测子包集合：`core engine.py execution perception ros_adapter skills support toolplane`（+ `__init__.py`）。

### P2 命名去歧义

- `ToolExecutor`→`ToolIntake`（`toolplane/intake.py`），方法 `execute`→`start`；`control_plane` 属性 `_executor`→`_intake`。
- `waypoint_execution.py`→`execution/waypoint.py`；`zenoh_rpc.py`→`toolplane/zenoh_transport.py`。
- `__init__` 自述重写：`dispatcher/`、`toolplane/`、`skills/`、`support/`、`execution/`、`skills/flight/`。
- **登记的有意变更**：日志标签 `[zenoh_rpc]`→`[zenoh_transport]`（8 处 print/log 前缀；不属于 topic/param/消息字段/RPC 方法/wire 名/slog 事件名/reason 字符串保护清单）。
- `ToolRegistry.default()` 的家族 catalog import 同步为 `skills.*`。

### P3 归属归位与删除

- `FlightHost(Protocol)` 删除（原 `tools/flight/ports.py#L73-L85`，全仓零引用）；`l3-skill-contract.spec.md` §9 同一改动内改写。
- `skills/flight/{motion,session}.py`、`execution/ports.py` 生效。
- `package-layout` §3 增补 `ToolRegistry.default()` 装配例外（生产集合构造口，`l3-tool-plane` §1 权威）。
- 测试侧 `test_core_boundary.py` core 闭包禁列更新为新平面词汇（`dispatcher.skills.flight`、`dispatcher.skills.vla`、`dispatcher.execution`、`dispatcher.toolplane`），模块 stub 键同步。

### P4 文档与台账同步

- `doc/rest/task-id-to-tool-name-deferred.md`（rpc_plane 路径）、`doc/l3-dispatcher-planner/rest/dispatcher-deferred-dependencies.md`（R04 session 路径）已同步；`rest/README.md` 复核无旧路径引用。
- **例外登记（不改写）**：`doc/**/iteration/` 各历史方案与 `specs/implemented/architecture/` 决策记录属冻结过程材料，其中的旧路径引用保留为历史事实，不回填。
- **遗留**：`AGENTS.md`「编码风格与命名（归 `development-workflow/l3-coding-style`）」表述需拆分为 C++/Python 两处归属；该文件不在默认目标树内，待用户明确点名许可后另行修改。

### 验收实测（2026-09-19，静态）

- `grep -rn --include='*.py' 'dispatcher\.(tools|utils|services)' l3-dispatcher-planner/` → **零命中**（G32）。
- 旧符号（`ToolExecutor`/`waypoint_execution`/`zenoh_rpc`/`flight_motion`/`flight_session`/`skill_api`/独立 `FlightHost`）零命中；`flight_session_id` 为 RPC wire 字段、`DispatcherFlightHost` 为现行类名，均不在清理范围。
- `python -m compileall ros_packages/dispatcher` → 通过。
- P4 三份文档与 `specs/implemented/` 旧路径复核 → 零命中。
- pytest 未运行（`AGENTS.md` 硬性约束 §9）。

## 12. 修正轮（2026-09-19，用户裁决）

> 用户指出：`tools` 是开发组协定的技能层目录名，本方案将其改为
> `skills/` 违反协定；并裁决调用面基础设施目录定名 `rpc/`。本节修订
> §4/§5 的目标形态，§11 记录的中间状态以此为准被取代。

### 裁决与依据

| 项 | 原方案 | 修正后 | 依据 |
|----|--------|--------|------|
| 技能层目录名 | `skills/` | **`tools/`（协定名，长期有效）** | 用户：开发组协定 |
| `skills/api.py` | — | **`tools/skill_api.py`（恢复原文件名）** | 同上 |
| 调用面目录名 | `toolplane/` | **`rpc/`** | 用户裁决（与 `l3-l4-rpc` 契约对齐，避免与 `tools` 词根并存） |
| 退役前缀集合 | `utils/services/tools` | **`utils/services/toolplane/skills`**（`tools` 移出退役清单） | 同上 |

### 执行内容

- `git mv skills tools`、`tools/api.py → tools/skill_api.py`、`git mv toolplane rpc`。
- 44 个 `.py` 批量替换（import、注释路径、模块名字符串）；`tools/__init__.py`、`rpc/__init__.py`、`support/__init__.py` 自述重写。
- 契约同步：`l3-package-layout` 全文重写（§1 平面表、§3 依赖方向、§5 退役前缀、G29/G32）；`l3-core-boundary` B1 改回 `tools/<family>/*` + `tools/skill_api.py` 豁免；`l3-skill-contract` 参考实现路径改回 `dispatcher/dispatcher/tools/skill_api.py`。
- 台账同步：`task-id-to-tool-name-deferred.md`（rpc_plane 路径）、`dispatcher-deferred-dependencies.md`（R04 session 路径）。
- 测试侧 `test_core_boundary.py` core 闭包禁列更新为 `dispatcher.tools.flight / dispatcher.tools.vla / dispatcher.execution / dispatcher.rpc`。

### 修正后静态验收实测（2026-09-19）

- 子包集合：`core engine.py execution perception ros_adapter rpc support tools`（+ `__init__.py`）。
- `dispatcher.(toolplane|skills|utils|services)` 在 `*.py` 全树零命中；`toolplane`/`dispatcher.skills` 字符零残留。
- `specs/implemented/` 除 `l3-package-layout` §5/G29 的退役前缀声明本身外零残留。
- `python -m compileall ros_packages/dispatcher` 通过；pytest 仍未运行（`AGENTS.md` §9）。

### 最终目录树（取代 §4.1）

```
dispatcher/
  engine.py  core/  rpc/  tools/  execution/  ros_adapter/  perception/  support/
  rpc/   = model protocol registry runtime intake connection_lease zenoh_transport rpc_plane control_plane
  tools/ = skill_api.py + flight/{catalog,motion,session,六技能} + vla/{catalog,ports,vla_geometry,vla_skill}
```

## 13. 修正轮二（2026-09-19，用户裁决）

> 用户指出 `rpc` 名不副实（9 个文件仅 4 个是 RPC 语义，且与契约术语
> `l3-tool-plane` 无对应），并提出「同词根 + 定语限制」的命名策略。
> 裁决结果：调用面定名 **`tool_plane/`**，`tools/` 保持协定名不动。

### 裁决与依据

| 项 | §12 状态 | 修正后 | 依据 |
|----|---------|--------|------|
| 调用面目录名 | `rpc/` | **`tool_plane/`** | 用户裁决；与权威叶契约 `l3-tool-plane` 术语 1:1 |
| `rpc_plane.py`（类 `RpcPlane`） | — | **`methods.py`（类 `RpcMethods`）** | 消目录名与模块名重复；其内容是 RPC 方法面 |
| 测试文件 | `test_rpc_plane.py` | **`test_methods.py`** | 随被测模块同步 |
| 命名规范 | 同词根纪律：不得同词根 | **同词根允许，中心词必须不同** | 用户「词根类似 + 定语限制」策略；`tools/`（本体）与 `tool_plane/`（面）合法 |
| 退役前缀集合 | +`toolplane`/`skills` | **+`rpc`**（`tools` 长期有效） | 同上 |

未采纳的候选：`agent_tools/`（`agent` 在本仓库已有「编码 agent」与「copaw agent」两个指代，会引入第三种歧义，且 `tools` 为协定名）；`tool_rpc/`（自解释但契约无对应术语）。

### 执行内容

- `git mv rpc tool_plane`、`tool_plane/rpc_plane.py → methods.py`、`tests/.../test_rpc_plane.py → test_methods.py`。
- 31 个 `.py` 批量替换：`dispatcher.rpc` → `dispatcher.tool_plane`、`RpcPlane` → `RpcMethods`、`rpc_plane` → `methods`。
- `tool_plane/__init__.py` 自述重写：给出可独立判读的**一行定义**（连接租约 → 传输 → 协议 → 发现 → 准入/事件/取消 → 技能工作流），并写明与 `tools/`（工具本体）的分工。
- 契约重写：`l3-package-layout` §1 平面表（`tool_plane` 一行定义 + `tools`/`tool_plane` 分工）、§2 同词根纪律（改为中心词判据）、§3 依赖方向、§4 要求平面自述含一行定义、§5 退役前缀、G29/G31/G32。
- 台账同步：`task-id-to-tool-name-deferred.md`（`tool_plane/methods.py`）、`dispatcher-deferred-dependencies.md`（`test_methods.py`）。

### 修正后静态验收实测（2026-09-19）

- 子包集合：`core engine.py execution perception ros_adapter support tool_plane tools`（+ `__init__.py`）。
- `dispatcher.(toolplane|skills|rpc|utils|services)` 在 `*.py` 全树零命中；`RpcPlane`/`rpc_plane`/`ToolExecutor`/`waypoint_execution`/`zenoh_rpc` 零命中。
- `specs/implemented/` 与 rest 台账除 `package-layout` §5/G29 的退役前缀声明本身外零残留。
- `python -m compileall ros_packages/dispatcher` 通过；pytest 仍未运行（`AGENTS.md` §9）。

### 最终目录树（取代 §4.1、§12 末节）

```
dispatcher/
  engine.py  core/  tool_plane/  tools/  execution/  ros_adapter/  perception/  support/
  tool_plane/ = model protocol registry runtime intake connection_lease zenoh_transport methods control_plane
  tools/      = skill_api.py + flight/{catalog,motion,session,六技能} + vla/{catalog,ports,vla_geometry,vla_skill}
```

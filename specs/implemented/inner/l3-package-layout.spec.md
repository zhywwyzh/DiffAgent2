# dispatcher 目录架构与命名

Status: implemented

Contract-ID: l3-dispatcher/package-layout

Parent: specs/implemented/l3-dispatcher.spec.md

> 定义 dispatcher Python 子包的平面划分、命名规范、依赖方向与
> `__init__` 自述规范。本契约只约束目录与命名形态；各平面的行为契约
> 归各自叶契约。C++ 编码规范归 `development-workflow/l3-coding-style`，
> 与本契约互不重叠。

## 1. 平面划分

> 子包与 l3 职责词汇一对一；不设 `utils`/`services` 等无归属目录。
> `tools` 是开发组协定的技能层目录名，长期有效，不得改名。

| 子包 | 职责（一行定义） | 行为契约 |
|------|------------------|----------|
| `core/` | 六态 FSM 与任务队列 | `l3-dispatcher/core-boundary` |
| `tool_plane/` | 工具面：承接 l4 工具调用的传输、协议、工具发现、调用准入、事件、取消与连接租约，及服务栈线程装配 | `l3-dispatcher/tool-plane`、`l3-dispatcher/l4-rpc` |
| `tools/` | 工具本体：技能协议（`skill_api.py`）与家族实现（`flight/`、`vla/`、`scene_nav/`） | `l3-dispatcher/skill-contract` |
| `execution/` | 共享动作端口、家族宿主与装配 | `l3-dispatcher/execution-seam` |
| `ros_adapter/` | ROS 收发 | `l3-dispatcher/ros-adapter-boundary` |
| `perception/` | 共享感知数据面：原始数据投影与几何换算；技能经端口只读 | `l3-dispatcher/scenegraph` |
| `support/` | 系统支撑：状态枚举、配置、结构化日志 | — |

- `engine.py` 与 `dispatcher_node.py` 是装配根，位于包顶层。
- `execution/ports.py` 承载跨家族共享的动作意图、状态、进度与配置；
  家族专属宿主端口留在各自家族目录。
- **`tools/` 与 `tool_plane/` 的分工**：前者是工具**本体**（技能实现），
  后者是承接这些工具调用的**面**（传输/协议/准入/租约）；`tool_plane/`
  不含技能实现，`tools/` 不含调用面基础设施。

## 2. 命名规范

| 类型 | 规范 | 示例 |
|------|------|------|
| 子包（平面） | 契约术语的单一英文名；禁 `utils`/`helpers`/`misc`/`common` 泛名；`tools` 为开发组协定名例外保留 | `tool_plane/`、`support/` |
| 模块（家族内） | 家族前缀，`__init__` 除外 | `tools/vla/vla_geometry.py` |
| 模块（家族基础设施） | 领域名词，不带家族前缀（目录已表达家族） | `tools/<family>/catalog.py`、`tools/<family>/ports.py` |
| 模块（家族执行） | 家族前缀（两家族同名实现，靠前缀区分） | `tools/flight/flight_waypoint.py`、`tools/vla/vla_waypoint.py` |
| 模块（平面基础设施） | 领域名词，不带平面前缀（目录已表达平面） | `tool_plane/registry.py` |
| 模块（执行缝） | 语义名词，不重复平面前缀 | `execution/ports.py` |
| 类 | PascalCase 领域名词；类名不重复所在平面目录名；家族执行实现带家族前缀 | `ToolIntake`、`FlightWaypointExecution`/`VlaWaypointExecution` |
| 函数/方法 | snake_case 动词开头 | `start_tool_workflow` |
| 私有成员 | 单下划线前缀 | `_active_call_id` |
| 常量 | UPPER_SNAKE_CASE | `DISPATCHER_STATE` |
| 同词根纪律 | **同词根允许，但中心词必须不同**；中心词相同的两个实体不得分处不同平面 | `tools/`（工具**本体**）与 `tool_plane/`（工具**面**）：词根同、中心词不同，合法；`execution/`（平面）与 `executor`（入口）中心词相同，非法 |
| 配置参数前缀 | **家族/平面名**，与所在目录同名；键名不重复前缀；子组用嵌套而非平级连写 | `~flight/*`、`~vla/*`、`~scene_nav/replan/*`（非 `~scene_nav_replan/*`） |

配置参数命名规则（违反即缺陷）：

- 参数键形如 `~<前缀>/<子组?>/<键名>`；**前缀 = 消费它的家族/平面目录名**，使归属可独立判读。
- 仅当参数被**多个家族**消费时，才使用流程名或包顶层键；顶层键限于
  `drone_id`、`odometry_topic`、`headless`、`config_path`、`log_dir`、`telemetry/*` 一类。
  例外：执行缝的跨家族共享配置沿用其主家族前缀（如 `~flight/*` 由飞行与 VLA 共用），
  但须在执行缝契约中声明共享范围与唯一权威，不得由各家族各自再存一份。
- 键名**不重复前缀**（`~scene_nav/json_wait_timeout_s`，不是 `~scene_nav/scene_nav_json_wait_timeout_s`）。
- 键名**带单位后缀**（参数名是 `development-workflow/l3-coding-style` §1.4 的显式例外）：
  时间 `_s`、长度 `_m`、角度 `_deg`、角速率 `_rad_s`；无量纲计数/开关不加后缀。
  缩写一律写全（`threshold` 不写 `thresh`，`distance` 不写 `dis`）。
- 每组参数须有**唯一权威**声明；同义参数不得在家族与 `perception/` 等处各存一份。
- 参数名是行为契约（`development-workflow/l3-coding-style` §6、
  `l3-dispatcher/ros-adapter-boundary` R6）：改名须登记为有意变更并给出兼容处置。
- 参数装载不得经白名单静默丢弃：缺失或未声明即显式失败或留痕，不得「存在但读不到」。

## 3. 依赖方向

| 平面 | 允许 import | 禁止 import |
|------|------------|------------|
| 装配根（`engine.py`、`dispatcher_node.py`、`execution/composition.py`） | 全部平面 | — |
| `core/` | `core/`、`support/`、`tools/skill_api.py` | `tools/<family>/`、`execution/`、`tool_plane/`、`ros_adapter/` |
| `tool_plane/` | `tool_plane/`、`support/` | `core/`、`execution/`、`tools/` |
| `tools/<family>/` | 本家族、`tools/skill_api.py`、`execution/ports.py` | `core/`、`tool_plane/`、其他家族 |
| `execution/`（除 composition） | `execution/`、`support/`、`tools/skill_api.py`、`tools/<family>/ports.py`（仅宿主端口）、`perception/`（仅 `skill_host.py` 读感知数据面） | `core/`、`tool_plane/`、家族技能实现 |
| `ros_adapter/` | `execution/ports.py`、`support/`、`perception/`（仅写感知数据面）、ROS 消息包 | 领域逻辑 |
| `perception/` | `perception/`、`support/` | 技能与执行缝 |

- core 允许 `tools/skill_api.py` 仅因其承载技能协议与四裁决词汇，是
  `l3-dispatcher/core-boundary` B1 的显式豁免。
- execution 允许家族端口模块仅因 `execution/skill_host.py` 实现各家族
  宿主端口；家族技能实现模块不得进入 execution。
- `execution/composition.py` 是装配根，允许引入各家族执行实现
  （`tools/<family>/<family>_waypoint.py`）；家族执行实现 import
  `execution/ports.py` 取共享动作端口。
- 感知数据面经 `perception/` 单向流动：`ros_adapter/` 是唯一写入方，
  `execution/skill_host.py` 是唯一读取方（再经端口交给技能）。技能不直接
  import `perception/`，`perception/` 不 import 任何平面，读写均遵守
  `l3-dispatcher/ros-adapter-boundary` §3 的共享状态规则（S1/S2/S3）。
- `tool_plane/registry.py::ToolRegistry.default()` 是生产工具集合的装配
  便捷入口（`l3-dispatcher/tool-plane` §1 的七项目标集合），允许 import
  家族 catalog（`tools/<family>/catalog.py`）；除此之外 tool_plane 不
  import 技能家族。

## 4. `__init__` 自述规范

- 每个子包 `__init__.py` 必须有 docstring 声明本平面职责与契约归属；
  禁止两个子包共用同一条泛描述。
- 平面自述必须包含**一行定义**，使目录名与内容可被独立判读。
- 导出面用 `__all__` 显式声明；`tools/__init__.py` 不导出家族，
  避免技能被隐式 import。

## 5. 旧路径处置

`dispatcher.utils.*`、`dispatcher.services.*`、`dispatcher.toolplane.*`、
`dispatcher.skills.*`、`dispatcher.rpc.*` 为退役前缀，不得以转发模块、
`__getattr__` 或别名形式回流；`dispatcher.tools.*` 为开发组协定的技能层
前缀，长期有效。

## 6. 门禁

| 门禁 | 检查 |
|------|------|
| G29 | `dispatcher/` 子包集合恰为 §1 七平面；不存在 `utils/`、`services/`、`toolplane/`、`skills/`、`rpc/` 目录 |
| G30 | §3 依赖方向表的禁列在 import 闭包中零命中（装配根与 §3 显式例外除外） |
| G31 | 每个子包 `__init__.py` 有区分性 docstring 与一行定义 |
| G32 | 退役模块前缀（§5）在全仓 Python 零命中 |

> `specs/tools/*` 门禁引擎迁移前，以等价 grep 与既有 pytest 承担判定。

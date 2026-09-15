# l3 dispatcher 架构稳定总纲 方案

> 摘要：先把当前架构「扶正」，再做增量。本总纲给出**唯一的目标拓扑、一层依赖矩阵、
> 命名规范、契约不变量与门禁、分期路线图**，并把两份未执行的 `proposed` 方案
> （`design-dispatcher-package-topology.md`、`design-dispatcher-engine-relocate-non-core.md`）
> 收敛为同一目标树下的执行版。原则：先做**零行为改写**的归位期，再做**契约对齐**期；
> 每期独立可回退、独立验收；不新增转接器、不留注释桩、不为「以后可能用」造空实现。
>
> 本总纲是**约束与索引**：不重复子方案的逐条证据与逐行手术清单，事实归各子方案。

## 0. 元信息

| 项 | 值 |
|----|----|
| 日期 | 2026-09-12 |
| 目标路径 | 代码：`l3-dispatcher-planner/ros_packages/dispatcher/`；契约：`specs/`（仅 S1，执行前需显式放行）；文档：`doc/l3-dispatcher-planner/iteration/`、`AGENTS.md`、`.trae/skills/`（仅 S0） |
| 状态 | proposed（待确认后按 S0 → S6 顺序执行） |
| 关联文档 | 模板：`doc/l3-dispatcher-planner/iteration/_TEMPLATE.md`；子方案见 §4.8；既有前序轮次：`design-dispatcher-core-inference-migration.md`（done）、`design-dispatcher-engine-narrow-core-trim.md`（done）、`design-dispatcher-zenoh-transport-migration.md`（done） |
| 契约依据 | `specs/implemented/l3-dispatcher.spec.md` 及其 5 个叶契约、`specs/implemented/topology.spec.md`+`entity-naming`、`specs/implemented/development-workflow.spec.md`+`l3-coding-style`、`specs/README.md` |
| 路径约定 | 本文档一律用**相对路径**（`l3-dispatcher-planner/…`、`specs/…`）；不写主机绝对路径与个人标识（S0 要建立同一纪律） |

## 1. 背景与动机

用户要求：**先把当前架构处理好（稳定）**，随后按文档执行优化。据此先做了一轮契约—代码一致性审计，结论是两条：

1. **契约层基本自洽、方向正确**；目录/命名/spec 注册表规则大体合规。
2. **代码层是「迁移中途态」**，存在 6 项与 `implemented` 契约的硬冲突（§2.A），
   而现有 6 份轮次方案**只做位置迁移、零行为改写**，没有一项覆盖它们。

同时，两份未执行的 `proposed` 方案在**目标拓扑上互相冲突**（§2.B2），
若按任意一份先执行，后续必然二次搬迁。因此需要一份**总纲先钉死目标形态**。

用户本轮三项裁决：

| 裁决项 | 结果 |
|---|---|
| 交付形态 | 总纲 + 分期子方案 |
| 覆盖范围 | 包拓扑归位 + engine 非 core 职责迁出 + 契约对齐 + 隐私门禁清理（全选） |
| 契约边界 | **契约优先**：契约正确、实现未跟上 → 修实现；仅在契约自相矛盾处先出契约修订 |

## 2. 现状事实（问题清单）

> 相对路径；`PKG = l3-dispatcher-planner/ros_packages/dispatcher/`。逐条已核。
> 细证与逐行清单归各子方案（§4.8），本节只列判定所需的锚点。

### 2.A 与契约的硬冲突（S1/S4/S5/S6 的对象）

- [ ] `PKG/dispatcher/tools/model.py#L31`、`#L82`、`PKG/dispatcher/tools/registry.py#L244-L246`、`#L273-L287`、`#L300-L307`、`PKG/dispatcher/tools/runtime.py#L136-L141`、`#L413` — **任务编号全链路残留**：`ToolCall.task_id` / `ToolSpec.task_id` / `_by_task_id` / `tool_for_task_id` / 强制 `task_id == spec.task_id` / `_meta["lx.task_id"]` / ack 与事件带 `task_id`。
  违反 `l3-core-boundary` B2/B7/B8（G5）与 `l3-migration-protocol` §4「禁止引入中间表示」（G23）。
- [ ] `PKG/dispatcher/engine.py#L186`、`#L437`、`#L443`、`#L509` — core 侧回读并向下传 `current_task_id` / `task_id=` / `task_ids=[…]`，与 `design-dispatcher-taskid-retirement-deps-migration.md` 已执行的退役方向相反。
- [ ] `PKG/dispatcher/rpc_plane.py#L20`、`#L347`、`#L387` — 代码显示 `task_id` 由 **l3 本地**按工具名从注册表解析并注入内部准入 payload（`"task_id": spec.task_id`）。**取证（旧库 l4-agent 源码 + `agent-station-tools.spec.md#L25`「task ids never appear on the wire」）：wire 从不携带该字段**——它不是上游协议字段，而是 l3 内部编号 → B7 的「入口丢弃」条款不触发，处置为**删除本地派生**（见 S5；无适配层兼容动作）。
- [ ] `PKG/dispatcher/engine.py#L23-L24`、`#L208-L224`、`#L806`、`PKG/dispatcher/config.py#L15`、`PKG/dispatcher/tools/control_plane.py#L45`、`#L75`、`PKG/dispatcher/perception/base_policy.py#L18`、`#L26`、`#L451`、`#L513`、`PKG/dispatcher/perception/pointcloud_accumulator.py#L122-L125` — **ROS 收发未隔离**：领域/核心/配置/装配/感知文件直接 `import rospy`、`from *_msgs`（`base_policy.py#L26` 为 `geometry_msgs.msg`）、构造 Publisher/Subscriber、`rospy.Rate`。
  违反 `l3-ros-adapter-boundary` R1/R2/R4（G7/G8）；Python 侧**零** `*_ros.py` 适配文件。
- [ ] `specs/implemented/inner/l3-core-boundary.spec.md#L31-L32`（B3 允许 core 持有四类发布器） vs `specs/implemented/inner/l3-ros-adapter-boundary.spec.md#L27-L39`（R1/R4 领域层出现 Publisher 即缺陷） — **两条叶契约自相矛盾**，需在 S1 裁决后才可判定代码。
- [ ] `PKG/dispatcher/engine.py#L562-L573`、`#L410-L419` — 分发未命中技能时走 `_advance_to_next_prompt()`，队尽即上报 `done`，**无 fail 相位**。违反 B5（G3）、`l3-migration-protocol` §4「禁止假成功」（G22）。
- [ ] `PKG/dispatcher/engine.py#L197`（`self._skills: dict = {}`）与全仓无任何技能实现（无 `tools/vla|flight|scene_nav|grasp`）— `l3-skill-contract` §1「技能是 l3 唯一任务能力形态」当前无落点；§7 的 11 个宿主端口在宿主上**全部缺失**（仅存在于契约工件 `skill_api.py`）。

### 2.B 拓扑与职责问题（S2/S3 的对象）

- [ ] `PKG/dispatcher/` 包根 8 个 `.py` + `tools/` + `perception/` 混居，**无 `utils/`**；`tools/control_plane.py#L9`（tools → 支撑面）与 `zenoh_rpc.py#L25-L28`、`connection_lease.py#L19-L20`、`rpc_plane.py#L36-L38`（支撑面 → tools）构成**双向耦合**。
- [ ] **两份 proposed 目标拓扑冲突**：`design-dispatcher-package-topology.md` §4.2 将 `state/config/slog/connection_lease/zenoh_rpc/rpc_plane` 收进 `utils/`、`skill_api.py` 进 `tools/`、`control_plane.py` 移出 `tools/`；`design-dispatcher-engine-relocate-non-core.md` §4 目标树把这些模块留在包根、把新协作模块（`telemetry/task_phase/skill_router/actuators/tools/workflow`）挂在包根、`control_plane.py` 留在 `tools/`。二者不可同时执行。
- [ ] `design-dispatcher-engine-relocate-non-core.md` 的证据基线是 **1055 行版** engine，现值 **1067 行**（`design-dispatcher-package-topology.md` §2.6 已勘误）；该子方案的迁移映射行号已过期，需按实测重锚。
- [ ] `PKG/dispatcher/engine.py#L494`（`_decision_chain_not_ready_reason` 零定义）、`PKG/dispatcher/rpc_plane.py#L122-L126`（`tools.scene_nav.graph_source` 悬空引用）— 既有孤儿/悬空引用，非本轮引入，须登记处置而不臆造实现。

### 2.C 文档、门禁与注册表问题（S0/S1 的对象）

- [x] `AGENTS.md`（9 处）、`doc/l3-dispatcher-planner/iteration/*.md`（42 处）、`.trae/skills/github-{issue,pull}/SKILL.md`（15 处）— 共 **66 处个人用户名/主机绝对路径**进入纳入版本控制的文档。
  违反 `AGENTS.md` 硬性约束 1/2 与 `topology` 不变量（「任何个人或机器特定的具体主机值都不进入纳入版本控制的文档」）。（S0 已清理：49 处主机绝对路径已替换为 `<new-repo-root>` / `<old-repo-root>`，17 处公开服务标识保留；勘误与实测见 S0 方案附录。）
- [ ] `specs/README.md#L11-L24` 声明的 `implemented/architecture/`、`implemented/process/`、`proposed/`、`rejected/`、`archived/`、`tools/` 均不存在；各轮方案全部落在 `doc/` 下，与 `l3-migration-protocol` §7「方案归档为决策记录」的落点（`specs/implemented/architecture/`）**未接线**。
- [ ] `specs/implemented/inner/l3-core-boundary.spec.md#L60` 的 G2 第二子句「core 的 `def` 数不超过**约定阈值**」无数值 — 门禁不可判。
- [ ] `AGENTS.md` 硬性约束 1 的措辞（「个人用户名……绝不进入」）与 `github-issue`/`github-pull` 必须写入的公开仓库地址（`zhywwyzh/DiffAgent2`）冲突：约束本意应是**主机本地凭据与机器特定值**，公开服务标识不在其列。措辞需在 S1 收敛。

## 3. 目标与约束

- **「稳定」的定义（三条同时成立才叫稳定）**：
  1. **单一目标树**：任何模块都有唯一归属平面，不存在两套并行的目标形态；
  2. **单一依赖方向**：包内依赖构成有向无环图，方向由 §4.2 矩阵唯一规定，可 grep 判定；
  3. **契约与代码一致**：`implemented` 契约的每条禁令/门禁都能在当前代码上判绿，未完成项必须在方案或 issue 中显式登记（不允许静默漂移）。
- **目标**：
  1. 钉死目标拓扑、依赖矩阵与命名规范（§4.1–§4.3）；
  2. 把两份冲突的 `proposed` 收敛为同一目标树下的执行版（S2、S3）；
  3. 让契约—代码一致（S1 改契约中自相矛盾处 → S4/S5/S6 修实现）；
  4. 建立可执行门禁（§4.4、§8）与隐私门禁（S0）；
  5. 每期给出：现状证据、决策、映射表、删除清单、分期、验收、风险、修改点清单。
- **Non-Goals**：
  - **不含旧库迁移**：本套**不执行** DiffAgent2 旧版 → 新版的任何代码迁移。技能族（`tools/vla|scene_nav|flight|grasp`）、`recording` / `vlm_facade`、任务注入轮次（`_start_prompt_task` / `arm_action` / `forward_*_tool`）等一律**排除**；它们何时迁、按什么形态迁，由**迁移轮次**依 `l3-migration-protocol` + 本套钉死的目标树另行设计。本套中所有「迁入/迁出」字样均指**新库仓库内**的文件位置迁移。旧版仅作为**历史事实被引用**（已 `done` 的方案记录与勘误），不产生行动项。
  - 不改 FSM 语义（状态集合、转移、四裁决落地）；
  - 不实现技能族、不补齐 `SkillHost` 端口；
  - 不改对外协议：slog 事件名/键集、zenoh topic/queryable/presence token、ROS topic/param/消息字段名、`list_tools()` 的 `revision`、`SkillHost` 端口签名；
  - 不引入新的构建/部署/容器编排；
  - 不修复与本期无关的算法问题（感知/规划算法内部逻辑）。
- **硬边界**：
  - **禁止转接器**：新旧接口不统一时重新设计接口，不得新设适配层桥接；位置迁移 + import 改写不算转接，新增「只做转换、不承载语义」的层算。
  - **过期必删（no legacy shim）**：被替代的旧路径/旧定义/旧注释**直接删除**，不留别名、不留注释桩、不留空实现。
  - **不投机设计**：没有调用方或消费者的端口/模块不预造（`l3-migration-protocol` §1「不留桩」）。
  - **契约优先、门禁绿**：`specs/` > 本目录文档；冲突先修契约再改码（`l3-migration-protocol` §5）。
  - **spec 改动需显式放行**：`specs/` 不在默认编辑目标树内，S1 执行前须取得用户显式确认。
  - 文档一律简体中文；本文档与 S0 起，文档不写主机绝对路径与个人标识。

## 4. 方案决策

### 4.1 目标目录树（唯一目标形态）

> ★ = 该期新建。**S2 不创建 `core/` 与 `ros_adapter/`**（避免空包=桩），它们在 S3/S4 有实际内容时创建。

```
l3-dispatcher-planner/ros_packages/dispatcher/
  dispatcher_node.py                    # composition root（S3 吸收 create_dispatcher_engine / start_dispatcher_workers）
  dispatcher/
    __init__.py
    engine.py                           # core 门面：FSM 主循环 + 全局状态 + 任务编排 + 动作裁定（领域逻辑，零 ROS）
    core/                        ★ S3  # core 私有协作模块（领域逻辑，零 ROS）
      __init__.py
      telemetry.py                      # RunTelemetry：slog / trace / 监控 / 等待诊断
      task_phase.py                     # TaskPhaseBridge：相位事件组装与上报
      skill_router.py                   # SkillRouter：技能注册表 / 分发 / 归属快照 / 结果暂存
      actuators.py                      # PlannerActuators：planner 动作面指令（yaw 模式等）
      ports.py                          # ★ S3 端口 Protocol（ROS 收发面的抽象）
    ros_adapter/                 ★ S3  # 唯一允许 rospy / ROS 消息类型的位置（R1）
      __init__.py
      core_channels_ros.py        ★ S3  # 四类 core 通道：急停 / if_handle_yaw / 命令内容监控 / 任务相位
      params_ros.py               ★ S4  # ROS 私有参数装载（config 的 ROS 面）
      clock_ros.py                ★ S4  # 关停信号 / 时钟 / 日志端口实现（装配面用）
      feedback_ros.py             ★ S4  # 传输反馈收发（`zenoh_rpc` 的 Subscriber / ServiceProxy 面）
      perception_ros.py           ★ S4b # 感知层收发实现（自 base_policy.py 拆出，评估后执行）
    utils/                       ★ S2  # 支撑平面
      __init__.py
      state.py  config.py  slog.py
      connection_lease.py  zenoh_rpc.py  rpc_plane.py
      control_plane.py                  # 自 tools/ 移入（装配职责归位，消解双向耦合）
    tools/                              # 执行平面（叶子平面）
      __init__.py
      protocol.py  model.py  registry.py  runtime.py  executor.py  skill_api.py
      <family>/                         # vla / scene_nav / flight / grasp（后续轮次迁入）
    perception/                         # 感知层（位置不变）
      __init__.py  base_policy.py  pointcloud_accumulator.py
```

- **端口与适配的方向**：端口 Protocol 由**被依赖侧**声明（`core/ports.py` 声明 core 四通道；`utils/` 为传输反馈面声明自己的端口），`ros_adapter/` 实现并由 `dispatcher_node.py` 注入——因此 `core/`、`utils/` 都不 import `ros_adapter/`，`ros_adapter/` → 被依赖侧 单向成立（§4.2 矩阵）。
- `feedback_ros.py` 由 S4 子方案登记（`zenoh_rpc.py` 的 Subscriber/ServiceProxy 无其他合法落点）；`params_ros.py`/`clock_ros.py`/`perception_ros.py` 同属 S4。

### 4.2 平面定义与一层依赖矩阵（唯一裁决，验收据此 grep）

| 层 / 单元 | 定位（一句话） | 允许的**包内**依赖 | 禁止的包内依赖 |
|---|---|---|---|
| `engine.py` | core 门面：FSM + 全局状态 + 编排 + 动作裁定 | `core/`、`tools/`、`utils/`、`perception/`、`ros_adapter/` | — |
| `core/` | core 私有协作模块（领域逻辑） | `core/` 内部、`tools/model`+`tools/skill_api`（模型与技能契约）、`utils/state`+`utils/slog` | `utils` 传输类、`perception/`、`ros_adapter/`、`engine` |
| `ros_adapter/` | ROS 收发适配（唯一允许 `rospy` 与消息类型处） | `core/`（端口 Protocol）、`utils/`、`perception/`、`rospy`/ROS 消息 | `tools/`、`engine` |
| `tools/` | 执行平面：注册表 / 准入 / 路由 / 技能契约 / 模型与协议词表 | `tools/` 内部 + stdlib/三方 | `utils/`、`perception/`、`core/`、`engine`、`ros_adapter/` |
| `utils/` | 支撑平面：传输 / 租约 / 日志 / 配置 / 状态 / 装配 | `utils/` 内部、`tools/`（作为执行平面的消费者） | `perception/`、`core/`、`engine`、`ros_adapter/` |
| `perception/` | 感知层：传感器数据获取与几何换算 | `perception/` 内部、`utils/state` | `tools/`、`core/`、`engine`、`utils`（除 `state`）、`ros_adapter/` |
| `dispatcher_node.py` | composition root | `engine`、`utils/control_plane`、`ros_adapter/` | — |

- 依赖方向：**支撑面 → 执行平面**、**core → 三个平面**；`tools/` 是叶子平面（零包内出边）。
- ROS 面方向：**`core/` 只声明端口，`ros_adapter/` 实现端口**；`core/` 与其消费者不 import `ros_adapter/`（依赖倒置）。是否进一步把适配器构造也移到 `dispatcher_node.py`（构造注入）登记为可选优化，非本期必需。

### 4.3 命名规范表

| 类型 | 规范 | 示例 |
|---|---|---|
| 平面目录 | 小写单词、语义化，层级即平面 | `core/`、`tools/`、`utils/`、`perception/`、`ros_adapter/` |
| 适配文件 | `*_ros.py`；仅此命名可含 `rospy` 与 ROS 消息类型 | `core_channels_ros.py`、`params_ros.py`、`perception_ros.py` |
| core 协作模块 | 小写下划线、按「职责角色」命名 | `telemetry.py`、`task_phase.py`、`skill_router.py`、`actuators.py` |
| 执行模块 | 小写下划线、按执行平面词汇命名 | `protocol.py`、`model.py`、`registry.py`、`runtime.py`、`executor.py`、`skill_api.py` |
| 技能族目录 | `tools/<family>/`：`__init__.py` + `<family>_skill.py` + 族私有模块 | `tools/vla/vla_skill.py`、`tools/scene_nav/graph_source.py` |
| 类 | 大驼峰、职责名词 | `RunTelemetry`、`SkillRouter`、`ToolRuntime`、`BasePolicyNode` |
| 常量 / 错误码 | 大写下划线 | `METHOD_NOT_FOUND`、`INVALID_PARAMS`、`BUSINESS_REJECTED` |
| 函数 / 方法 | snake_case；位置迁移一律沿用原名（迁移非重构） | `tool_for_name`、`publish_task_phase` |
| 方案文档 | `design-dispatcher-*.md` | 本文档 |
| 契约文件 | `specs/implemented/{<root>,inner/<area>-<name>}.spec.md`（`specs/README.md`） | `inner/l3-core-boundary.spec.md` |

### 4.4 契约不变量 → 门禁映射（验收基线）

> 既有门禁编号沿用契约（G1–G23），不重编号。新增门禁在本总纲登记为 **A1–A5**；门禁脚本工具（`specs/tools/*`）尚未迁移，落地前用等价 grep/脚本判定。

| 门禁 | 检查 | 来源 | 本期状态 |
|---|---|---|---|
| G1 | core 的 import 闭包不含技能/领域模块 | core-boundary B1 | S2/S3 后判 |
| G2 | `DISPATCHER_STATE` 成员数 == 6；**且** core 的 `def` 集合 ⊆ 契约白名单（S1 把「约定阈值」改写为可判定的方法集） | core-boundary B4 | S1 改判定，S3 后判 |
| G3 | 分发未命中路径存在 fail 上报且无 done 上报 | core-boundary B5 | **S6 修** |
| G4 | core 发布器集合 ⊆ B3 四类白名单 | core-boundary B3 | 现状已过（4 个） |
| G5 | l3 core 与领域层零任务编号标识符；上游字段只允许出现在适配层的丢弃逻辑 | core-boundary B2/B7/B8 | **S5 修** |
| G6 | 每个等待循环有周期性诊断输出，区分「从未收到」与「已过期」 | core-boundary O1 | 现状已过 |
| G7 | 领域层文件零命中 `rospy\.` / `ros::` / `Publisher(` / `Subscriber(` | ros-adapter R1 | **S4 修** |
| G8 | 领域层 import 闭包不含 `*_msgs` | ros-adapter R2 | **S4 修** |
| G9 | 每个端口接口至少一个适配层实现，且实现体内无状态推进分支 | ros-adapter R5 | S4 建立后判 |
| G10 | `ros_packages/` 下不存在名为 `mission_executive` 的包 | execution-seam §1 | 现状已过 |
| G11 | 执行缝代码无工具名字符串分支 | execution-seam §4 | 无执行缝代码，不适用 |
| G12 | 经 pybind 暴露的每个能力端口有纯 C++ 单测 | execution-seam §3 | 未接线，登记 |
| G13 | 每个技能声明 `name`/`requires_perception`/`synchronous` 且不引用任务编号 | skill-contract §2 | **无技能实现 → 无判定对象；随技能轮次** |
| G14–G17 | 技能私有访问/ disposer / 技能互 import / 钩子默认实现 | skill-contract §5–§6、§3 | 同上 |
| G18–G23 | 迁移规程：契约先行、无调用方不迁、旧实现删除、行为契约 diff、无静默成功、零编号引入 | migration-protocol §1–§4 | 每期验收时逐条判 |
| **A1** | 依赖方向门禁：`grep -rn "dispatcher\.\(utils\|perception\|core\|ros_adapter\)" PKG/dispatcher/tools/` 零命中；`grep -rn "dispatcher\.engine" PKG/dispatcher/{utils,core,perception}/` 零命中 | 本总纲 §4.2 | S2/S3/S4 后判 |
| **A2** | 适配面门禁：非 `*_ros.py` / `ros_adapter/` 文件零命中 `import rospy` / ROS 消息类型 | 本总纲 §4.3 + R1/R2 | S4 后判 |
| **A3** | 旧路径清零：无包根 `skill_api.py`/`state.py`/`config.py`/`slog.py`/`connection_lease.py`/`zenoh_rpc.py`/`rpc_plane.py`；无 `tools/control_plane.py`；无任何 re-export 转发模块 | S2 | S2 后判 |
| **A4** | 隐私门禁：纳入版本控制的 `*.md` / `*.sh` / skills 零命中主机绝对路径与个人标识；公开仓库 URL 除外并已在 spec 中收敛措辞 | AGENTS.md 硬约束 1/2 + S0 | S0 后判 |
| **A5** | 引用闭包：`python3 -m py_compile` 全绿 + 分级 import 冒烟通过 + 无未解析符号（孤儿引用按方案登记处置，不得隐藏） | migration-protocol §6 | 每期判 |
| **A6** | 工具面对外协议门禁：`list_tools()["revision"]` 断言（白名单值）+ `tool_call_ack` / `tool_event` 键集快照 + 拒绝 reason 词表快照 | 本总纲 §4.4；工具面契约补齐归 S7（此前以旧库 `agent-station-tools.spec.md` 锚定） | S5/S6 后判 |

- **G2 白名单的定稿规则**（消解 S1 与 S3 的互相等待）：白名单的**取值来源**是 S3 子方案已冻结的命名与保留边界
  （`design-dispatcher-engine-relocate-non-core.md` §4.2 保留集 + §4.3 迁出集的新名 + §4.5 端口集合）；
  **S1 定稿**（`design-dispatcher-spec-reconciliation.md` §4.1/§4.2）负责把它写成契约文本。两者须同一改动对齐；
  因 S1 执行先于 S2/S3，S1 定稿时直接采用 S3 文档中的冻结名，**不得留「待 S3 定稿」占位**，也不得反过来要求 S3 改树。

### 4.5 B3 ↔ R1/R4 冲突裁决（提案，S1 定稿）

> 结论：**两条契约都不删，B3 加限定、R1 加指引**，使二者相容。

- **裁决内容**：`l3-core-boundary` B3 的「core 只允许持有四类发布器」应理解为**语义白名单**（即 core 的对外通道集合固定为这四类），**不豁免** `l3-ros-adapter-boundary` R1/R2/R4——这四类通道的 ROS 实现必须落在适配文件（`ros_adapter/*_ros.py`），core 只持有端口引用；`l3-ros-adapter-boundary` §2 增一句引用 B3 白名单，明确「core 的四类通道同样适用本契约」。
- **备选（不推荐）**：删除 B3 白名单，改为「core 零 ROS，全部经适配层端口」。否决理由：B3 的价值是**限制 core 的对外通道数量**（防止 core 变成通信聚合点），删除会丢失去这条约束；而加限定的改动面更小、语义更强。
- **影响**：裁决后 G7 对 `engine.py` / `core/` 生效，`ros_adapter/core_channels_ros.py` 成为四类通道的唯一合法落点；S4 的拆分边界由此确定。

### 4.6 技能端口与技能族落地时机裁决（不留桩）

- **裁决**：`l3-skill-contract` §7 的 11 个宿主端口**不在本期补齐**。端口与技能族**同轮落地**——没有技能实例时先造端口会立刻变成「只被自己引用的空实现」，违反 `l3-migration-protocol` §1「不留桩」与「不投机设计」。
- **登记**：该缺口以「端口清单已由契约定义、宿主未实现」的形式登记在 S6 的待办与后续技能轮次的入口条件中（**不进契约正文**，符合 §5.2「待办不进契约」）。
- **本期可做且必须做的**：G3 的「未注册即失败」语义修正（S6）——它不依赖技能族，只改 core 的失败路径。

### 4.7 分期路线图与依赖（S0 → S6）

| 期 | 名称 | 子方案 | 前置 | 行为影响 | 是否需显式放行 |
|---|---|---|---|---|---|
| S0 | 隐私与文档门禁清理 | `design-dispatcher-privacy-gate-cleanup.md` | — | 纯文档 | 是（含 `AGENTS.md`、`.trae/skills/`，默认目标树之外） |
| S1 | 契约修订（消解自相矛盾与不可判定） | `design-dispatcher-spec-reconciliation.md` | S0（措辞统一） | 纯契约 | **是**（`specs/`） |
| S2 | 包拓扑归位（tools/utils/perception） | `design-dispatcher-package-topology.md`（改写） | S1 | 零行为（move + import） | 否 |
| S3 | engine 非 core 职责迁出 + core 四通道适配落位（`core/` + `ros_adapter/core_channels_ros.py`） | `design-dispatcher-engine-relocate-non-core.md`（改写） | S2 | 零行为（位置迁移 + 端口注入 + 组合） | 否 |
| S4 | 其余 ROS 面适配（`config` 参数面 / 装配面 / 感知层评估） | `design-dispatcher-ros-adapter-split.md` | S3、S1 | S4a 零行为；S4b 感知拆分见子方案 | 否（S4b 若超阈值需再确认） |
| S5 | task_id 全链路退役（含 l4 wire 处置） | `design-dispatcher-taskid-retirement-full.md` | S1、S4 | 有（对外 ack/event 字段与发现面 `_meta`） | 否（字段级变更已在 S1 登记） |
| S6 | 分发失败语义与端口登记 | `design-dispatcher-dispatch-fail-semantics.md` | S3 | 有（未注册路径从 done 改为 fail） | 否 |
| S7 | 工具面契约补齐（把工具面对外协议补进 `specs/`） | `design-dispatcher-tool-plane-contract.md` | S1 | 纯契约 | **是**（`specs/`） |
| — | 后续轮次（不在本套） | — | S7 之后 | — | 技能族迁入（含 `SkillHost` 11 端口）、`recording`/`vlm_facade`、任务注入、**S4b 感知层 ROS 隔离**、门禁脚本迁移 |

- 排序理由：**先钉目标（S0/S1）→ 再搬位置（S2/S3）→ 再收 ROS 面（S4）→ 再做有对外影响的语义/字段变更（S5/S6）**。S4 在 S3 之后，是因为四类通道的实现位置由协作模块拆分结果决定；S5 在 S4 之后，是因为适配层是「丢弃上游编号」的唯一合法落点。
- 每期独立可回退：纯位置期为「文件移回 + 还原 import」；语义期按子方案给回退点。

### 4.8 文档集与取代关系

| 文档 | 角色 | 与既有文档的关系 |
|---|---|---|
| `design-dispatcher-architecture-stabilization.md`（本文件） | **总纲 / 索引 / 裁决** | 对既有 6 份轮次方案做目标形态收敛 |
| `design-dispatcher-execution-plan.md` | **执行计划（编排总表）** | 新增；唯一执行顺序、唯一状态总表、放行门、执行流水线与 DoD——**执行顺序与状态以它为准** |
| `design-dispatcher-privacy-gate-cleanup.md` | S0 子方案 | 新增 |
| `design-dispatcher-spec-reconciliation.md` | S1 子方案 | 新增；裁决 §4.5、G2 判定、决策记录落点、措辞收敛 |
| `design-dispatcher-package-topology.md` | S2 子方案 | **就地改写**（收敛为对齐本总纲 §4.1/§4.2 的执行版） |
| `design-dispatcher-engine-relocate-non-core.md` | S3 子方案 | **就地改写**（目标路径改 `core/` + `ros_adapter/`，`control_plane` 归 `utils/`，行号按 1067 行版重锚） |
| `design-dispatcher-ros-adapter-split.md` | S4 子方案 | 新增 |
| `design-dispatcher-taskid-retirement-full.md` | S5 子方案 | 新增；与已 done 的 `design-dispatcher-taskid-retirement-deps-migration.md` 是**续篇**，不改写历史记录 |
| `design-dispatcher-dispatch-fail-semantics.md` | S6 子方案 | 新增 |
| `design-dispatcher-tool-plane-contract.md` | S7 子方案（后续轮次） | 新增；把工具面对外协议不变量补进 `specs/`（需放行） |
| `design-dispatcher-core-inference-migration.md` / `-engine-narrow-core-trim.md` / `-zenoh-transport-migration.md` | 已 done 的历史记录 | 不改写 |

- **阅读/执行顺序**：先读本总纲（§3 约束 → §4 决策 → §4.7 路线图），再读 `design-dispatcher-execution-plan.md`（**唯一执行顺序与状态总表**），然后按 `S0 → S1 → S2 → S3 → S4 → S5 → S6`（S7 为 S1 之后可插入的后续轮次）打开对应子方案执行；S0/S1/S7 需先取放行，未放行则其后的期不得开工（S2 前置 S1，避免目标树未定即搬迁）。
- 子方案与总纲冲突时**以总纲为准**，并在同一改动内修正子方案（总纲是目标形态的唯一权威）。

## 5. 迁移映射表（模块级总表）

> 细表归各期子方案；本表只给「模块 → 目标平面」的最终归属，便于对照 `design-dispatcher-package-topology.md` 与 `design-dispatcher-engine-relocate-non-core.md` 的旧裁决。

| 现状位置 | 目标位置 | 动作 | 期 |
|---|---|---|---|
| `PKG/dispatcher/state.py` / `config.py` / `slog.py` | `PKG/dispatcher/utils/*` | move（内容逐字不变） | S2 |
| `PKG/dispatcher/connection_lease.py` / `zenoh_rpc.py` / `rpc_plane.py` | `PKG/dispatcher/utils/*` | move + import 改写（`tools.protocol`） | S2 |
| `PKG/dispatcher/tools/control_plane.py` | `PKG/dispatcher/utils/control_plane.py` | move + import 改写 | S2 |
| `PKG/dispatcher/skill_api.py` | `PKG/dispatcher/tools/skill_api.py` | move | S2 |
| `PKG/dispatcher/tools/model.py::ToolProtocolError`、`registry.py::METHOD_NOT_FOUND/INVALID_PARAMS`、`runtime.py::BUSINESS_REJECTED` | `PKG/dispatcher/tools/protocol.py` | move（同平面） | S2 |
| `PKG/dispatcher/engine.py::create_dispatcher_engine` / `start_dispatcher_workers` | `PKG/dispatcher_node.py` | move | S3 |
| `PKG/dispatcher/engine.py` 遥测/监控/诊断块 | `PKG/dispatcher/core/telemetry.py` | move + 改协作调用 | S3 |
| `PKG/dispatcher/engine.py::_publish_task_phase` 及三字段 | `PKG/dispatcher/core/task_phase.py` | move + rename | S3 |
| `PKG/dispatcher/engine.py` 注册表/归属/结果暂存 | `PKG/dispatcher/core/skill_router.py` | move | S3 |
| `PKG/dispatcher/engine.py::_set_if_handle_yaw` + pub | `PKG/dispatcher/core/actuators.py` | move | S3 |
| `PKG/dispatcher/engine.py` 工具执行缝（host 三缝 `bind_tool_middleware`/`start_tool_workflow`/`cancel_tool_call` + `_activate_tool_call` + 6 字段） | `PKG/dispatcher/core/workflow.py` | move | S3 |
| `engine.py` 内四类 core 通道（急停 / `if_handle_yaw` / 命令内容监控 / 任务相位）的 ROS 实现 | `PKG/dispatcher/ros_adapter/core_channels_ros.py` + `core/ports.py` | move + 端口化 | S3 |
| `config.py` 的 ROS 私有参数面、`control_plane.py` / `zenoh_rpc.py` 的 `rospy` 关停与日志/反馈面、`perception/*.py` 的收发 | `PKG/dispatcher/ros_adapter/{params_ros,clock_ros,feedback_ros,perception_ros}.py` | move + 端口化 | S4 |
| `tools/model.py` / `registry.py` / `runtime.py` / `rpc_plane.py` / `engine.py` 的任务编号 | 删除（含 `rpc_plane` 的本地注入）；**wire 无该字段，无兼容处置** | delete | S5 |
| `engine.py` 未注册分发的 `advance` 路径 | 改为 fail 上报 + 停 `WAIT_FOR_MISSION` | rewrite | S6 |

## 6. 删除清单（总表）

| 删除项 | 理由 | 期 |
|---|---|---|
| 包根 `skill_api.py` / `state.py` / `config.py` / `slog.py` / `connection_lease.py` / `zenoh_rpc.py` / `rpc_plane.py` | 迁入 `tools/` / `utils/`；禁止 re-export 转发桩 | S2 |
| `tools/control_plane.py` | 迁入 `utils/`；消除 `tools → utils` 反向边 | S2 |
| `tools/model.py::ToolProtocolError`、`tools/registry.py::{METHOD_NOT_FOUND,INVALID_PARAMS}`、`tools/runtime.py::BUSINESS_REJECTED` 的旧定义 | 迁入 `tools/protocol.py` | S2 |
| `engine.py` 内被迁出的方法/字段（遥测、相位桥、注册表、动作面、执行缝） | 迁入 `core/`；不留同名薄封装桩 | S3 |
| 领域文件内的 `import rospy` / `from *_msgs` / Publisher / Subscriber / Service / Action 构造 | 迁入 `ros_adapter/*_ros.py`；领域层零命中 | S4 |
| `ToolCall.task_id` / `ToolSpec.task_id` / `_by_task_id` / `tool_for_task_id` / `_meta["lx.task_id"]` / ack 与 event 的 `task_id` / `engine.current_task_id` / `task_ids=[…]` | 编号退役（B2/B7/B8、G5/G23） | S5 |
| `engine._handle_plan_tool` 与 `_validate_active_tool` 的「未命中即 advance」分支 | 改为 fail（B5/G3） | S6 |
| `AGENTS.md` / `doc/**/*.md` / `.trae/skills/**` 中的主机绝对路径与个人标识 | 隐私门禁（硬约束 1/2） | S0 |
| 本总纲取代的两处旧裁决（relocate §4 包根模块清单、其 `control_plane` 留在 `tools/` 的位置裁决） | 目标形态唯一化 | S1/S3 |

## 7. 实施步骤（S0 → S6）

> 每期细节（现状证据、决策、映射、删除、验收、风险、修改点）在对应子方案内。本节只列**范围 + 行为不变式 + 回退**。

### S0 — 隐私与文档门禁清理

- 范围：`AGENTS.md`、`doc/l3-dispatcher-planner/iteration/*.md`、`.trae/skills/github-{issue,pull}/SKILL.md` 中的主机绝对路径与个人标识替换为角色名/相对路径；建立可复跑的隐私检索命令。
- 行为不变式：代码零改动；文档语义不变（仅标识替换）。
- 回退：git 还原文档。
- **需显式放行**：`AGENTS.md` 与 `.trae/skills/` 在默认目标树之外。

### S1 — 契约修订

- 范围：`specs/`：B3↔R1/R4 措辞（§4.5）、G2 第二子句改为可判定方法集、硬约束 1 措辞收敛（公开服务标识 vs 主机本地凭据）、决策记录落点接线（`specs/implemented/architecture/`）。
- 行为不变式：不改任何不变量语义，只消除自相矛盾与不可判定；不改代码。
- 回退：git 还原 `specs/`。
- **需显式放行**：`specs/` 不在默认编辑目标树内。

### S2 — 包拓扑归位（`design-dispatcher-package-topology.md` 执行版）

- 范围：`tools/`（含 `protocol.py`）/ `utils/` / `perception/` 三层落位；包根只剩 `engine.py` + `__init__.py`。
- 行为不变式：**零行为改写**（move + import 改写）；`list_tools()["revision"]`、topic/queryable、slog 事件名与键集字节级不变。
- 回退：文件移回 + 还原 import。

### S3 — engine 非 core 职责迁出 + core 四通道适配落位

- 范围：新增 `core/{telemetry,task_phase,skill_router,actuators,workflow}.py` 与 `core/ports.py`（端口 Protocol）；
  四类 core 通道的 ROS 实现一次性落 `ros_adapter/core_channels_ros.py`（**避免先搬家再拆 ROS 的二次搬迁**）；
  装配函数（`create_dispatcher_engine` / `start_dispatcher_workers`）入 `dispatcher_node.py`；engine 改为组合调用。
- 行为不变式：slog 事件名/键、topic 名与 payload、状态迁移 reason、等待诊断串格式字节级不变；空注册表下所有回退路径与现状等价。
- 回退：还原方法体与调用点 + 删除新增模块。

### S4 — 其余 ROS 面适配

- 范围：S4a 建 `ros_adapter/{params_ros,clock_ros,feedback_ros}.py`——`config.py` 的 ROS 私有参数面、`control_plane.py` 的 `rospy` 关停与日志、`zenoh_rpc.py` 的 Subscriber/ServiceProxy 反馈面全部端口化；S4b 感知层拆分（`perception_ros.py`）**先评估后执行**。
- **S4b 前置结论（见子方案 §7.2 门槛判据）**：子方案初判门槛不满足（`base_policy.py` 实测 100 处 `rospy.`，且 `Frame.cloud_msg`/`OdometryBuffer` 把 ROS 消息类型与几何/状态交织，无 ROS-free 感知测试）→ **S4b 在本套中按「另立后续轮次」处置**，执行前须按子方案判据复核；S4a 不受影响。
- 行为不变式：S4a 零行为（同 topic/param/消息字段）；S4b 见子方案的独立性论证。
- 回退：适配器实现移回原文件 + 删除对应 `ros_adapter/` 文件。

### S5 — task_id 全链路退役

- 范围：`tools/{model,registry,runtime}.py`、`utils/rpc_plane.py`、`engine.py`、`tests/tool-registry/*`；**wire 不携带编号（已取证）→ 无「适配层入口丢弃」动作**，只删本地派生与传递。
- **对外变更登记以 S1 为准**：S5 子方案 §1.3/§2.0 的三条自登记（E1 发现面 `_meta`+`revision`、E2 ack/事件字段、E3 未注册 done→fail 属 S6）与 S1 的登记项内容一致；执行时**以 `design-dispatcher-spec-reconciliation.md` 的登记项为权威**，S5 只引用不复述结论。
- 行为不变式：工具发现面按 S1 登记的字段变更执行（`_meta` 与 ack/event 的 `task_id` 去除属**已登记的有意变更**）；`revision` 随之变化需显式断言新值；其余协议不变。
- 回退：按子方案的分步回退点。

### S6 — 分发失败语义与端口登记

- 范围：`engine.py`（S3 后为 `core/skill_router.py` + engine 回退路径）未注册分发改为 fail 上报 + 停 `WAIT_FOR_MISSION`；端口缺口与技能族时机登记（§4.6）。
- 行为不变式：只有「未注册」路径的对外可观测行为改变（done → fail），属 S1 已登记的有意变更。
- 回退：还原分支 + 还原 phase 上报。

## 8. 验收标准（总门禁，每期全跑）

- [ ] `python3 -m py_compile` 对 `PKG/**/*.py` 与 `dispatcher_node.py` 全绿（A5）。
- [ ] 分级 import 冒烟：L1（零 ROS 子集）必过；L2/L3 依主机 ROS 环境判定，不可用时回退静态验收并在方案中记录（不得因环境缺失判失败）。
- [ ] `pytest l3-dispatcher-planner/tests/tool-registry` 全绿；`test_rpc_plane_navigation` 的 scene_graph 用例维持「因技能族未迁而失败」的既有预期。
- [ ] 字节级契约不变：`ToolRegistry.default().list_tools()["revision"]`（S5 除外，S5 断言新值）、`ZenohTaskMiddleware.queryable_suffixes()`、`presence_token_key` / `owner_watch_key`。
- [ ] slog 事件名/键集、transition reason、topic/param/消息字段名、`/agent_task_phase` payload 字节级一致（S5/S6 已登记项除外）。
- [ ] 依赖方向（A1）：`tools/` 零 `dispatcher.utils|perception|core|ros_adapter`；`utils/`、`core/`、`perception/` 零 `dispatcher.engine`。
- [ ] 适配面（A2）：非 `*_ros.py`/`ros_adapter/` 文件零 `import rospy`、零 ROS 消息类型。
- [ ] 旧路径清零（A3）：包根无被迁出模块、`tools/` 无 `control_plane.py`、无 re-export 转发模块。
- [ ] 隐私门禁（A4）：检索命令零命中（公开仓库 URL 除外）。
- [ ] 契约一致性：G1–G23 逐条判定，未达成项在方案或 issue 中登记，无静默漂移。

## 9. 风险与对策

| 风险 | 影响 | 对策 |
|---|---|---|
| 期数多、跨期漂移（目标树被下一期再改） | 反复搬迁、diff 冲突 | 目标树与依赖矩阵在本总纲唯一钉死（§4.1/§4.2），子方案不得自行改树；改树须先改总纲 |
| S4b 感知层拆分（3077 行）超出「稳定」负荷 | 期无法收敛、引入回归 | S4b 单列并**先评估**（触点数/单测可行性/回退粒度），超阈值即拆成独立轮次或降低目标（只隔离收发、不动几何） |
| S5 改变对外字段（`_meta.task_id`、ack/event） | 站端消费失败 | 变更在 S1 登记为有意变更并给兼容处置；`revision` 断言新值；适配层保留 wire 兼容解析 |
| S6 把 done 改 fail 触发站端行为变化 | 站端任务卡住 | S1 登记为有意变更；fail 上报带未命中的工具名（O3），站端可定位；与 l4 侧确认后执行 |
| 门禁工具（`specs/tools/*`）未迁移 | 门禁只能手工跑 | 本期用等价 grep/脚本（§4.4 A1–A5）；工具迁移登记为后续轮次，不在本套内凭空引用 |
| 契约修订被质疑「改契约迁就现状」 | 评审返工 | §4.5 是「消除自相矛盾」而非放宽：两条都保留且更强；其余修订均为把不可判定改为可判定（G2）与措辞收敛（硬约束 1），不改不变量 |
| `AGENTS.md`/`.trae/skills` 在默认目标树外 | 越界改动 | S0 列为需显式放行项；未放行则 S0 只改 `doc/` 下文档 |

回滚路径：S0/S1 为文档/契约，`git` 还原；S2/S3/S4a 为位置迁移，逐期「移回 + 还原 import」；S5/S6 按子方案分步回退点；执行前建议对 `PKG/` 全量快照（放主机本地，不入库）。

## 10. 修改点清单汇总

| 文件 | 动作 | 说明 |
|---|---|---|
| `doc/l3-dispatcher-planner/iteration/design-dispatcher-architecture-stabilization.md` | 新增 | 本总纲 |
| `doc/l3-dispatcher-planner/iteration/design-dispatcher-privacy-gate-cleanup.md` | 新增 | S0 子方案 |
| `doc/l3-dispatcher-planner/iteration/design-dispatcher-spec-reconciliation.md` | 新增 | S1 子方案 |
| `doc/l3-dispatcher-planner/iteration/design-dispatcher-package-topology.md` | 改写 | S2 执行版（对齐本总纲） |
| `doc/l3-dispatcher-planner/iteration/design-dispatcher-engine-relocate-non-core.md` | 改写 | S3 执行版（对齐本总纲，行号重锚） |
| `doc/l3-dispatcher-planner/iteration/design-dispatcher-ros-adapter-split.md` | 新增 | S4 子方案 |
| `doc/l3-dispatcher-planner/iteration/design-dispatcher-taskid-retirement-full.md` | 新增 | S5 子方案 |
| `doc/l3-dispatcher-planner/iteration/design-dispatcher-dispatch-fail-semantics.md` | 新增 | S6 子方案 |
| `AGENTS.md`、`doc/**/*.md`、`.trae/skills/**` | 修改 | S0：标识替换（需放行） |
| `specs/implemented/**` | 修改 | S1：契约修订（需放行） |
| `PKG/dispatcher/**`、`PKG/dispatcher_node.py`、`tests/tool-registry/*` | 修改 | S2–S6：代码改动（细节见各子方案） |

**登记的后续轮次**：**S7 工具面契约补齐**（`design-dispatcher-tool-plane-contract.md`，需放行）；**S4b 感知层 ROS 隔离**（S4 子方案 §7.2 门槛不满足，另立轮次）；技能族迁入（`tools/<family>/`）与 `SkillHost` 11 端口同轮落地；`recording` / `vlm_facade` 归位；任务注入轮次（`_start_prompt_task` / `arm_action`）；`specs/tools/*` 门禁脚本迁移；`specs/implemented/architecture/` 决策记录归档。

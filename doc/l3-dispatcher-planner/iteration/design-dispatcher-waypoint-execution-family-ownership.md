# 航点下发执行按家族归属 方案

> 摘要：把 `WaypointExecution`（单目标航点下发执行：批次、反馈、超时、取消）
> 从共享平面 `dispatcher/execution/waypoint.py` 迁出，按使用者分别落到
> `tools/flight/waypoint.py` 与 `tools/vla/waypoint.py` 各一份（内容可以相同，
> 各自独立演进）。依据：用户裁定「航点发布是一个独立能力，后续新增的很多功能
> 完全不使用该发布，因此必须迁移」。
> **本次只动 `l3-dispatcher-planner/` 与 `specs/`；不改 planner、不改 `ros_adapter`
> 行为、不改 topic/消息。**

## 0. 元信息

| 项 | 值 |
|----|----|
| 日期 | 2026-09-21 |
| 目标路径 | `l3-dispatcher-planner/ros_packages/dispatcher/dispatcher/`、`specs/implemented/inner/` |
| 状态 | done（2026-09-21 执行完毕；归档 `specs/implemented/architecture/2026-09-21-waypoint-execution-family-ownership.md`；按 `AGENTS.md` §9 未运行 pytest，静态 grep 验收见 §8；同轮按用户指令补家族前缀：`flight_waypoint.py`/`vla_waypoint.py`、`FlightWaypointExecution`/`VlaWaypointExecution`） |
| 关联文档 | `specs/implemented/inner/l3-execution-seam.spec.md`、`specs/implemented/inner/l3-package-layout.spec.md`、`specs/implemented/inner/l3-skill-contract.spec.md`、`doc/l3-dispatcher-planner/rest/dispatcher-deferred-dependencies.md` R05、[机上收窄方案](design-dispatcher-vla-waypoint-executor-migration.md) |

### 0.1 范围裁定（用户指令）

1. **裁定依据**：用户明确指示——「`waypoint` 发布是一个独立的能力；后续新增的
   很多功能都完全不使用这个 `waypoint` 发布了；因此你必须迁移」。
2. **落地形态**：用户在上一轮明确要求——「在 basic-flight 和 vla 中**分别写两个
   waypoint 方案（哪怕相同）**来实现下发」。
3. **契约关系**：该裁定与现行 `l3-execution-seam.spec.md` §1/§4/§6 冲突（现行
   条文把航点下发执行归入「跨工具共享」的共享执行能力）。按 `AGENTS.md` §6，
   已停下并引用双方原文请用户裁决；用户裁决为「执行迁移」。故本方案**先改
   spec、再改实现**（`AGENTS.md` §代码优化工作流 第 1 条、spec 先行）。
4. **事实澄清**：用户提出「waypoint 不被 scene_nav 使用」。核实结论是
   `scene_nav` 家族**尚未迁入**（非「实现了但不用」），因此该点不构成本轮迁移的
   反例证据；本方案按用户裁定的设计原则执行，不以其为唯一依据。

## 1. 背景与动机

- 现状：`dispatcher/execution/` 平面把「单目标航点下发执行」实现为一份
  `WaypointExecution`，由飞行家族（六个 basic-flight 技能）与 VLA 家族
  （`navigation.vla_nav`）**共用**。
- 用户裁定：航点下发是**独立能力**，不是「所有工具共享」的通用执行缝；后续新增
  功能不会使用它。因此它不应占据共享平面的位置，应归属到实际使用它的家族。
- 收益（用户视角）：共享平面不再承载家族专属行为；两个家族的下发执行可各自
  独立演进，互不牵制。
- 代价（须明示）：同一份执行状态机会存在两份相同实现。用户已明确接受
  「哪怕相同」。

## 2. 现状事实（问题清单）

> 证据路径：`N/` = `l3-dispatcher-planner/ros_packages/dispatcher/dispatcher/`；
> `S/` = `specs/`。

### 2.1 待迁实现与调用面

- [ ] `N/execution/waypoint.py#L1-L104` — 整模块即 `WaypointExecution`
      （`start` #L33-L50、`poll` #L52-L75、`_next_batch` #L77-L81、
      `_publish_hold` #L83-L90、`cancel` #L92-L96、`stop` #L98-L103）。
- [ ] `N/execution/waypoint.py#L6` — `from dispatcher.execution.ports import
      ActionResult, FlightConfig, FlightPorts, Goal`（依赖共享端口）。
- [ ] `N/execution/waypoint.py#L45` — `self.ports.send_goal(self._batch, goal)`
      出海；`#L63-L71` 消费 `ports.progress()` 判完成。
- [ ] `N/execution/composition.py#L3` — `from dispatcher.execution.waypoint import
      WaypointExecution`（唯一生产 import）。
- [ ] `N/execution/composition.py#L15` — `install_flight` 内建飞行实例。
- [ ] `N/execution/composition.py#L49` — `install_vla` 内建 VLA 实例。
- [ ] `N/execution/composition.py#L41-L43` — docstring 明示「动作出海复用
      `WaypointExecution`（与飞行共享同一 `FlightPorts` 出站口，独立实例）」。

### 2.2 宿主持有方式（本方案不改）

- [ ] `N/execution/skill_host.py#L9-L13` — `DispatcherFlightHost` 持
      `self.execution`（构造注入，不 import `waypoint` 模块）。
- [ ] `N/execution/skill_host.py#L114-L122` — `VlaSkillHost` 持
      `self.execution`（同上）。
- [ ] `N/execution/skill_host.py#L102-L112` — `VlaSkillHost` docstring 提及
      「动作出海复用 `WaypointExecution`」，迁移后措辞需同步。

> 结论：宿主只依赖**注入实例**，不依赖模块路径，故迁移不会波及
> `skill_host.py` 的逻辑，仅需同步 docstring。

### 2.3 共享端口（本方案保留）

- [ ] `N/execution/ports.py#L7-L17` — `FlightConfig`（含校验）。
- [ ] `N/execution/ports.py#L33-L41` — `FlightState`。
- [ ] `N/execution/ports.py#L44-L48` — `Goal`。
- [ ] `N/execution/ports.py#L51-L55` — `Progress`。
- [ ] `N/execution/ports.py#L58-L61` — `ActionResult`。
- [ ] `N/execution/ports.py#L64-L70` — `FlightPorts` Protocol。
- [ ] `N/ros_adapter/planner_execution_ros.py#L12` — `from
      dispatcher.execution.ports import FlightState, Progress`（适配层实现方）。
- [ ] `N/dispatcher_node.py#L121-L123`、`#L158` — 装配根经
      `execution.ports`/`execution.composition` 接线。

### 2.4 平面自述与契约现状

- [ ] `N/execution/__init__.py#L1-L6` — 平面自述把「`waypoint.py` 为单目标执行」
      写为执行缝组成，需同步。
- [ ] `S/implemented/inner/l3-execution-seam.spec.md#L12-L14` — §1「跨工具共享的
      动作发送、批次关联、反馈、超时与取消机制归 dispatcher 内部执行模块」。
- [ ] `S/implemented/inner/l3-execution-seam.spec.md#L20-L22` — §1 表格行「多工具
      共用的动作发送、批次记账、反馈和取消 → dispatcher 内部共享执行能力」。
- [ ] `S/implemented/inner/l3-execution-seam.spec.md#L59-L62` — §4 通用动作端口
      定义于 `execution/ports.py`，飞行与 VLA 共用（**保留**）。
- [ ] `S/implemented/inner/l3-execution-seam.spec.md#L65-L68` — §4「执行缝不感知
      工具语义……不识别具体工具名」。
- [ ] `S/implemented/inner/l3-execution-seam.spec.md#L86-L88` — §6 门禁 G11。
- [ ] `S/implemented/inner/l3-execution-seam.spec.md#L90-L106` — §7 取消/停止边界
      （**行为不变，仅归属表述需同步**）。
- [ ] `S/implemented/inner/l3-package-layout.spec.md#L24` — §1 平面表
      「`execution/` | 共享执行（执行缝）与共享动作端口」。
- [ ] `S/implemented/inner/l3-package-layout.spec.md#L30-L31` — §1「`execution/ports.py`
      承载跨家族共享的动作意图、状态、进度与配置」。
- [ ] `S/implemented/inner/l3-package-layout.spec.md#L44` — §2 命名示例
      「模块（执行缝）| 语义名词 | `execution/waypoint.py`」。
- [ ] `S/implemented/inner/l3-package-layout.spec.md#L72-L78` — §3 依赖方向表。
- [ ] `S/implemented/inner/l3-package-layout.spec.md#L82-L83` — §3「execution 允许
      家族端口模块仅因 `skill_host.py` 实现各家族宿主端口」。
- [ ] `S/implemented/inner/l3-skill-contract.spec.md#L162-L163` — §10 机上保留项
      引用「取消/保持（`l3-dispatcher/execution-seam` §7）」（引用不变，措辞待核）。
- [ ] `doc/l3-dispatcher-planner/rest/dispatcher-deferred-dependencies.md#L81-L94`
      — R05「动作上下文、武装接口与 VLA 重规划」，归属描述需同步。

### 2.5 测试面（仅路径级，不预读内容）

- [ ] `tests/basic-flight/test_flight.py` — import
      `dispatcher.execution.composition` / `dispatcher.execution.waypoint` /
      `dispatcher.execution.ports`。
- [ ] `tests/core-boundary/test_vla_skill.py` — import
      `dispatcher.execution.waypoint` / `dispatcher.execution.skill_host`。
- [ ] `tests/core-boundary/test_vla_skill_host.py` — 同上。
- [ ] `tests/core-boundary/test_vla_composition.py` — import
      `dispatcher.execution.composition` / `skill_host` / `ports`。
- [ ] `tests/ros/test_ego_cmd.py` — import
      `dispatcher.execution.waypoint` / `dispatcher.execution.ports` /
      `dispatcher.execution.composition`。

## 3. 目标与约束

- **目标**：
  1. `WaypointExecution` 按使用者下沉为两份：`tools/flight/waypoint.py`、
     `tools/vla/waypoint.py`。
  2. 删除共享平面中的 `execution/waypoint.py`（过期必删，不留转接器/别名）。
  3. 共享平面收缩为「共享动作端口（`ports.py`）+ 家族宿主（`skill_host.py`）
     + 装配（`composition.py`）」，并按此改写 `l3-execution-seam` 与
     `l3-package-layout` 的对应条文。
  4. 行为零变化：批次语义、进度判据、超时、取消/保持、`send_goal` 唯一写入口、
     topic 与消息字段全部不变。
- **Non-Goals**：
  - **不下沉** `execution/ports.py`（`Goal`/`FlightPorts`/`FlightState`/
    `Progress`/`ActionResult`/`FlightConfig`）。理由：它是 planner 的**线上接口
    契约**（`/planner/local_goal`、`LocalGoalSet`、`/planner/waypoint_progress`），
    由 `ros_adapter` 单点实现、被两个家族共同消费；复制两份会让适配层失去
    唯一实现目标。若用户要求连端口一并下沉，须另立裁决。
  - **不下沉** `execution/skill_host.py`（`DispatcherFlightHost`/`VlaSkillHost`）。
    本轮只迁 `waypoint`。
  - 不改 `ros_adapter/planner_execution_ros.py`、不改 planner 侧、不改 topic /
    消息 / `batch_id` 语义。
  - 不为 `scene_nav` 预建任何实现或占位（`l3-execution-seam` §5：待迁能力只登记）。
- **硬边界**：
  - 契约先行（`l3-migration-protocol` §1）：先落 `specs/`，再改代码。
  - 反转接器：不得保留 `execution/waypoint.py` 作为 re-export 别名或兼容层。
  - 过期必删：旧路径直接删除，不注释保留。
  - 行为不变式：两份实现必须与旧实现**逐字等价**（用户「哪怕相同」），
    差异只能来自后续各自的独立演进。

## 4. 方案决策

### 4.1 目标目录树（改后）

```
dispatcher/
  execution/
    __init__.py        # 平面自述改：共享动作端口 + 家族宿主 + 装配
    ports.py           # 不变（共享动作端口）
    skill_host.py      # 仅同步 docstring（逻辑不变）
    composition.py     # 改：从两个家族分别 import
    waypoint.py        # 删除
  tools/
    flight/
      __init__.py
      catalog.py
      emergency_stop_skill.py
      land_skill.py
      motion.py
      return_skill.py
      rotate_skill.py
      session.py
      takeoff_skill.py
      translate_skill.py
      flight_waypoint.py  # 新增：FlightWaypointExecution（飞行份）
    vla/
      __init__.py
      catalog.py
      ports.py
      vla_skill.py
      vla_waypoint.py  # 新增：VlaWaypointExecution（VLA 份）
```

### 4.2 命名规范表

| 类型 | 规范 | 示例 |
|------|------|------|
| 文件 | 家族前缀（两家族同名实现，靠前缀区分） | `tools/flight/flight_waypoint.py`、`tools/vla/vla_waypoint.py` |
| 类 | PascalCase 领域名词；家族前缀 | `FlightWaypointExecution` / `VlaWaypointExecution` |
| 方法 | snake_case 动词开头，签名与旧实现逐字一致 | `start` / `poll` / `cancel` / `stop` |

- 依据 `S/implemented/inner/l3-package-layout.spec.md` §2「模块（家族执行）|
  家族前缀」与类命名规范（家族执行实现带家族前缀）。
- 命名修正（2026-09-21 同轮，用户指令）：初版落地为两份同名
  `WaypointExecution`（靠模块路径区分），用户指出同名会混淆，改为
  `FlightWaypointExecution` / `VlaWaypointExecution` 与
  `flight_waypoint.py` / `vla_waypoint.py`。

### 4.3 接口形态

- 两份 `WaypointExecution` 的**公开接口与旧实现完全一致**：
  `__init__(ports, config, *, clock=time.monotonic, first_batch=None)`、
  `state()`、`start(goal)`、`poll()`、`cancel()`、`stop()`。
- 依赖：各自 `from dispatcher.execution.ports import ActionResult, FlightConfig,
  FlightPorts, Goal`（`l3-package-layout` §3 已允许 `tools/<family>/` import
  `execution/ports.py`）。
- 装配：`execution/composition.py` 内
  `from dispatcher.tools.flight.waypoint import WaypointExecution as FlightWaypointExecution`
  与 `from dispatcher.tools.vla.waypoint import WaypointExecution as VlaWaypointExecution`
  （装配根允许 import 全部平面），分别供 `install_flight` / `install_vla` 使用。
- 行为不变式（两份都必须保持）：
  - `start` 前校验：无活动执行/无待处理保持 → 里程计新鲜度/坐标系/有限性 →
    goal 有限性与高度界；失败回滚并上抛。
  - 批次：随机起始（`secrets.randbelow(2**31)+1`）、单调递增、上限
    `2**32-1` 触发 `action_generation_exhausted`。
  - `poll`：仅消费 `batch == self._active` 的进度；`skipped_mask` →
    `waypoint_skipped`；`all_consumed` → 成功；`action_timeout` → `planner_timeout`。
  - `cancel`/`stop`：以新批次发布「当前位置 + `look_forward=false`」保持意图；
    发布失败保留 `_hold_pending` 并拒绝新动作，不假报停止。

### 4.4 旧接口 → 删除

`dispatcher/execution/waypoint.py` 整模块删除，不留 re-export、别名或注释桩。

## 5. 迁移映射表

| 旧路径/命名 | 新路径/命名 | 动作 | 备注 |
|---|---|---|---|
| `N/execution/waypoint.py`（整模块） | `N/tools/flight/flight_waypoint.py`（`FlightWaypointExecution`） | move（复制） | 逐字等价，飞行份 |
| `N/execution/waypoint.py`（整模块） | `N/tools/vla/vla_waypoint.py`（`VlaWaypointExecution`） | move（复制） | 逐字等价，VLA 份 |
| `N/execution/waypoint.py` | — | delete | 过期必删 |
| `N/execution/composition.py#L3` 的 import | 两个家族模块 import | rewrite | 装配根分别引入 |
| `N/execution/composition.py#L15` | `install_flight` 用飞行份 | rewrite | 行为不变 |
| `N/execution/composition.py#L49` | `install_vla` 用 VLA 份 | rewrite | 行为不变 |
| `N/execution/composition.py#L41-L43` docstring | 措辞更新 | rewrite | 去掉「共享/复用」表述 |
| `N/execution/skill_host.py#L102-L112` docstring | 措辞更新 | rewrite | 同上 |
| `N/execution/__init__.py#L1-L6` | 平面自述更新 | rewrite | 平面收缩为端口+宿主+装配 |
| `N/execution/ports.py` | 不变 | — | 共享动作端口保留 |
| `S/.../l3-execution-seam.spec.md` §1/§4/§6 | 归属改写 | rewrite | 见 §7 P0 |
| `S/.../l3-package-layout.spec.md` §1/§2/§3 | 归属改写 | rewrite | 见 §7 P0 |
| `S/.../l3-skill-contract.spec.md` §10 | 措辞核对 | review | 引用路径不变则不改 |
| `doc/.../rest/dispatcher-deferred-dependencies.md` R05 | 归属描述同步 | rewrite | 见 §7 P2 |

## 6. 删除清单

| 删除项 | 理由 |
|--------|------|
| `dispatcher/execution/waypoint.py` 整模块 | 实现按使用者下沉到两个家族；共享平面不再承载该能力（用户裁定） |
| `execution/composition.py` 对 `execution.waypoint` 的 import | 随模块删除；改由家族模块引入 |
| 测试中对 `dispatcher.execution.waypoint` 的 import | 随模块删除；改指家族模块 |

> 不删除：`execution/ports.py`、`execution/skill_host.py`、`execution/composition.py`
> （见 §3 Non-Goals）。

## 7. 实施步骤（P0–P2 分期）

### P0 — 契约先行

- 范围：
  - `S/implemented/inner/l3-execution-seam.spec.md`：
    - §1（#L12-L14、#L20-L22）：把「跨工具共享的动作发送、批次关联、反馈、
      超时与取消」从共享执行能力改为**归使用它的工具家族**，并登记
      `tools/<family>/waypoint.py` 为家族执行实现位置；
    - §4（#L65-L68）：把「执行缝不感知工具语义」改为对**共享动作端口**的约束，
      并明确「航点下发的执行实现归家族，不集中到共享平面」；
    - §4（#L59-L62）：保留「通用动作端口定义于 `execution/ports.py`，飞行与 VLA
      共用」不变；
    - §6 G11（#L86-L88）：约束面扩到 `execution/` **与**各家族 `waypoint.py`；
    - §7（#L90-L106）：行为边界不变，仅把归属表述对齐。
  - `S/implemented/inner/l3-package-layout.spec.md`：
    - §1（#L24、#L30-L31）：`execution/` 职责改为「共享动作端口、家族宿主与装配」；
    - §2（#L44）：执行缝模块命名示例由 `execution/waypoint.py` 改为
      `execution/ports.py`，并新增一行「模块（家族执行）| 领域名词，不带家族前缀
      | `tools/<family>/waypoint.py`」；
    - §3（#L72-L78、#L82-L83）：确认 `tools/<family>/` 允许 import
      `execution/ports.py`（已允许，无需改）；补充 `execution/composition.py`
      允许 import 家族 `waypoint` 的装配根地位（已由 #L72 覆盖）。
- 行为不变式：不动生产代码路径。
- 验收：spec 内条文自洽，无「共享执行」与「家族执行」并存矛盾。
- 回退：文档级回退。

### P1 — 实现下沉 + 装配改线（一次不可分割改动）

- 范围：
  - 新增 `N/tools/flight/waypoint.py`：逐字移植旧 `WaypointExecution`；
  - 新增 `N/tools/vla/waypoint.py`：逐字移植旧 `WaypointExecution`；
  - 改 `N/execution/composition.py`：分别 import 两份并用于
    `install_flight` / `install_vla`；同步 docstring；
  - 改 `N/execution/skill_host.py`：仅同步 `VlaSkillHost` docstring 措辞；
  - 改 `N/execution/__init__.py`：平面自述收缩；
  - **删除** `N/execution/waypoint.py`。
- 行为不变式：批次、进度判据、超时、取消/保持、`send_goal` 唯一写入口、
  两条 `WaypointExecution` 实例互不干扰（随机 batch 起始）全部不变。
- 验收：`grep -rn "execution.waypoint" N/` 零命中（测试除外，P2 处理）；
  静态 import 自检通过。
- 回退：git（同轮整体回退）。

### P2 — 测试面与台账同步

- 范围：
  - 同步 `tests/basic-flight/test_flight.py`、`tests/core-boundary/test_vla_skill.py`、
    `tests/core-boundary/test_vla_skill_host.py`、`tests/core-boundary/test_vla_composition.py`、
    `tests/ros/test_ego_cmd.py` 中的 import 与断言目标；
  - 同步 `doc/l3-dispatcher-planner/rest/dispatcher-deferred-dependencies.md` R05
    的归属描述（执行缝 → 家族执行），保留其记录消费挂账结论；
  - 完成时归档 `specs/implemented/architecture/2026-09-21-waypoint-execution-family-ownership.md`。
- 行为不变式：不因测试改动改生产行为。
- 验收：见 §8。
- 回退：git。

## 8. 验收标准

> **统一声明**：除非使用者明确许可，否则跳过验收测试工作（`AGENTS.md` 硬性约束 §9）。

- [ ] `grep -rn "dispatcher.execution.waypoint\|execution\.waypoint" l3-dispatcher-planner/`
      零命中。
- [ ] `l3-dispatcher-planner/ros_packages/dispatcher/dispatcher/execution/waypoint.py`
      不存在。
- [ ] `tools/flight/waypoint.py` 与 `tools/vla/waypoint.py` 存在，且与旧实现
      逐字等价（`diff` 或 AST 等价核对）。
- [ ] 两份实现的公开签名与旧实现一致：
      `__init__/state/start/poll/cancel/stop`。
- [ ] `composition.py` 的 `install_flight` / `install_vla` 分别使用家族份；
      两者实例独立（`first_batch` 随机起始）。
- [ ] 行为不变式回归：`waypoint_skipped` / `planner_timeout` /
      `execution_cancel_pending` / `execution_not_cancelled` /
      `action_generation_exhausted` 等既有语义词零变化。
- [ ] spec 自洽：`l3-execution-seam.spec.md` 与 `l3-package-layout.spec.md` 中
      不再把航点下发执行描述为共享执行能力。
- [ ] 台账 R05 归属描述已同步，且未关闭其记录消费挂账。
- [ ] 隐私门禁：新增/修改的 `*.md` 无主机绝对路径与个人用户名。

## 9. 风险与对策

| 风险 | 影响 | 对策 |
|------|------|------|
| 两份相同实现（DRY 违背） | 后续修 bug 需双改，易漏 | 用户已明确接受「哪怕相同」；§4.3 以「行为不变式」约束两份等价；P1 用 diff/AST 核对强制等价 |
| 迁移后两份悄悄分叉 | 飞行与 VLA 行为不一致 | 两份差异只能来自**显式**的后续方案；本轮要求逐字等价并在 §8 设核对项 |
| `execution/` 平面语义被掏空后名不符实 | 契约自相矛盾 | P0 同步改 §1/§2 条文，把平面重定义为「共享动作端口 + 家族宿主 + 装配」 |
| 用户后续要求连 `ports.py`/`skill_host.py` 一并下沉 | 需二次迁移 | §3 Non-Goals 已明示边界与理由；如裁定变更，另立方案 |
| 适配层 `RosFlightPorts` 的 `FlightPorts` 实现目标混淆 | import 断裂 | 本方案不下沉 `ports.py`，适配层 import 路径不变 |
| 测试 import 断裂 | 收集失败 | P1 与 P2 分两步，P2 集中改测试面 |
| 遗漏其他 `waypoint` 引用点 | 运行期 ImportError | P1 验收设全树 grep 零命中 |
| 台账未同步 | 迁移记录断链（`AGENTS.md` §64-75） | P2 同轮更新 R05 与索引 |

## 10. 修改点清单汇总

| 文件 | 动作 | 说明 |
|------|------|------|
| `specs/implemented/inner/l3-execution-seam.spec.md` | 修改 | §1 归属表、§4 端口/语义边界、§6 G11、§7 措辞 |
| `specs/implemented/inner/l3-package-layout.spec.md` | 修改 | §1 平面表、§2 命名示例、§3 依赖方向确认 |
| `specs/implemented/inner/l3-skill-contract.spec.md` | 核对 | §10 引用路径不变则不改 |
| `.../dispatcher/tools/flight/flight_waypoint.py` | 新增 | 飞行份 `FlightWaypointExecution`（逐字等价） |
| `.../dispatcher/tools/vla/vla_waypoint.py` | 新增 | VLA 份 `VlaWaypointExecution`（逐字等价） |
| `.../dispatcher/execution/waypoint.py` | 删除 | 实现下沉；不留转接器 |
| `.../dispatcher/execution/composition.py` | 修改 | 分别 import 两份；docstring 去「共享」表述 |
| `.../dispatcher/execution/skill_host.py` | 修改 | 仅 `VlaSkillHost` docstring 措辞 |
| `.../dispatcher/execution/__init__.py` | 修改 | 平面自述收缩 |
| `.../dispatcher/execution/ports.py` | 不变 | 共享动作端口保留 |
| `.../tests/basic-flight/test_flight.py` | 修改 | import 指向家族模块 |
| `.../tests/core-boundary/test_vla_skill.py` | 修改 | 同上 |
| `.../tests/core-boundary/test_vla_skill_host.py` | 修改 | 同上 |
| `.../tests/core-boundary/test_vla_composition.py` | 修改 | 同上 |
| `.../tests/ros/test_ego_cmd.py` | 修改 | 同上 |
| `doc/l3-dispatcher-planner/rest/dispatcher-deferred-dependencies.md` | 修改 | R05 归属描述同步 |
| `specs/implemented/architecture/2026-09-21-waypoint-execution-family-ownership.md` | 新增 | done 时归档 |

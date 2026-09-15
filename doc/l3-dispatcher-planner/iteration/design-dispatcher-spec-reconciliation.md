# dispatcher 契约修订（消解自相矛盾与不可判定）方案

> 摘要：本文件是总纲 `doc/l3-dispatcher-planner/iteration/design-dispatcher-architecture-stabilization.md`
> 的 **S1 期执行方案**。S1 只改契约（`specs/`，外加默认目标树之外的 `AGENTS.md`），
> 消除 5 项「自相矛盾 / 不可判定 / 未接线」：B3↔R1/R4 相容化、G2 可判定化、
> `AGENTS.md` 硬约束 1 措辞收敛、决策记录落点接线、有意对外变更登记。
> 本方案只给出**逐字修订片段（old → new）**，不实际改契约；执行时按片段照字落盘。
>
> **执行前须取得用户显式放行**：`specs/` 不在默认编辑目标树（`l3-dispatcher-planner/`）
> 内，`AGENTS.md` 亦不在默认目标树内（总纲 §3「spec 改动需显式放行」、§4.7 S1 行）。

## 0. 元信息

| 项 | 值 |
|----|----|
| 日期 | 2026-09-12 |
| 目标路径 | `specs/implemented/inner/l3-core-boundary.spec.md`、`specs/implemented/inner/l3-ros-adapter-boundary.spec.md`、`specs/implemented/inner/l3-migration-protocol.spec.md`、`specs/README.md`（均需放行）；`AGENTS.md`（默认目标树之外，需放行） |
| 状态 | done（2026-09-12 执行完毕，见 §11 附录） |
| 前置 | S0（措辞统一，见总纲 §4.7） |
| 行为影响 | 纯契约与文档；零代码改动 |
| 关联文档 | 总纲 `doc/l3-dispatcher-planner/iteration/design-dispatcher-architecture-stabilization.md`（§2.A、§2.C、§4.4、§4.5、§4.6、§4.7、§7 S1、§10）；模板 `_TEMPLATE.md`；姊妹篇 S0 `design-dispatcher-privacy-gate-cleanup.md`、S6 `design-dispatcher-dispatch-fail-semantics.md` |
| 契约依据 | `specs/implemented/l3-dispatcher.spec.md`、`specs/implemented/inner/l3-core-boundary.spec.md`、`specs/implemented/inner/l3-ros-adapter-boundary.spec.md`、`specs/implemented/inner/l3-migration-protocol.spec.md`、`specs/implemented/inner/l3-skill-contract.spec.md`、`specs/README.md`、`AGENTS.md` |
| 需放行 | **是**：`specs/` 与 `AGENTS.md` 均不在默认编辑目标树内 |

## 1. 背景与动机

契约—代码一致性审计（总纲 §2）给出两条结论：契约层方向正确，但存在 3 类**契约自身缺陷**：

1. **两条叶契约自相矛盾**：`l3-core-boundary` B3 允许 core 持有四类发布器，
   `l3-ros-adapter-boundary` R1/R4 又规定「领域层出现 Publisher 即缺陷」——同一份
   `engine.py` 同时违反其中之一，任何代码判定都无解（总纲 §2.A、§4.5）。
2. **门禁不可判定**：`l3-core-boundary` §4 的 G2 第二子句是「core 的 `def` 数不超过
   **约定阈值**」，无数值，无法脚本化（总纲 §2.C）。
3. **措辞与落点未接线**：`AGENTS.md` 硬约束 1 的措辞把「公开服务标识（GitHub 仓库 URL/
   仓主名）」也一并禁掉，与 `github-issue`/`github-pull` 必须写公开仓库地址冲突；
   `l3-migration-protocol` §7 要求「方案归档为决策记录」，但 `specs/README.md` 声明的
   `implemented/architecture|process/` 未被任何流程落点引用（总纲 §2.C）。

契约修订应遵循总纲 §3 的裁决：**消除自相矛盾（两条都保留且更强）、把不可判定改为可判定、
措辞收敛**——而非「改契约迁就现状」。S1 执行后，S4/S5/S6 才具备可判定的判据。

## 2. 现状事实（问题清单）

> 行号为本次实测（引用文件 + 行号 + 引文）。

### 2.1 B3 ↔ R1/R4 自相矛盾（总纲 §2.A、§4.5）

- [ ] `specs/implemented/inner/l3-core-boundary.spec.md#L31-L32` —

  ```
  - **B3 无领域端点**：core 只允许持有四类发布器——急停、`if_handle_yaw`、
    任务相位、命令内容监控。其余主题由技能或适配层自建。
  ```
- [ ] `specs/implemented/inner/l3-ros-adapter-boundary.spec.md#L27-L28` —

  ```
  - **R1 收发集中**：`rospy` / `roscpp` 的 Subscriber、Publisher、Service、
    ActionClient、ActionServer 只能出现在适配层文件。领域层出现任一处即缺陷。
  ```
- [ ] 现状代码侧锚点（不改，仅证明冲突真实）：`l3-dispatcher-planner/ros_packages/dispatcher/dispatcher/engine.py#L208-L224`
  在 `engine.py`（领域 core）内直接构造 4 个 `rospy.Publisher`——按 B3 合法，按 R1 是缺陷。

### 2.2 G2 第二子句不可判定（总纲 §2.C、§4.4）

- [ ] `specs/implemented/inner/l3-core-boundary.spec.md#L60` —

  ```
  | G2 | `DISPATCHER_STATE` 成员数 == 6，且 core 的 `def` 数不超过约定阈值（B4） |
  ```
- [ ] 第一子句可判：`l3-dispatcher-planner/ros_packages/dispatcher/dispatcher/state.py#L25-L31`
  的 `DISPATCHER_STATE` 成员为 `INIT / WAIT_FOR_MISSION / DISPATCH / WAIT_ACTION_FINISH /
  STOP / POST_ACTION`，恰 6 个。
- [ ] `B4`（`l3-core-boundary.spec.md#L33`）「`DISPATCHER_STATE` 成员数固定为 6；新增状态须先改本契约」——
  故 G2 是 B4 的判定，但「约定阈值」无定义。

### 2.3 `AGENTS.md` 硬约束 1 措辞冲突（总纲 §2.C）

- [ ] `AGENTS.md#L68-L70` —

  ```
  1. **文档不写个人凭据**：`*.md`（spec、docs、本文件）只写角色名；
     个人用户名、密码、令牌绝不进入纳入版本控制的文件，只放在被忽略的
     主机本地区（如 `.local.env`）。
  ```
- [ ] 冲突事实：`AGENTS.md#L90-L94`（Issues 节）与 `.trae/skills/github-{issue,pull}/SKILL.md`
  的默认仓库即公开服务标识，必须入库——硬约束 1 的措辞若按字面包含「仓主名」，则
  这些文件全部违规（总纲 §2.C、S0 方案 §4「保留」列）。

### 2.4 决策记录落点未接线（总纲 §2.C）

- [ ] `specs/README.md#L11-L24` 声明生命周期布局，含 `implemented/architecture/yyyy-mm-dd-*.md`、
  `implemented/process/yyyy-mm-dd-*.md`、`proposed/`、`rejected/`、`archived/`、`tools/`。
- [ ] 但仓库中 `specs/` 只有 `README.md` 与 `implemented/{*.spec.md,inner/*.spec.md}`；
  上述目录均不存在（各轮方案全部落在 `doc/l3-dispatcher-planner/iteration/`）。
- [ ] `specs/implemented/inner/l3-migration-protocol.spec.md#L87-L94`（§7 交付物与归档）中，
  §7 **未点名归档路径**（`implemented/architecture/`），与 `specs/README.md` 的布局脱节；
  其第二句原文为「方案执行完毕后，其"为什么这样变"的部分归档为决策记录，方案本身不再
  作为权威」。

### 2.5 有意对外变更未登记（`l3-migration-protocol` §3）

- [ ] `specs/implemented/inner/l3-migration-protocol.spec.md#L48-L49`（§3 准入条件末条）：

  ```
  - 若本轮会变更对外行为契约（主题名、服务名、action 名、消息字段名、
    结构化日志事件名），已明确登记为有意变更并给出兼容处置。
  ```
- [ ] 待登记的对外变更锚点：
  - 工具发现面：`l3-dispatcher-planner/ros_packages/dispatcher/dispatcher/tools/model.py#L107-L108`
    有 `_meta.lx.task_id`；`dispatcher/tools/registry.py#L252-L261` 的 `list_tools()` 中
    `revision = "sha256:" + sha256(canonical)`，其中 `canonical` 由 `spec.public_dict()` 序列化
    ——删除 `_meta` 键必然改变 `revision`。
  - 调用 ack 与事件：`dispatcher/tools/runtime.py#L136`（ack 内 `"task_id": call.task_id`）、
    `#L413`（`tool_event` 内 `"task_id": call.task_id`）。
  - 未注册分发的对外结果：`dispatcher/engine.py#L572` 未命中即 `_advance_to_next_prompt()`，
    队尽时 `#L398-L403` 上报 `phase="done"`。

## 3. 目标与约束

- **目标**：
  1. 消除 B3↔R1/R4 自相矛盾（两条契约都保留，B3 加限定 + R1 增指引）；
  2. 把 G2 第二子句改为**可判定的 AST 方法白名单**，并给出与 S3 目标形态一致的清单；
  3. 收敛 `AGENTS.md` 硬约束 1 的措辞，区分「主机本地凭据与机器特定值」与「公开服务标识」；
  4. 给决策记录落点接线（`doc/…/iteration/` = 过程方案、`specs/implemented/architecture/` =
     冻结决策记录），并给出最小模板与触发时机；
  5. 登记 3 件有意对外变更，供 S5/S6 引用（**只登记，不改契约正文**）。
- **Non-Goals**：
  - 不改任何不变量的**语义**（状态数、四裁决、终态唯一、无任务编号等），只消歧与改判定；
  - 不改代码、不改测试；
  - 不迁移 `specs/tools/*` 门禁脚本（登记为后续轮次，总纲 §4.4 尾注）；
  - 不新建 `implemented/architecture/` 空目录或占位文件（不留桩，见 §4.4）。
- **硬边界**：
  - 禁止转接器：不为桥接新旧措辞新造「兼容条款」，旧条款被逐字替换（AGENTS.md 硬约束 5）；
  - 过期必删：被替换的旧措辞直接删除，不留「原表述亦有效」式注释（硬约束 6）；
  - 文档一律简体中文（硬约束 8）；不写主机绝对路径与个人标识（硬约束 1、`topology` 不变量）；
  - 契约优先：修订只在 `specs/` 与 `AGENTS.md` 落地，不得散落为项目本地契约（硬约束 5）。

## 4. 方案决策

> 每项给：现状（文件 + 行号 + 引文）、判定、修订后逐字文本、影响面、非「迁就现状」论证。

### 4.1 项 1：B3 ↔ R1/R4 相容化（总纲 §4.5）

**判定**：两条契约都**正确但表述不完整**。B3 的「四类发布器」应理解为 **core 的对外通道
语义白名单**（限制 core 变通信聚合点），它**不豁免** R1/R2/R4；四类通道的 ROS 实现必须落
适配文件（S3 后为 `ros_adapter/core_channels_ros.py`），core 只持有端口引用。修两处措辞即可
相容，无需删除任一契约。

**修订 4.1a — `specs/implemented/inner/l3-core-boundary.spec.md#L31-L32`**

old（逐字）：

```
- **B3 无领域端点**：core 只允许持有四类发布器——急停、`if_handle_yaw`、
  任务相位、命令内容监控。其余主题由技能或适配层自建。
```

new（逐字）：

```
- **B3 无领域端点**：core 的对外通道是**语义白名单**，固定为四类——急停、
  `if_handle_yaw`、任务相位、命令内容监控。该白名单**不豁免**
  `l3-dispatcher/ros-adapter-boundary` R1/R2/R4：四类通道的 ROS 实现必须落在
  适配文件，core 只持有端口引用。其余主题由技能或适配层自建。
```

**修订 4.1b — `specs/implemented/inner/l3-ros-adapter-boundary.spec.md#L27-L28`**

old（逐字）：

```
- **R1 收发集中**：`rospy` / `roscpp` 的 Subscriber、Publisher、Service、
  ActionClient、ActionServer 只能出现在适配层文件。领域层出现任一处即缺陷。
```

new（逐字，追加 R1 指引，不改 R1 本句）：

```
- **R1 收发集中**：`rospy` / `roscpp` 的 Subscriber、Publisher、Service、
  ActionClient、ActionServer 只能出现在适配层文件。领域层出现任一处即缺陷。
  `l3-dispatcher/core-boundary` B3 的四类通道（急停 / `if_handle_yaw` /
  任务相位 / 命令内容监控）是 core 的语义白名单，同样适用本规则：其 ROS
  实现落在适配层文件，core 只持有端口引用。
```

**影响面**：
- G4（四类白名单）语义不变，仍判「core 发布器集合 ⊆ 四类」；
- G7 对 `engine.py` / `core/` 生效：S4 完成后 `ros_adapter/core_channels_ros.py` 是四类通道
  唯一合法落点（总纲 §4.5「影响」、§4.1 目标树）；
- S3/S4 的拆分边界由此确定（四类通道一次性落适配文件，避免二次搬迁）。

**非「迁就现状」论证**：本修订**不放宽**任何一条，反而**收紧**：B3 从「允许 core 持有
发布器」变成「白名单 + 必须走端口」，R1 从「未覆盖 core 四通道」变成「明确覆盖」。
备选「删除 B3 白名单」被否决（总纲 §4.5），因其丢失「限制 core 对外通道数量」这条约束。

### 4.2 项 2：G2 第二子句可判定化

**判定**：把「`def` 数不超过约定阈值」改为 **AST 方法白名单**——判据从「数量」改为
「集合包含关系」，可脚本化且不随无关重构漂移。

**修订 4.2a — `specs/implemented/inner/l3-core-boundary.spec.md#L60`**

old（逐字）：

```
| G2 | `DISPATCHER_STATE` 成员数 == 6，且 core 的 `def` 数不超过约定阈值（B4） |
```

new（逐字）：

```
| G2 | `DISPATCHER_STATE` 成员数 == 6，且 core 的 `def` 集合 ⊆ 本契约 §4.1 白名单（B4） |
```

**修订 4.2b — 新增 §4.1 白名单小节**（插入位置：`l3-core-boundary.spec.md` §4 门禁表之后、
§5 迁移判定之前，即现 `#L65` 空行处）：

new（逐字）：

```
### 4.1 core 方法白名单（G2 判定基准）

> `def` 集合的作用域 = `engine.py` 与其协作模块 `core/**`（S3 起）；核心判据是
> 「集合包含」而非「数量」。白名单随契约修订维护：新增方法须先改本节。

| 模块 | 允许的 `def`（方法名） |
|------|------------------------|
| `engine.py` | `__init__`、`sync_task_buffers_from_prepare`、`_set_dispatcher_state`、`_state_name`、`_handle_get_pre_command`、`_load_next_prompt`、`_bump_task_generation`、`_enter_global_stop`、`_action_done`、`_advance_to_next_prompt`、`_reset_plan_cycle_if_needed`、`_handle_post_action`、`_run_inference_loop`、`_recover_inference_after_exception`、`run_inference`、`_fail_unregistered_dispatch`；`PendingAction.clear` |
| `core/telemetry.py`（`RunTelemetry`） | `__init__`、`emit`、`publish_command_content`、`fmt_wait_age`、`wait_diag` |
| `core/task_phase.py`（`TaskPhaseBridge`） | `__init__`、`publish`、`set_active_frame`、`set_middleware` |
| `core/skill_router.py`（`SkillRouter`） | `__init__`、`register`、`get`、`dispatch_plan`、`validate_active_tool`、`owner_skill`、`snapshot_owner`、`stash_task_result`、`pop_task_result` |
| `core/actuators.py`（`PlannerActuators`） | `__init__`、`set_if_handle_yaw` |
| `core/workflow.py`（`ToolWorkflowHost`） | `__init__`、`bind_tool_middleware`、`_activate_tool_call`、`start_tool_workflow`、`cancel_tool_call` |
| `core/ports.py`（端口 Protocol） | 见下条注 |

- 类标注以外的 `def` 节点：模块级装配函数（`create_dispatcher_engine` /
  `start_dispatcher_workers`）随装配职责落 `dispatcher_node.py`，**不计入 core**；
  嵌套 `def` 只允许 `_set_dispatcher_state._state_name`（状态名反查，随宿主方法）。
- `core/ports.py` 的 `Protocol` 端口声明方法：**待 S3 定稿**——该文件内容（B3 四类通道
  端口 Protocol 的具体签名与数量）由 S3 方案定稿后在此登记；建议门禁对 `Protocol`
  子类的 `def ...: ...` 声明整体豁免或按 S3 定稿清单白名单化。
```

**白名单来源与 S3 一致性**（`engine.py` 现有 31 个 `def` 节点的去向，实测行号）：

| 现位置（`engine.py`） | 节点 | S3 后归属 | 确定性 |
|---|---|---|---|
| `#L61` | `clear`（`PendingAction`，D3 暂留） | engine | 定稿 |
| `#L81` | `__init__` | engine | 定稿 |
| `#L229` | `sync_task_buffers_from_prepare` | engine | 定稿 |
| `#L256` | `_telemetry` | `core/telemetry.py::emit` | 待 S3 定稿（改名） |
| `#L260` | `publish_command_content` | `core/telemetry.py` | 待 S3 定稿 |
| `#L267` | `_set_dispatcher_state` | engine | 定稿 |
| `#L270` | `_state_name`（嵌套） | engine（随宿主） | 定稿 |
| `#L296` | `_fmt_wait_age` | `core/telemetry.py::fmt_wait_age` | 待 S3 定稿（改名） |
| `#L301` | `_decision_chain_wait_diag` | `core/telemetry.py::wait_diag` | 待 S3 定稿（改名） |
| `#L315` | `_publish_task_phase` | `core/task_phase.py::publish` | 待 S3 定稿（改名） |
| `#L366` | `_handle_get_pre_command` | engine | 定稿 |
| `#L390` | `_load_next_prompt` | engine | 定稿 |
| `#L410` | `_validate_active_tool` | `core/skill_router.py` | 待 S3 定稿 |
| `#L421` | `bind_tool_middleware` | `core/workflow.py` | 待 S3 定稿 |
| `#L432` | `_activate_tool_call` | `core/workflow.py` | 待 S3 定稿 |
| `#L448` | `start_tool_workflow` | `core/workflow.py` | 待 S3 定稿 |
| `#L515` | `cancel_tool_call` | `core/workflow.py` | 待 S3 定稿 |
| `#L536` | `_set_if_handle_yaw` | `core/actuators.py` | 待 S3 定稿（改名去 `_`） |
| `#L547` | `_handle_plan_tool` | `core/skill_router.py::dispatch_plan` | 待 S3 定稿（改名） |
| `#L576` | `_bump_task_generation` | engine | 定稿 |
| `#L586` | `_enter_global_stop` | engine | 定稿 |
| `#L632` | `pop_task_result` | `core/skill_router.py` | 待 S3 定稿 |
| `#L638` | `_action_done` | engine | 定稿 |
| `#L685` | `_advance_to_next_prompt` | engine | 定稿 |
| `#L705` | `_reset_plan_cycle_if_needed` | engine | 定稿 |
| `#L714` | `_handle_post_action` | engine | 定稿 |
| `#L759` | `_run_inference_loop` | engine | 定稿 |
| `#L981` | `_recover_inference_after_exception` | engine | 定稿 |
| `#L1000` | `run_inference` | engine | 定稿 |
| `#L1020` | `create_dispatcher_engine` | `dispatcher_node.py` | 定稿（不计入 core） |
| `#L1063` | `start_dispatcher_workers` | `dispatcher_node.py` | 定稿（不计入 core） |

> 协作模块的方法名取自 S3 方案 `design-dispatcher-engine-relocate-non-core.md` §4 接口形态与
> 总纲 §4.1 目标树；因 S3 执行版目标树「就地改写、以 S3 定稿为准」，上表标「待 S3 定稿」的
> 改名项在 S3 定稿后须与本白名单**同一改动**对齐（否则 G2 会判红）。`_fail_unregistered_dispatch`
> 为 S6 新增（见 S6 方案 §4.2），在本契约中先予登记。

**影响面**：G2 从「不可判」变为可脚本（AST 遍历 `engine.py` + `core/**`，取 `def` 名集合，
判 ⊆ 白名单）；总纲 §4.4 记「S1 改判定，S3 后判」。

**非「迁就现状」论证**：数量阈值对现状（core 待拆分）无法定值，任何具体数字都是
「按现状凑数」；改为**集合白名单**后，判据表达的是「core 只允许出现这些职责方法」，
比数量阈值更严且更抗重构——它是把 B4 的「状态数固定」精神延伸到方法面，不是放宽。

### 4.3 项 3：`AGENTS.md` 硬约束 1 措辞收敛

**判定**：硬约束 1 的本意是「**主机本地凭据与机器特定值**不入库」（密码/令牌/私钥、
主机绝对路径、个人用户名），但现行措辞把「公开服务标识」也罩了进去，与
`github-issue`/`github-pull` 必须写公开仓库地址的事实冲突（总纲 §2.C）。收敛为按
「凭据/机器特定值」与「公开服务标识」二分。

**修订 — `AGENTS.md#L68-L70`**

old（逐字）：

```
1. **文档不写个人凭据**：`*.md`（spec、docs、本文件）只写角色名；
   个人用户名、密码、令牌绝不进入纳入版本控制的文件，只放在被忽略的
   主机本地区（如 `.local.env`）。
```

new（逐字）：

```
1. **文档不写主机本地凭据与机器特定值**：`*.md`（spec、docs、本文件）只写
   角色名（`specs/implemented/inner/entity-naming.spec.md` 的实体词汇）；密码、
   令牌、私钥，以及主机绝对路径、个人用户名等**机器特定值**，绝不进入纳入
   版本控制的文件，只放在被忽略的主机本地区（如 `.local.env`）。**公开服务
   标识**——公开仓库 URL 与其仓主名、服务角色名——不属凭据，可入库。
```

> 该文件属**非默认目标树**，执行前须显式放行（总纲 §4.7 S0/S1 行）。若未放行，本项保持
> 未完成并登记，不得降级为永久豁免。

**影响面**：S0 的 A4 门禁（总纲 §4.4）判据须表述为「凭据/机器特定值零命中；公开仓库 URL
除外」；`.trae/skills/github-{issue,pull}/SKILL.md` 的公开仓库标识为**保留项**。

**非「迁就现状」论证**：这不是给现状开绿灯，而是**修正一句过宽的定义**：真正的不可协商项
（密码/令牌/主机路径/个人用户名）一条不减，且新增「机器特定值」以覆盖 `topology` 不变量
（「任何个人或机器特定的具体主机值都不进入纳入版本控制的文档」，`topology.spec.md#L14`）。

### 4.4 项 4：决策记录落点接线

**判定**：`doc/l3-dispatcher-planner/iteration/` 是**过程方案（非权威）**；
`specs/implemented/architecture/` 是**冻结决策记录**（`specs/README.md#L17-L18` 已定义该布局）。
接线动作：把 `l3-migration-protocol` §7 点名的归档路径补上，并在 `specs/README.md` 明确
「生命周期目录按需创建、不预建空目录」（回应总纲 §2.C「声明了但不存在」）。

**修订 4.4a — `specs/implemented/inner/l3-migration-protocol.spec.md#L87-L94`（§7）**

old（逐字）：

```
## 7. 交付物与归档

- 每轮产出一份方案，落 `doc/l3-dispatcher-planner/iteration/`，格式遵循
  该目录模板；
- 方案执行完毕后，其"为什么这样变"的部分归档为决策记录，方案本身不再
  作为权威；
- 工作区不留中间产物；临时快照放主机本地，不入库；
- 提交前执行隐私检索，个人凭据零命中。
```

new（逐字）：

```
## 7. 交付物与归档

- 每轮产出一份方案，落 `doc/l3-dispatcher-planner/iteration/`，格式遵循
  该目录模板；该方案是**过程材料，非权威**；
- 方案执行完毕（该轮状态置 `done`）时，在**同一改动内**把其"为什么这样变"的
  部分归档为决策记录，落 `specs/implemented/architecture/yyyy-mm-dd-<topic>.md`
  （工作流/工具类决策落 `specs/implemented/process/`；布局见 `specs/README.md`
  §生命周期布局）。决策记录冻结、不再维护，方案的其余部分不迁移；
- 工作区不留中间产物；临时快照放主机本地，不入库；
- 提交前执行隐私检索，个人凭据零命中。
```

**修订 4.4b — `specs/README.md`（`#L24` 代码块之后追加说明）**

old（逐字，生命周期布局代码块收尾行）：

```
└── tools/            纳入版本控制的门禁引擎（尚未迁移）
```

new（逐字，代码块收尾行之后追加一段规则）：

```
└── tools/            纳入版本控制的门禁引擎（尚未迁移）
```

> **生命周期目录按需创建**：未被使用的目录（如尚无决策记录的
> `implemented/{architecture,process}/`、空的 `proposed/` / `rejected/` /
> `archived/`）**不预建空目录、不预置占位文件**；首个记录落入时随该改动创建。
> 过程方案留在 `doc/` 下，不占 `specs/` 的权威。

**决策记录最小模板**（执行时随首个归档落盘；对齐 `specs/README.md#L39-L57` 的 header 与
`Supersedes` 约定）：

```
# <yyyy-mm-dd> <决策标题>

Status: implemented
Supersedes: <可选，指向被取代记录的相对路径>

## 背景
<结构为何需要变化>

## 决策
<钉死的目标形态>

## 放弃的备选与理由
<被否决项及其原因>

## 影响
<随之判定的门禁/契约条目>
```

**触发时机**：某一轮方案从 `in-progress` 置 `done` 的**同一次改动内**归档；归档后该方案
在 `doc/` 下保留为过程材料、不再作为权威（对应 `specs/README.md#L50-L57`「冻结的决策记录」
与 `l3-migration-protocol` §7）。

**影响面**：`l3-migration-protocol` G18（§8）不受影响（目标契约已存在）；本轮不创建任何
目录（避免空目录=桩，违反 §4.1「不留桩」）；归档动作登记为后续轮次（总纲 §10 尾注）。

**非「迁就现状」论证**：本裁决不改「方案落 `doc/`、决策记录落 `specs/`」这一权威分层，
只把 §7 未点名的路径**补成可执行**、把 README 的布局与「不留桩」原则对齐；它消除的是
「声明了目录却无人落点」的**接线缺口**，而非承认 `doc/` 方案是权威。

### 4.5 项 5：有意对外变更登记（供 S5/S6 引用）

> 依 `l3-migration-protocol.spec.md#L48-L49`（§3）登记；依 §5 第 2 项（`#L70-L71`）
> 「待办登记在该轮方案或 issue 中，**不进契约**」——**本节只登记，不改任何契约正文**
> （总纲 §4.6 亦以「不进契约正文」为口径）。

| # | 变更内容 | 影响方 | 兼容处置 | 回归手段 |
|---|----------|--------|----------|----------|
| (a) | 工具发现面去除 `_meta["lx.task_id"]`（`tools/model.py#L107-L108`），并因 `list_tools()` 的 `revision` 由 `public_dict()` 序列化得出（`tools/registry.py#L252-L261`）而**随之变化** | 发现面消费方：**已取证 l4 不使用发现面**（`agent-station-rpc.spec.md`「Discovery is unnecessary: the method table is static and known to both sides」）→ 无现实消费方，仅为文档面登记 | 该字段为 l3 内部编号，非路由依据；除去该键后 `revision` 的新值在 S5 显式断言（总纲 §4.7 S5 行） | S5 验收断言 `list_tools()["revision"]` 的新值 + `tools` 数组逐项不再含 `_meta.lx.task_id` |
| (b) | 调用 ack（`tools/runtime.py#L136`）与工具事件（`tools/runtime.py#L413`）去除 `task_id` 字段 | 站端：**已取证 l4 零消费**（ack 只读 `accepted`，outcome 只读 `call_id`/`outcome`）→ 无现实消费方 | `call_id` / `frame_id` / `step_id` 等既有标识保留；**wire 从不携带该字段**（旧库 `agent-station-tools.spec.md#L25`「task ids never appear on the wire」+ l4-agent 出站 payload 取证）→ **无适配层丢弃动作**，S5 只删 l3 本地派生 | S5 行为契约 diff：ack/event 的键集删去 `task_id`，其余键与取值不变 |
| (c) | 未注册分发的对外结果由 `done` 改为 `fail`（`engine.py#L572` 未命中推进 → `#L398-L403` 队尽 `done`） | 站端（`/agent_task_phase` 消费方） | `fail` 相位载荷**携带未命中的工具名**（满足 `l3-core-boundary` O3，`#L50-L51`），站端可定位缺失技能；与 l4 侧确认后执行（总纲 §9 S6 风险行） | S6 验收：失败相位 payload 断言（见 S6 方案 §8）+ 误伤检查（正常 ADVANCE 仍发 `done`） |

**影响面**：S5 与 S6 引用本节作为「已登记的有意变更」依据；G21（行为契约字符串级 diff 与登记
一致，`l3-migration-protocol.spec.md#L103`）据此判定。

**非「迁就现状」论证**：登记不是放宽契约，而是把**必然发生**的对外变更提前显式化；三项均
指向「去掉任务编号」与「禁止假成功」两条契约方向（`l3-dispatcher.spec.md#L21-L26`），是
实现向契约收敛的**结果**，而非契约向实现妥协。

### 4.6 项 6（新增）：B7 收口——禁止 l3 自产编号

- **现状**（`l3-core-boundary.spec.md#L38-L39`）：`B7 编号零残留：l3 任何模块都不得定义、传递或存储任务编号。若上游调用协议仍携带该字段，由适配层在入口处丢弃，不得进入领域层。`
- **问题**：第二句预设"上游有该字段"。取证（旧库 l4-agent 出站 payload + `agent-station-tools.spec.md#L25`「task ids never appear on the wire」）表明 wire 从不携带，编号 **100% 由 l3 自产**（`tools/registry.py` 的 `ToolSpec.task_id` → `dispatcher/rpc_plane.py#L387` 注入内部准入 payload）。现文可由"不得定义、传递"间接覆盖，但字面未点名"由工具名派生编号再注入内部载荷"这条路径，实践中易被误读为"只要不从 wire 读就合规"。
- **修订（old → new，逐字）**：
  - old：`B7 编号零残留：l3 任何模块都不得定义、传递或存储任务编号。若上游调用协议仍携带该字段，由适配层在入口处丢弃，不得进入领域层。`
  - new：`B7 编号零残留：l3 任何模块都不得定义、传递或存储任务编号，也不得自产（含由工具名、能力名或配置派生编号后注入内部载荷）。若上游调用协议仍携带该字段，由适配层在入口处丢弃，不得进入领域层；wire 未携带该字段时，适配层亦不得补造。`
- **性质**：**收紧**（补明确禁止的路径），非放宽；G5 判定面不变（全域零命中）。
- **影响面**：S5 子方案 §4.4（已按"删本地派生、不做 wire 丢弃"落地）获得契约字面支撑；`l3-migration-protocol` §4「禁止引入中间表示」无需改动。

### 4.7 项 7（新增）：`l3-skill-contract` §7 端口清单粒度注记

- **现状**：`l3-skill-contract.spec.md` §7 表列 11 个端口（"队列机械操作""代次守卫"各占一行），而本契约指定的参考实现 `dispatcher/skill_api.py` 的 `SkillHost` 对应成员为 13 项（`consume_head_prompt` / `advance_prompt` 两项；`capture_task_generation` / `task_generation_valid` 两项）。
- **问题**：语义无冲突；但 §7 声明"缺失即缺陷，由门禁判定"，粒度不一致使门禁无法机械判定齐全性。
- **修订（§7 表后追加一句；表内各行不动）**：
  - new：`> 端口名以参考实现 `skill_api.py` 的 `SkillHost` 成员为准；本表按语义分组，一行可能对应多个成员（如"代次守卫"= `capture_task_generation` + `task_generation_valid`，"队列机械操作"= `consume_head_prompt` + `advance_prompt`）。门禁据此判定齐全性。`
- **性质**：澄清粒度，不改端口集合与语义，不新增/删除端口。

## 5. 迁移映射表（旧条款 → 新条款）

| 文件 | 行（实测） | 旧条款 | 新条款 | 动作 |
|------|-----------|--------|--------|------|
| `specs/implemented/inner/l3-core-boundary.spec.md` | `#L31-L32` | B3「只允许持有四类发布器」 | §4.1a 修订版（语义白名单 + 明确不豁免 R1） | 修改 |
| `specs/implemented/inner/l3-ros-adapter-boundary.spec.md` | `#L27-L28` | R1（未覆盖 core 四通道） | §4.1b 修订版（追加 B3 指引） | 修改 |
| `specs/implemented/inner/l3-core-boundary.spec.md` | `#L60` | G2「`def` 数不超过约定阈值」 | §4.2a 修订版（`def` 集合 ⊆ §4.1 白名单） | 修改 |
| `specs/implemented/inner/l3-core-boundary.spec.md` | `#L65` 前 | （无 §4.1 白名单） | §4.2b 新增 §4.1 core 方法白名单 | 新增小节 |
| `AGENTS.md` | `#L68-L70` | 硬约束 1 旧措辞 | §4.3 修订版（凭据/机器特定值 vs 公开服务标识） | 修改（需放行） |
| `specs/implemented/inner/l3-migration-protocol.spec.md` | `#L87-L94` | §7 未点名归档路径 | §4.4a 修订版（点名 `implemented/architecture/`） | 修改 |
| `specs/README.md` | `#L24` 后 | 无「按需创建」说明 | §4.4b 追加说明 | 修改 |

## 6. 删除清单（被替换条款）

| 删除项 | 理由 |
|--------|------|
| B3 原句「core 只允许持有四类发布器」（`l3-core-boundary.spec.md#L31-L32`） | 被 §4.1a 替换；避免与 R1/R4 并存产生歧义（不留兼容注释） |
| G2 原句「core 的 `def` 数不超过约定阈值」（`l3-core-boundary.spec.md#L60`） | 不可判定；被 §4.2a 集合白名单替换 |
| `AGENTS.md` 硬约束 1 原句「个人用户名、密码、令牌绝不进入」（`#L68-L70`） | 被 §4.3 替换；消除与公开服务标识的冲突 |
| `l3-migration-protocol` §7 第二句「归档为决策记录，方案本身不再作为权威」（`#L91-L92`） | 被 §4.4a 替换为点名路径与触发时机的版本 |

> 说明：不删除任何不变量的语义、不删除任何门禁编号（G1–G23 全保留）。

## 7. 实施步骤（S1 单期）

### P0 — 契约修订（需显式放行）

- 范围：§5 映射表全部 7 处改动；`specs/` 与 `AGENTS.md`，代码/测试零改动。
- 行为不变式：
  - 不变量语义零变更（状态数、四裁决、终态唯一、无任务编号）；
  - 门禁编号与检查项一一对应关系不变（仅 G2 的判定式变可判、G4/G7 语义不变）；
  - 修订后 `l3-core-boundary` 与 `l3-ros-adapter-boundary` 在同一份代码上**不再互斥**。
- 步骤：
  1. 落 §4.1a/§4.1b（B3↔R1 相容化）；
  2. 落 §4.2a/§4.2b（G2 可判定化 + §4.1 白名单）；
  3. 落 §4.3（`AGENTS.md` 措辞，需单独放行）；
  4. 落 §4.4a/§4.4b（决策记录落点接线）；
  5. 复核：对 `engine.py` 手工跑 G2 的等价 AST 检查（`def` 名集合 ⊆ §4.1 白名单），
     并 grep 确认两叶契约不再同时把 `engine.py` 的四个 Publisher 判为合法/缺陷。
- 回退：`git` 还原 `specs/` 与 `AGENTS.md`（纯文档/契约，无副作用）。

## 8. 验收标准

- [ ] **B3↔R1 相容**：`l3-core-boundary` B3 与 `l3-ros-adapter-boundary` R1 逐句复核——四类
      通道被明确要求「ROS 实现落适配文件、core 只持端口」，二者不再互斥。
- [ ] **G2 可判**：对 `engine.py`（S3 前）与 `engine.py + core/**`（S3 后）跑等价 AST 检查，
      输出 `def` 名集合，判 ⊆ §4.1 白名单；`DISPATCHER_STATE` 成员数 == 6（`state.py#L25-L31`）。
- [ ] **措辞二分可执行**：`AGENTS.md` 硬约束 1 修订后，「凭据/机器特定值」与「公开服务标识」
      边界可复述；`.trae/skills/github-{issue,pull}/SKILL.md` 的公开仓库标识为保留项。
- [ ] **落点接线**：`l3-migration-protocol` §7 点名 `specs/implemented/architecture/`；
      `specs/README.md` 含「生命周期目录按需创建」说明；仓库中**未新建**任何空目录。
- [ ] **登记在案**：§4.5 三项登记可被 S5/S6 引用；契约正文**未**出现这三项变更描述。
- [ ] **零回归**：`git diff --stat` 仅含 §5 列出的 4 个文件；代码/测试零改动。
- [ ] **门禁 G18（契约先行）满足方式**：G18（`l3-migration-protocol.spec.md#L100`）要求「本轮
      涉及的目标契约存在于 `specs/` 且状态为 `proposed` 及以上」——S1 修订的 4 份契约均为
      现有 `implemented` 文件，故 G18 天然满足；对下游期（S4/S5/S6），其目标形态（B3/R1 相容、
      G2 白名单、B5/`l3-migration-protocol` §4「禁止假成功」）在 S1 后**已在契约中可判**，
      G18 亦满足。S1 不新增契约、不引入未成型形态。

## 9. 风险与对策

| 风险 | 影响 | 对策 |
|------|------|------|
| 白名单「待 S3 定稿」项与 S3 执行版不一致 | G2 在 S3 后误判红 | S3 定稿时与本白名单**同一改动**对齐；白名单存于契约、由 S3 方案显式引用 |
| 修订被质疑「改契约迁就现状」 | 评审返工 | §4.1 收紧、§4.2 改判定不改语义、§4.3 修正过宽定义、§4.4 补接线——逐项给「非迁就」论证（本文件各节末） |
| `AGENTS.md` 未放行 | G2/措辞项半程 | 未放行时该项保持未完成并登记（不得降级为豁免），见 §4.3 注 |
| 归档目录被预建为空目录 | 违反「不留桩」 | §4.4b 明确「按需创建、不预建」；S1 不创建任何目录 |
| 登记项与后续 S5/S6 脱节 | 对外变更无据可依 | §4.5 表 + S6 方案显式引用 (c) 项 |

回滚路径：`git checkout -- specs/ AGENTS.md`（纯契约/文档，无副作用）。

## 10. 修改点清单汇总

| 文件 | 动作 | 说明 |
|------|------|------|
| `specs/implemented/inner/l3-core-boundary.spec.md` | 修改 | §4.1a B3、§4.2a G2、§4.2b 新增 §4.1 白名单、§4.6 B7 收口（禁自产编号）（需放行） |
| `specs/implemented/inner/l3-skill-contract.spec.md` | 修改 | §4.7 §7 端口粒度注记（端口名以 `skill_api.py` 为准）（需放行） |
| `specs/implemented/inner/l3-ros-adapter-boundary.spec.md` | 修改 | §4.1b R1 追加 B3 指引（需放行） |
| `specs/implemented/inner/l3-migration-protocol.spec.md` | 修改 | §4.4a §7 归档落点（需放行） |
| `specs/README.md` | 修改 | §4.4b 生命周期目录按需创建（需放行） |
| `AGENTS.md` | 修改 | §4.3 硬约束 1 措辞（默认目标树之外，需放行） |
| `doc/l3-dispatcher-planner/iteration/design-dispatcher-spec-reconciliation.md` | 新增 | 本方案（S1 执行方案） |

**本方案不动的文件**（明确排除，避免误改）：

- 全部代码与测试：`l3-dispatcher-planner/**`（含 `ros_packages/dispatcher/**`、`tests/**`）——零改动；
- `specs/implemented/l3-dispatcher.spec.md`、`specs/implemented/topology.spec.md`、
  `specs/implemented/development-workflow.spec.md`；
- 其余叶契约：`inner/l3-execution-seam.spec.md`、`inner/l3-skill-contract.spec.md`、
  `inner/l3-coding-style.spec.md`、`inner/entity-naming.spec.md`（`l3-skill-contract` §7 端口缺口
  由 S6 登记，不在 S1 改）；
- 已 `done` 的历史轮次方案：`design-dispatcher-core-inference-migration.md`、
  `design-dispatcher-engine-narrow-core-trim.md`、`design-dispatcher-zenoh-transport-migration.md`、
  `design-dispatcher-taskid-retirement-deps-migration.md`；
- `.trae/skills/**`（仅 S0 处理，且需放行）。

**登记的后续轮次**：`specs/tools/*` 门禁脚本迁移（S1 后 G2 的手工 AST 检查改由脚本承担）；
首个决策记录归档（`specs/implemented/architecture/`）。

## 11. 附录：执行记录

### 2026-09-12 执行（S1 置 done）

- **执行者**：SOLO Agent（主 Agent 直接执行；G-放行-2 已取得，用户放行 `specs/` 与 `AGENTS.md` 全部范围）。
- **执行实测**：§10 全部 6 个文件、9 处修订逐字落地——4.1a（B3 相容化）、4.1b（R1 追加指引）、4.2a（G2 可判定化）、4.2b（新增 §4.1 白名单）、4.3（`AGENTS.md` 硬约束 1 措辞二分）、4.4a（migration-protocol §7 归档落点）、4.4b（README 按需创建）、4.6（B7 收紧）、4.7（skill-contract 端口粒度注记）。
- **4.2b 白名单定稿口径**：按执行计划 §7.2 指令，`core/ports.py` 行以 S3 方案 §4.5 **冻结名**定稿（`CoreChannels`/`Ticker`/`RuntimeClock`/`LogSink` 的 12 个端口方法名），未保留原稿「待 S3 定稿」占位注记。
- **G2 等价 AST 检查实测**：`engine.py` 31 个 `def` 节点（去重）；扣除 2 个装配函数（`create_dispatcher_engine`/`start_dispatcher_workers`，不计入 core）后 core 作用域 29 个；residual 7 项：`_telemetry`、`_fmt_wait_age`、`_decision_chain_wait_diag`、`_publish_task_phase`、`_validate_active_tool`、`_set_if_handle_yaw`、`_handle_plan_tool` ——与 §4.2 映射表「待 S3 定稿（改名）」清单**逐项吻合**；按总纲 §4.4「S1 改判定，S3 后判」，该 residual 属预期，S3 执行时与本白名单同一改动对齐。`DISPATCHER_STATE` 成员数实测 6（`state.py#L25-L31`）。
- **B3↔R1 互斥消解复核**：修订后 B3 明确「白名单不豁免 R1/R2/R4、ROS 实现落适配文件、core 只持端口引用」，R1 明确「B3 四通道同样适用本规则」——同一份 `engine.py` 的四个 Publisher 现统一判为「S3 前的过渡态、S3 后为缺陷」，两契约不再互斥。
- **落点接线复核**：`l3-migration-protocol` §7 已点名 `specs/implemented/architecture/`；`specs/README.md` 已含「生命周期目录按需创建」；本轮**未新建**任何空目录。
- **登记在案**：§4.5 三项登记（(a) 发现面 `_meta`+`revision`、(b) ack/事件 `task_id`、(c) 未注册 done→fail）已可被 S5/S6 引用；契约正文未出现这三项变更描述（G-变更-1 满足）。
- **勘误（已回写正文）**：§5 迁移映射表原缺 §4.6/§4.7 两行（已补）；§8「零回归」原写「§5 列出的 4 个文件」与 §10 的 6 文件清单不一致（已按 §10 修正）。
- **零回归实测**：本轮代码/测试零改动；`git diff --stat` 中 `engine.py`、`tools/__init__.py` 为开工前既有改动（见 S0 附录），不计入本期。G18 天然满足（4 份目标契约均为现存 `implemented` 文件）。
- **门禁基线**：与 S0 附录同（py_compile 全量通过；pytest 44 通过 / 6 既有失败 / 1 文件因缺 `zenoh` 无法收集）。

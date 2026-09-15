# dispatcher 架构稳定方案执行计划（编排总表）

> 摘要：本文件是 `doc/l3-dispatcher-planner/iteration/` 下**全部 design 的执行编排**——唯一顺序、唯一状态总表、
> 每期入口/出口判据、放行门、执行流水线与门禁集合。它**不做架构决策**（决策归总纲 `design-dispatcher-architecture-stabilization.md`
> 与各期方案），也**不执行代码改动**；执行者按 §7 逐期推进，按 §4.5 回写状态。
>
> 定位：总纲 = 目标形态权威；各期方案 = 该期怎么做；**本文件 = 按什么顺序做、每期何时可开工、何时算完成**。

## 0. 元信息

| 项 | 值 |
|----|----|
| 日期 | 2026-09-12 |
| 目标路径 | `doc/l3-dispatcher-planner/iteration/`（本文件）；被编排对象见 §2 |
| 状态 | done（2026-09-12：S0–S7 全部执行完毕，状态总表见 §2；后续轮次登记见 §10 尾注与各方案附录） |
| 期 | 横跨 S0–S7（编排者，本身不产生代码/契约改动） |
| 关联文档 | 总纲：`design-dispatcher-architecture-stabilization.md`（目标形态唯一权威）；模板：`_TEMPLATE.md`；各期方案见 §2；已 done 历史见 §6 |
| 路径口径 | 全文相对路径；`PKG = l3-dispatcher-planner/ros_packages/dispatcher/`；路径形态以 **S2 后**（`utils/` 落位）为准 |

## 1. 背景与动机

现状：本目录已有 **13 份 design**（1 份模板 + 8 份活跃期方案 + 4 份 `done` 历史），且活跃方案之间存在前置关系与放行门（`S0`/`S1`/`S7` 需显式放行；`S2 → S3 → S4` 必须串行）。执行者打开目录后无法一眼判断：

1. 先从哪份开始、哪些能并行；
2. 每期开工的前置条件是什么、需要谁放行；
3. 每期做完如何判定"完成"、状态写到哪里；
4. 执行中途发现方案与总纲冲突、或行号漂移、或需要临时扩范围时怎么处置。

本文件把这四件事固化为可执行的编排，避免"按文档各自为政"导致的反复搬迁与状态漂移。

## 2. 现状事实（文档集清单与状态）

> 状态取自各文件 §0 元信息（本次实测行号）；本表是**唯一状态总表**，回写规则见 §4.5。

| 文档 | 期 | 状态（实测） | 前置 | 行为影响 | 放行 |
|---|---|---|---|---|---|
| `design-dispatcher-architecture-stabilization.md`（总纲） | 横跨 | proposed（`#L17`） | — | 无（约束与索引） | 否 |
| `design-dispatcher-privacy-gate-cleanup.md` | S0 | done（`#L16`，2026-09-12；附录见该方案 §11） | 无（可与 S1 并行） | 纯文档 | **是**（`AGENTS.md`、`.trae/skills/`，见 `#L19`；已放行） |
| `design-dispatcher-spec-reconciliation.md` | S1 | done（`#L18`，2026-09-12；附录见该方案 §11） | S0（措辞统一） | 纯契约 | **是**（`specs/`、`AGENTS.md`，见 `#L23`；已放行） |
| `design-dispatcher-package-topology.md` | S2 | done（`#L22`，2026-09-12；附录见该方案 §11） | S1 | 零行为（move + import） | 否 |
| `design-dispatcher-engine-relocate-non-core.md` | S3 | done（`#L29`，2026-09-12；deep-oracle 放行，附录见该方案 §11） | S2 | 零行为（位置迁移 + 端口注入 + 组合） | 否 |
| `design-dispatcher-ros-adapter-split.md` | S4 | done（`#L19`，2026-09-12；S4a P0–P4 完毕，S4b 降级后续轮次；附录见该方案 §11） | S3、S1 | S4a 零行为；S4b 见该方案 §7.2 | 否（S4b 若超阈值需再确认） |
| `design-dispatcher-taskid-retirement-full.md` | S5 | done（`#L18`，2026-09-12；deep-oracle 放行，附录见该方案 §11） | S1、S4 | 有（发现面 `_meta`、ack/事件键集、slog 键集） | 否（字段级变更已登记） |
| `design-dispatcher-dispatch-fail-semantics.md` | S6 | done（`#L17`，2026-09-12；写法 B，deep-oracle 放行，附录见该方案 §11） | S3、S1 | 有（未注册分发 done → fail） | 否 |
| `design-dispatcher-tool-plane-contract.md` | S7 | done（`#L16`，2026-09-12；deep-oracle 处置完成，附录见该方案 §11） | S1（并引用 S5/S6 的产物值） | 纯契约 | **是**（`specs/`；沿用 S1 放行） |
| `_TEMPLATE.md` | — | 模板 | — | — | — |
| `design-dispatcher-core-inference-migration.md` | 历史 | done（`#L16`） | — | — | — |
| `design-dispatcher-engine-narrow-core-trim.md` | 历史 | done（`#L15`） | — | — | — |
| `design-dispatcher-zenoh-transport-migration.md` | 历史 | done（`#L20`，含环境验收项） | — | — | — |
| `design-dispatcher-taskid-retirement-deps-migration.md` | 历史 | done（`#L11`） | — | — | — |

## 3. 目标与约束

- **目标**：
  1. 给出**唯一执行顺序**（含并行机会与强制串行边）；
  2. 每期给出可判定的**入口条件**与**完成定义（DoD）**；
  3. 建立**唯一状态总表**与回写规则，杜绝状态漂移；
  4. 固化**执行流水线**（含子智能体派发门槛）、**门禁集合**与**证据要求**。
- **Non-Goals**：
  - 不新增/修改任何架构决策（决策归总纲与各期方案）；
  - 不做代码、`specs/`、测试的改动（本文件执行时零代码改动）；
  - 不重排 S0–S7 的语义（顺序只在 §4.1 固化一次，改序须先改总纲 §4.7）；
  - 不追踪：l4 `visualizer` 读 `SCENE_NAV` 日志字段一事（归技能/日志轮次）。
- **硬边界**（`AGENTS.md`，逐条适用）：
  - **先方案后改码**：任何改动必须先有对应期方案；唯一例外是用户明确指示可直接改；
  - **禁止转接器**：不新增桥接新旧接口的层；**过期必删**：被替代项直接删除，不留桩、不留注释；
  - **契约优先**：`specs/` > 总纲 > 各期方案；冲突时按 §4.6 处置；
  - **不 commit**：每期结束等待显式指令；提交时 `--no-verify`，不装钩子；
  - **隐私门禁**：改动纳入版本控制的文件前跑隐私检索（模式取主机本地），零命中；
  - 文档一律简体中文、只用相对路径（主机绝对路径与个人标识不入库）。

## 4. 方案决策

### 4.1 执行顺序（唯一编排）

```
本地准备（§7.0）
   │
   ├─ S0 隐私与文档门禁清理 ─┐（允许与 S1 并行，但必须先于 S2 起的所有期）
   └─ S1 契约修订 ──────────┘
        │
        ▼
      S2 包拓扑归位（tools/ utils/ perception/）
        │
        ▼
      S3 engine 非 core 职责迁出 + core 四通道适配落位
        │
        ├──► S4 其余 ROS 面适配（S4a 必做；S4b 先评估）
        │        │
        │        ▼
        │      S5 task_id 全链路退役
        │
        └──► S6 分发失败语义与端口登记（前置 S3、S1）

S7 工具面契约补齐（仅依赖 S1；与 S2–S6 无文件交集，可在 S1 后任意时点插入；
                     但其内容引用 S5/S6 的产物值——执行前须复核 S5/S6 是否已 done）
```

- **强制串行边**：`S1 → S2 → S3 → {S4, S6}`；`S4 → S5`。
- **允许并行**：`S0 ∥ S1`（不同树）；`S6 ∥ S4`（S6 只动 engine/skill_router 的失败分支，S4 只动 ROS 面与适配文件）。
- **禁止并行**：任何两期**不得同时改同一文件**（尤其 `engine.py`：S3 与 S6 都动它，S6 必须在 S3 之后）。

### 4.2 放行门（不满足即不得开工）

| 门 | 覆盖范围 | 说明 |
|---|---|---|
| **G-放行-1** | `S0` | `AGENTS.md`、`.trae/skills/**` 在默认目标树之外，需用户显式放行；未放行时 S0 只允许改 `doc/**`（缺口登记，不降级为永久豁免） |
| **G-放行-2** | `S1`、`S7` | `specs/` 是唯一权威且不在默认目标树内，需用户显式放行 |
| **G-放行-3** | 任何期若需顺带改 `specs/` / `AGENTS.md` / `.trae/**` | 一律按上述两条取得放行；不得"顺手改" |
| **G-变更-1** | S5、S6 | 对外可观测变更（发现面 `_meta`、ack/事件键集、slog 键集、未注册 done→fail）必须先在 S1 的「有意变更登记」中存在，否则不得执行 |

### 4.3 每期标准执行流水线（六步）

> 与 `AGENTS.md` 工作流及用户既定的子智能体门槛一致。

1. **前置复核**（每期开头）：用 Read/Grep 复核该期 §2「现状事实」的锚点行号是否仍成立（代码可能已漂移）；**行号漂移则先在同一改动内修正该期文档**，再开工。
2. **补充探索**（仅当该期文档证据不足或涉及未探明区域）：派 `code-explorer`；外部库/API 疑问可与 `doc-librarian` 并行。
3. **用户确认**：把该期文档（含复核结果）交用户确认；**需要放行的期在此取得放行**（§4.2）。
4. **执行**：派 `code-fixer` 按该期 §7 步骤执行；**派发门槛**遵循用户规则——单文件/小修由主 Agent 直接完成，跨模块/≥3 文件/架构级才派子智能体；用户点名的直接派。
5. **评审**：高风险期（S3、S5、S6、S7）派 `deep-oracle` 独立复核证据链与不变量；其余期由主 Agent 自评。
6. **验收与回写**：跑该期 §8 与本文 §8 的门禁；结果与勘误回写该期方案附录；更新 §2 状态表与该期文档 §0 状态行；登记新发现的后续轮次；**不 commit**。

### 4.4 每期完成定义（DoD）

一期只有同时满足以下六条才算 `done`：

1. 该期 §7 的全部步骤执行完毕，无跳步；
2. 该期 §8 验收项**逐条**通过（含分级冒烟：L1 必过；L2/L3 按主机 ROS 环境判定，不可用时回退静态验收并在方案中记录）；
3. 本文 §8.3 的全局门禁（A1–A6 + `py_compile` + `pytest`）在当期判定范围内通过；
4. 字节级契约核对完成：slog 事件名/键集、topic/param/消息字段名、`revision`（除已登记变更）无未登记漂移；
5. 删除项零残留（无转接桩、无注释桩、无 re-export 别名）；
6. 状态回写完成（§4.5）＋ 该期方案附录记录验收实测与勘误。

### 4.5 状态机与状态单点

- 状态取值：`proposed → in-progress → done`（`blocked` 不使用；阻塞情形写入 §9 风险并在方案内登记）。
- **唯一总表 = 本文件 §2**；各期文档 §0「状态」行必须与总表一致，**同一改动内同步**。
- 转 `in-progress` 的时点：获得确认（及放行）后、开始改第一行代码/契约之前。
- 转 `done` 的时点：§4.4 六条全部满足且记录已回写。
- 若执行中方案需要改技术内容：按 §4.6 处置，不得以"先做后补文档"推进。

### 4.6 冲突与变更控制

| 情形 | 处置（顺序不可颠倒） |
|---|---|
| 期方案与**总纲**冲突 | 以总纲为准；在同一改动内修正该期方案；若确需改目标形态，**先改总纲**再改方案 |
| 契约为**自相矛盾/不可判定** | 归 S1；先改契约文本，再按新契约改代码（`l3-migration-protocol` §5） |
| 期方案之间**互相矛盾** | 以总纲 §4.1/§4.2 收敛；收敛结果写回总纲，再同步各期 |
| 执行中**发现新问题**（孤儿引用、悬空引用等） | 不得顺手修；登记到该期方案的「后续轮次待办」或开 issue（issue 建在本仓库 GitHub） |
| 方案**执行中作废** | 在方案 §0 状态行注明废弃原因，并指向替代方案；被替代项按"过期必删"删除 |

### 4.7 文件隔离规则（防并行污染）

- 同一期是**唯一写者**：该期声明改动的文件，其它期在该期 `done` 前不得改。
- 共享热点文件（`engine.py`、`tools/model.py`、`tools/registry.py`、`rpc_plane.py`）按 §4.1 的串行边执行，禁止并行。
- 执行前确认**没有外部编辑器缓冲区/同步进程**正在写同一文件（本套文档曾出现"写入被回滚"，见 §9 R7）。

### 4.8 门禁与证据要求

- **证据形态**：每条现状事实 = 相对路径 + 实测行号 + 现象；每条验收 = 可执行命令或契约级比对；禁止"看起来对"。
- **门禁集合**：总纲 §4.4 的 A1–A6 与契约 G1–G23；**分级冒烟**按主机 ROS 环境判定，环境缺失回退静态验收并显式记录（不得因环境缺失判失败）。
- **门禁脚本未迁移**（`specs/tools/*`）：迁移前用等价 grep / `python3 -c` / `pytest`；S7 的 A6-1/2/3 是其落点。

## 5. 文档 ↔ 期 ↔ 产物 对照

| 期 | 方案文件 | 主要产物（代码 / 契约 / 文档） | 验收产物 |
|---|---|---|---|
| S0 | `design-dispatcher-privacy-gate-cleanup.md` | `AGENTS.md`、`doc/**`、`.trae/skills/**` 的标识替换 | 方案附录：命中数（不写模式与内容） |
| S1 | `design-dispatcher-spec-reconciliation.md` | `specs/implemented/**`（B3↔R1/R4、G2、硬约束措辞、决策记录落点、B7 收口、端口粒度注记） | 方案附录：逐条 old→new 落盘核对 |
| S2 | `design-dispatcher-package-topology.md` | `PKG/dispatcher/{utils,tools,perception}/**`、`dispatcher_node.py`、`tests/tool-registry/*` 的 import | 方案附录：`revision` 不变、旧路径清零 |
| S3 | `design-dispatcher-engine-relocate-non-core.md` | `PKG/dispatcher/core/**`、`PKG/dispatcher/ros_adapter/core_channels_ros.py`、`engine.py`、`dispatcher_node.py` | 方案附录：slog/topic 字节级一致、G7/G8 |
| S4 | `design-dispatcher-ros-adapter-split.md` | `PKG/dispatcher/ros_adapter/{params_ros,clock_ros,feedback_ros}.py`、`utils/**` 去 `rospy` | 方案附录：A1/A2、param/topic 不变 |
| S5 | `design-dispatcher-taskid-retirement-full.md` | `tools/{model,registry,runtime}.py`、`utils/rpc_plane.py`、`engine.py`、`tests/tool-registry/*` | 方案附录：新 `revision` 断言、键集比对、G5/G23 零命中 |
| S6 | `design-dispatcher-dispatch-fail-semantics.md` | `engine.py`（S3 后 `core/skill_router.py` + 回退接线） | 方案附录：fail payload 断言、误伤检查 |
| S7 | `design-dispatcher-tool-plane-contract.md` | `specs/proposed/inner/l3-tool-plane.spec.md`（→ `implemented/`）、`l3-dispatcher.spec.md` 的 Inner contracts 表 | 方案附录：A6-1/2/3 可跑 |

## 6. 作废、降级与不追踪清单

| 项 | 处置 | 理由 |
|---|---|---|
| `package-topology.md` / `engine-relocate-non-core.md` 的**旧版裁决**（包根布局、`control_plane` 留 `tools/`） | 已被**就地改写**的新版取代，不保留旧版副本 | 目标形态由总纲唯一钉死；保留旧版会形成第二权威 |
| 4 份 `done` 历史方案 | **不改写**，仅作历史与勘误引用 | `specs/README.md` 生命周期规则：冻结记录不再维护 |
| l4 `visualizer` 读 `SCENE_NAV` 日志 `task_id` | **不追踪** | 属观测契约与 skill round，不在本套范围 |
| `S4b` 感知层 ROS 隔离 | 降级为**后续轮次**（不在 S0–S7） | S4 子方案 §7.2 门槛不满足（100 处 `rospy.`、消息类型与几何交织、无 ROS-free 测试） |
| 技能族迁入 + `SkillHost` 11 端口、`recording`/`vlm_facade`、任务注入轮次、门禁脚本迁移、决策记录归档 | 后续轮次（总纲 §10 尾注登记） | 属旧库→新库迁移，按 `l3-migration-protocol` 另行立方案 |

## 7. 实施步骤（逐期执行清单）

> 每期固定四段：**入口条件 → 步骤 → 验收 → 回退**。细则在各期方案内；本节只写编排级要求。

### 7.0 本地准备（每期开工前）

- 入口条件：无。
- 步骤：
  1. 快照当期将改动的文件到主机本地（如 `/tmp/`，**不入库**）；
  2. 确认无外部进程/编辑器缓冲区在写同一文件（§4.7）；
  3. 环境判定：`python3 -c "import rospy, yaml, numpy"` 决定 L2/L3 冒烟是否执行；`pytest` 可用性确认；
  4. 隐私检索模式就位（主机本地，不入库）。
- 验收：快照路径与三个环境判定结果记录在该期方案附录。
- 回退：不适用。

### 7.1 S0 隐私与文档门禁清理

- 入口条件：**已取得 G-放行-1**。
- 步骤：按方案 §7 P0 执行（`doc/**` 先行；`AGENTS.md`/`.trae/skills` 依放行）。
- 验收：方案 §8 全项 + 本文 §8.3 的 A4。
- 回退：`git checkout -- <files>`（纯文档）。

### 7.2 S1 契约修订

- 入口条件：**已取得 G-放行-2**；S0 的措辞统一已落地（B7/硬约束 1 的措辞依赖它）。
- 步骤：按方案 §7 P0 顺序落 §4.1a/§4.1b → §4.2a/§4.2b（**白名单按 S3 文档的冻结名定稿，不留"待 S3 定稿"占位**）→ §4.3 → §4.4 → §4.6 → §4.7。
- 验收：方案 §8 + 决议记录落点接线可运行；G-变更-1 的登记项齐备（E1–E4 与 S6 的 (c)）。
- 回退：`git checkout -- specs/ AGENTS.md`。

### 7.3 S2 包拓扑归位

- 入口条件：S1 `done`。
- 步骤：按方案 P0（`tools/protocol.py`）→ P1（`utils/` 骨架 + state/slog/config）→ P2（传输支撑）→ P3（`control_plane` 归位）→ P4（`skill_api` 归 `tools/`）。
- 验收：方案 §8 + A1/A3 + `revision` 逐字不变。
- 回退：文件移回 + 还原 import（逐期 P0–P4 独立可回退）。

### 7.4 S3 engine 非 core 职责迁出 + core 四通道适配落位

- 入口条件：S2 `done`。
- 步骤：按方案 P0 装配 → P1 端口 + 四通道适配 → P2 遥测 → P3 相位桥 → P4 技能路由 → P5 工具缝 → P6 动作面（**四类通道适配与拆分同期落位，禁止二次搬迁**）。
- 验收：方案 §8（含 G2/G4/G7/G8、A1/A2）+ §4.10 的 S6 接口已冻结。
- 回退：还原方法体与调用点 + 删除 `core/`、`ros_adapter/core_channels_ros.py`。

### 7.5 S4 其余 ROS 面适配

- 入口条件：S3 `done`；S4b 需按方案 §7.2 门槛重新判定（初判不满足 → 降级为后续轮次）。
- 步骤：S4a（`params_ros` / `clock_ros` / `feedback_ros`）→ S4b（仅当门槛满足）。
- 验收：方案 §8（A2/A3 + param/topic/payload 不变）。
- 回退：适配实现移回原文件 + 删除对应 `ros_adapter/*_ros.py`。

### 7.6 S5 task_id 全链路退役

- 入口条件：S1、S4 `done`；G-变更-1 登记的 E1/E2/E4 已存在。
- 步骤：方案 P0 数据模型 → P1 准入/发现面 → P2 ack/事件 → P3 engine/遥测 → P4 测试与门禁（**wire 无该字段，不新增丢弃落点**）。
- 验收：方案 §8（新 `revision` 断言、键集比对、G5/G23 全域零命中、pytest 全绿）。
- 回退：按方案分步回退点。

### 7.7 S6 分发失败语义与端口登记

- 入口条件：S3 `done`；S1 的 (c) 登记已存在。
- 步骤：按方案把未命中两处分支统一改 `_fail_unregistered_dispatch`（写法 B 依 S3 §4.10 冻结接口）；端口缺口只登记不补桩。
- 验收：方案 §8（fail payload 含工具名、正常 ADVANCE 与队尽 done 不受影响）。
- 回退：还原分支 + 删除 `_fail_unregistered_dispatch`。

### 7.8 S7 工具面契约补齐

- 入口条件：**已取得 G-放行-2**；S1 `done`；引用 S5/S6 产物值的部分，在 S5/S6 `done` 后复核。
- 步骤：方案 P0 起草叶契约 → P1 挂 Parent 与 Inner contracts 表 → P2 与实现对照 → P3 接入 A6-1/2/3。
- 验收：方案 §8（契约头规范、`specs/README.md` 规则逐条、A6 可跑）。
- 回退：删除新增叶契约与总纲/根契约的对应行。

## 8. 验收标准

### 8.1 每期 DoD

见 §4.4（六条）。任一未满足即不得置 `done`。

### 8.2 全局终态判据（"稳定"三条同时成立）

1. **单一目标树**：`PKG/dispatcher/` 下每模块归属唯一平面，无并行的第二形态；
2. **单一依赖方向**：A1 门禁零命中（`tools/` 零包内出边；`utils/`/`core/`/`perception/` 零 `engine`）；
3. **契约—代码一致**：G1–G23 逐条可判绿；未达成项在方案或 issue 中登记，无静默漂移。

### 8.3 全局门禁命令集（每期在当期范围内执行）

```bash
# A5 语法 / 引用闭包
python3 -m py_compile $(git ls-files 'l3-dispatcher-planner/ros_packages/dispatcher/**/*.py')

# A1 依赖方向
grep -rnE 'dispatcher\.(utils|perception|core|ros_adapter)' PKG/dispatcher/tools/    # 期望：零命中
grep -rnE 'dispatcher\.engine'  PKG/dispatcher/{utils,core,perception}/             # 期望：零命中

# A2 适配面
grep -rnE '^\s*(import rospy|from (std_msgs|geometry_msgs|sensor_msgs|nav_msgs|quadrotor_msgs|cv_bridge))' \
  PKG/dispatcher --include=*.py | grep -v '_ros\.py' | grep -v 'ros_adapter/'      # 期望：零命中

# A3 旧路径清零（S2 后）
ls PKG/dispatcher/{skill_api,state,config,slog,connection_lease,zenoh_rpc,rpc_plane}.py   # 期望：不存在
ls PKG/dispatcher/tools/control_plane.py                                                  # 期望：不存在

# A4 隐私（模式取主机本地区，占位）
# <station-host 本地检索命令>：命中集合 == 公开仓库标识白名单

# A6 工具面对外协议（S5/S6 后；细分 A6-1/2/3 见 S7 方案 §4.5）
python3 -c "import sys; sys.path.insert(0,'PKG'); from dispatcher.tools.registry import ToolRegistry; print(ToolRegistry.default().list_tools()['revision'])"

# 测试
pytest l3-dispatcher-planner/tests/tool-registry
```

### 8.4 记录要求

- 每期在其方案附录记录：日期、执行者、验收实测结果、勘误（回写正文）、未完成项与后续轮次；
- 若发现**新待办**：登记在该期方案的「后续轮次待办」或开源仓 issue（`gh issue create -R <owner>/<repo>`），**不得只写在对话里**。

## 9. 风险与对策

| # | 风险 | 影响 | 对策 |
|---|---|---|---|
| R1 | 不按顺序、抢跑（如未 S1 就 S2） | 目标树未定即搬迁，二次搬迁 | §4.1 串行边 + §4.2 放行门 + §7 每期入口条件；抢跑即缺陷 |
| R2 | 两期并行改同一文件 | 语义互相覆盖 | §4.7 单写者 + 热点文件串行化 |
| R3 | 行号漂移（代码已变，方案仍写旧行号） | 切错行、误删 | §4.3 第 1 步前置复核实测；漂移即先修方案 |
| R4 | 放行未取得却先做 S0/S1/S7 的非 doc 部分 | 越界改动 | §4.2 G-放行-1/2/3；未放行只允许 `doc/**` |
| R5 | 对外变更未登记就执行（S5/S6） | 无据可查的对外行为变化 | §4.2 G-变更-1；登记项必须先落 S1 |
| R6 | 契约自相矛盾未裁决就改代码 | 判定标准缺失 | §4.6：先改契约再改码（`l3-migration-protocol` §5） |
| R7 | 写入被外部编辑器缓冲区回滚（本套已发生） | 改动丢失、验收误判 | §7.0 第 2 步：执行前确认无外部写者；关键改写后立即回读校验 |
| R8 | 状态不同步（总表与各期 §0 不一致） | 执行者按过期状态开工 | §4.5：同一改动内同步两处；DoD 第 6 条 |
| R9 | 把"环境缺失"当"验收失败" | 无谓返工 | 分级冒烟判定条件（§4.8）；环境缺失回退静态验收并记录 |
| R10 | 顺手修新发现的问题 | 范围失控、diff 交织 | §4.6 末行：登记不修 |

回滚策略：每期独立可回退（纯位置期为"移回 + 还原 import"；文档/契约为 `git checkout --`；语义期按各期回退点）；执行前对当期文件做主机本地快照。

## 10. 修改点清单汇总

| 文件 | 动作 | 说明 |
|---|---|---|
| `doc/l3-dispatcher-planner/iteration/design-dispatcher-execution-plan.md` | 新增 | 本执行计划（编排总表） |
| `doc/l3-dispatcher-planner/iteration/design-dispatcher-architecture-stabilization.md` | 修改 | §4.8 文档集新增本文件一行；标注「执行顺序与状态总表以本文件为准」 |
| 各期方案 | 随执行维护 | 仅 §0 状态行与附录（勘误/验收记录）随执行更新；技术内容变更须走 §4.6 |

**登记的后续轮次（不在本编排内）**：S4b 感知层 ROS 隔离；技能族迁入与 `SkillHost` 11 端口；`recording` / `vlm_facade` 归位；任务注入轮次（`_start_prompt_task` / `arm_action`）；`specs/tools/*` 门禁脚本迁移；`specs/implemented/architecture/` 决策记录归档。

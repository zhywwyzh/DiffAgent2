# core workflow.py → tool_workflow.py 改名方案

> 摘要：用户指出 `core/workflow.py` 命名不明确（工具执行缝宿主），建议改为 `tool_workflow.py`。
> 本方案为**独立任务**（与 `design-dispatcher-engine-domain-extraction.md` 域外迁方案无关）：
> 仅模块重命名 + 同步 5 处活引用 + 契约白名单行名同步；类名 `ToolWorkflowHost` 与方法/字段/行为
> 一律不变。

## 0. 元信息

| 项 | 值 |
|----|----|
| 日期 | 2026-09-15 |
| 目标路径 | `l3-dispatcher-planner/ros_packages/dispatcher/dispatcher/core/` |
| 状态 | done |
| 关联文档 | 契约 `specs/implemented/inner/l3-core-boundary.spec.md`；S3 姊妹篇 `design-dispatcher-engine-relocate-non-core.md`（done，历史不改写）；姊妹篇 `design-dispatcher-engine-domain-extraction.md`（域外迁，独立任务）；模板 `_TEMPLATE.md` |

## 1. 背景与动机

1. 用户指出 `core/workflow.py` 命名不明确：模块承载的是**工具执行缝宿主**（`ToolWorkflowHost`
   —— `bind_tool_middleware` / `start_tool_workflow` / `cancel_tool_call` 三缝 + 六字段），
   「workflow」一词与 dispatcher 决策流程语义重叠，易误导；`tool_workflow` 直指工具执行面。
2. 用户明确「这个是独立于前面对与engine提问的」——不并入域外迁方案，单独成案。
3. 类名 `ToolWorkflowHost`、`dispatcher_node.py#L135-140` 的 `ToolControlPlane(engine.tools, …)`
   duck-typed 契约面（`core/workflow.py#L21-22` 头注记）均不变，仅模块文件名变化。

## 2. 现状事实（改动面）

> 每条带「文件路径 + 行号」。

- [ ] `l3-dispatcher-planner/ros_packages/dispatcher/dispatcher/core/workflow.py` — 待改名目标（166 行，`ToolWorkflowHost`）。
- [ ] `engine.py#L29` — `from dispatcher.core.workflow import ToolWorkflowHost`（唯一 import 点）。
- [ ] `engine.py#L167-L168` — 注释「工具执行缝宿主（S3 §2.7/§5 迁入 core/workflow.py）：3 缝 + 6 字段」。
- [ ] `engine.py#L169` — `self.tools = ToolWorkflowHost(...)` 构造调用（仅类名，随 import 行自动生效，无需单独改动）。
- [ ] `dispatcher_node.py#L130` — 注释「duck-typed 三缝宿主为 core/workflow.py 的 `ToolWorkflowHost`」。
- [ ] `specs/implemented/inner/l3-core-boundary.spec.md#L82` — §4.1 白名单行 `core/workflow.py`（`ToolWorkflowHost`）。
- [ ] `core/__init__.py` 为空、无 re-export — 改名无其它导入面；`dispatcher/core/__pycache__/workflow.cpython-310.pyc` 为构建缓存（不入库）。

## 3. 目标与约束

- **目标**：`core/workflow.py` → `core/tool_workflow.py`；5 处引用（2 行 import/注释于 engine、1 处注释于 dispatcher_node、1 行白名单于 spec）同步；命名与「平面目录小写单词、文件小写下划线」规范一致。
- **Non-Goals**：不改类名 `ToolWorkflowHost`；不改任何方法/字段/构造签名/行为；不改写 S3 历史文档中的 `workflow` 引用（历史冻结）。
- **硬边界**：
  - 禁止 re-export 兼容：`core/__init__.py` 保持空，不写 `from .workflow import *` 之类别名；
  - 旧文件直接改名（内容逐字），不留旧文件；
  - spec 白名单同步属端侧契约修改，用户已放行（同一契约文件 `l3-core-boundary.spec.md`）。

## 4. 方案决策

- **新文件名**：`core/tool_workflow.py`（内容与 `workflow.py` 逐字一致，仅文件更名）。
- **命名对齐**：类 `ToolWorkflowHost` 不变；模块名与「工具执行缝宿主」语义一致（`tool_workflow`）。
- **同步面**（5 处）：`engine.py:29` import、`engine.py:167` 注释、`dispatcher_node.py:130` 注释、
  `l3-core-boundary.spec.md:82` 白名单行；`engine.py:169` 构造调用类名不变、随 import 自动生效。
- **spec 修订照抄文本（`l3-core-boundary.spec.md` §4.1，用户已放行）**：白名单行由
  `core/workflow.py`（`ToolWorkflowHost`）改名为 `core/tool_workflow.py`（`ToolWorkflowHost`），
  构成 `| core/tool_workflow.py（\`ToolWorkflowHost\`） | \`__init__\`、\`bind_tool_middleware\`、\`_activate_tool_call\`、\`start_tool_workflow\`、\`cancel_tool_call\` |`，
  行内方法清单逐字不变，仅模块名变化；§4.1 其余各行不动（`core/tool_workflow.py` 行号
  随域外迁方案 §4 spec 修订小节齐备，三处 spec 改动统一在执行期一次落盘）。
- **旧接口 → 删除**：`core/workflow.py` 文件实体经 git mv 消失，不保留副本、不设别名。

## 5. 迁移映射表

| 旧路径/命名 | 新路径/命名 | 动作 | 备注 |
|-------------|-------------|------|------|
| `core/workflow.py` | `core/tool_workflow.py` | rename | 内容逐字（git mv），类名 `ToolWorkflowHost` 不变 |
| `engine.py#L29` `from dispatcher.core.workflow import ToolWorkflowHost` | `from dispatcher.core.tool_workflow import ToolWorkflowHost` | edit | 唯一 import 点 |
| `engine.py#L167` 注释 `core/workflow.py` | `core/tool_workflow.py` | edit | 注释同步 |
| `engine.py#L169` `ToolWorkflowHost(...)` | 不变 | 无独立改动 | 类名不变，import 已覆盖 |
| `dispatcher_node.py#L130` 注释 `core/workflow.py` | `core/tool_workflow.py` | edit | 注释同步 |
| `l3-core-boundary.spec.md#L82` `core/workflow.py` 白名单行 | `core/tool_workflow.py` 白名单行 | edit | 行内方法清单不变 |

## 6. 删除清单

| 删除项 | 理由 |
|--------|------|
| `core/workflow.py` 旧文件实体 | git mv 改名（内容迁移至新名），不留副本、不 re-export |
| `dispatcher/core/__pycache__/workflow.cpython-310.pyc` | 构建缓存，随重构清理或由忽略规则覆盖，不入库 |

## 7. 实施步骤

### P0 — 重命名 + 同步引用

- 范围：
  1. `core/workflow.py` → `core/tool_workflow.py`（git mv，内容逐字）；
  2. 同步 `engine.py:29`、`engine.py:167`、`dispatcher_node.py:130`、`l3-core-boundary.spec.md:82`。
- 行为不变式：`ToolWorkflowHost` 类名、构造参数、方法、字段、slog 事件零变化；`ToolControlPlane` duck-typed 契约（`dispatcher_node.py#L135-140`）零变化。
- 验收：`python3 -m py_compile` 全绿；`pytest l3-dispatcher-planner/tests/tool-registry` 全绿；`grep -rnE 'core\.workflow|core/workflow'` 于 `PKG/` 与 `specs/` 除历史文档零命中（见 §8）。
- 回退：git mv 还原 + 引用还原。

## 8. 验收标准与结果

- [x] 核心与工具面回归：`uv run --isolated --no-project --python python3 --with pytest --with eclipse-zenoh --with pyyaml python -m pytest -q l3-dispatcher-planner/tests/core-boundary l3-dispatcher-planner/tests/tool-registry`，**80 项通过**。
- [x] 现存 l3 Python 源文件语法检查通过；core AST 方法集合符合修订后的白名单；六态数量不变。
- [x] 核心导入闭包无 ROS 与领域实现；协作模块不反向导入 engine；四类出站通道白名单通过。
- [x] 未注册失败不排空队列、不产生 done；四裁决、实例归属、迟到动作结果、恢复与等待诊断回归通过。
- [x] 默认工具集合为空，revision 与工具面 spec 一致；22 个已删除工具名及旧别名的 RPC 请求均拒绝且不入队。
- [x] engine 已迁旧定义及注释引用零残留；生产工具、缺失任务注入入口、场景/抓取/记录状态标识零残留。
- [x] spec 状态及父契约引用有效；本仓门禁引擎尚未迁移，以上述 AST、结构检查与测试判定。

验证限制：本轮未做 ROS/实机飞行端到端验证。全部未实现生产工具已按用户要求删除，当前无飞行/导航生产能力；未来新增技能须连同执行链与端到端验收一起交付。感知实现内部仍含 ROS 通信，planner 中仍有既有来源编号检查；这些是保留实现的后续边界工作，不能将本轮核心通过外推为全 l3 的 G5/G7/G8 全绿。

## 9. 风险与对策

| 风险 | 影响 | 对策 |
|------|------|------|
| 历史 design 文档（S3 姊妹篇等）中的 `workflow` 引用与行号 | 低 | 历史冻结不改写；引用保持原文 |
| `__pycache__/*.pyc` 残留或旧字节码被导入 | 低 | 重构后清理 `core/__pycache__/` 或由忽略规则覆盖；改后立即回读校验（编排总表 §9 R7） |
| 与域外迁方案同日动 `engine.py`（编排总表 §4.7 文件隔离，engine.py 为热点文件） | 中 | 两方案均动 `engine.py`（本方案 L29/L167，域外迁方案 import 区新增）——执行时串行；本方案仅 5 处机械引用，先行落地 |
| `git mv` 在部分环境不保留内容为逐字 | 低 | 改名后立即 `diff` 校验新旧文件内容一致 |

## 10. 修改点清单汇总

| 文件 | 动作 | 说明 |
|------|------|------|
| `l3-dispatcher-planner/ros_packages/dispatcher/dispatcher/core/workflow.py` | rename | → `core/tool_workflow.py`（git mv，内容逐字） |
| `l3-dispatcher-planner/ros_packages/dispatcher/dispatcher/engine.py` | 修改 | `#L29` import、`#L167` 注释 |
| `l3-dispatcher-planner/ros_packages/dispatcher/dispatcher_node.py` | 修改 | `#L130` 注释 |
| `specs/implemented/inner/l3-core-boundary.spec.md` | 修改（已放行） | `#L82` 白名单行名 `core/workflow.py` → `core/tool_workflow.py` |
| `doc/l3-dispatcher-planner/iteration/design-dispatcher-tool-workflow-rename.md` | 新增 | 本方案 |

最终交付记录：结构拆分、核心契约修复与用户追加的全部未迁入链路删除合并交付。`engine.py` 从开始时约 784 行缩为 373 行。`workflow.py` 在重命名阶段逐字迁移，后续通用入口接线与缺失链删除由 `design-dispatcher-unmigrated-chain-removal.md` 接管，故最终文件内容不再与旧版本逐字相同；无旧路径兼容入口。

结构理由已归档至 `specs/implemented/architecture/2026-09-15-dispatcher-core-and-capability-pruning.md`。工作区未提交、未推送。最初既有工具面基线为 52 通过、7 失败；删除无实现链路并将旧连接 queryable 断言对齐现行单 RPC 契约后，最终回归全绿。

# dispatcher VLA 几何改名 + 迁移对应注释清理 方案

> 摘要：把 `tools/vla/geometry.py` 改名为 `tools/vla/vla_geometry.py` 以统一
> vla 家族命名；并把 **vla 模块以外** 所有"新库/旧库迁移对应"的注释与测试
> 说明删除。代码范围：`ros_packages/dispatcher/**/*.py` + `tests/**/*.py`；
> 目标：让非 vla 代码不再携带迁移叙事；依据来源：用户 2026-09-18 指令与
> 澄清答复；姊妹篇 `design-dispatcher-vla-migration.md`（本次不修改）。

## 0. 元信息

| 项 | 值 |
|----|----|
| 日期 | 2026-09-18 |
| 目标路径 | `l3-dispatcher-planner/ros_packages/dispatcher/`、`l3-dispatcher-planner/tests/` |
| 状态 | proposed |
| 关联文档 | `design-dispatcher-vla-migration.md`（不改）、`doc/l3-dispatcher-planner/rest/dispatcher-deferred-dependencies.md`（仅去旧版引用） |

## 1. 背景与动机

- 命名混淆：`tools/vla/` 家族内已有 `vla_skill.py`、`catalog.py`、`ports.py`，
  唯独几何模块叫通用名 `geometry.py`，在跨包 import 与检索时易与
  `dispatcher/perception/` 的几何原语混淆。
- 迁移叙事外溢：非 vla 模块的注释里大量保留"旧库/旧链/迁移前逐字一致/
  留壳"等**迁移对应**描述；使用者明确表示不关心新旧迁移对应关系，这些描述
  在代码定型后成为噪声，且会随旧库演进而过期失真。

## 2. 现状事实（问题清单）

> 每条带「文件路径 + 行号」证据。所有行号基于 2026-09-18 工作区状态。

### 2.1 改名涉及点（8 处）

- [ ] `ros_packages/dispatcher/dispatcher/tools/vla/geometry.py` — 待改名文件本体
- [ ] `ros_packages/dispatcher/dispatcher/tools/vla/ports.py#L19` — `from dispatcher.tools.vla.geometry import VlaGeometrySource`
- [ ] `ros_packages/dispatcher/dispatcher/tools/vla/vla_skill.py#L46` — `from dispatcher.tools.vla.geometry import GeometryService, VlaGeometryConfig`
- [ ] `ros_packages/dispatcher/dispatcher_node.py#L165` — `from dispatcher.tools.vla.geometry import VlaGeometryConfig`
- [ ] `tests/core-boundary/test_vla_composition.py#L40` — 同款 import
- [ ] `tests/perception/test_vla_geometry.py#L47` — 同款 import
- [ ] `ros_packages/dispatcher/dispatcher/tools/vla/__init__.py#L3` — 注释 "tools/vla/geometry.py"
- [ ] `ros_packages/dispatcher/dispatcher/tools/vla/vla_skill.py#L73` — 注释 "geometry.py 头注"

### 2.2 vla 模块外待删迁移引用（模块 .py，共 15 文件）

- [ ] `dispatcher_node.py#L149-L151` — "旧链 planner_mode_topic=/uav_planner/trigger … 在新栈无对应口"
- [ ] `dispatcher_node.py#L155` — "默认值与旧库 config 逐项核对一致"
- [ ] `dispatcher_node.py#L156-L157` — "默认值=旧库 config.py UAV_POLICY_DEFAULTS + base_policy 默认，逐项核对一致"
- [ ] `dispatcher/engine.py#L122-L123` — "旧版的额外悬停目标下发尚未接入"
- [ ] `dispatcher/execution/waypoint_execution.py#L93` — "旧 stopMotion 职责上行"
- [ ] `dispatcher/execution/skill_host.py#L109` — "不模拟旧版 engine 属性"
- [ ] `dispatcher/execution/skill_host.py#L154-L155` — "旧引擎的跨技能直写归属无消费者"
- [ ] `dispatcher/execution/skill_host.py#L158` — "与旧链 _can_accept_new_action 同源的门"
- [ ] `dispatcher/execution/skill_host.py#L266` — "（旧链行为）"
- [ ] `dispatcher/execution/skill_host.py#L269-L270` — "与旧 engine 的 error={...} 口径一致"
- [ ] `dispatcher/execution/skill_host.py#L307` — "顺序与旧链一致"
- [ ] `dispatcher/execution/composition.py#L49` — "默认值=旧库值"
- [ ] `dispatcher/execution/composition.py#L52-L57` — "旧语义 / 旧链每轮置位 / if_safe_mode 旧库仅剩留壳写"
- [ ] `dispatcher/ros_adapter/params_ros.py#L4-L5` — "迁移前 utils/config.py::set_ros_params … 逐字一致"
- [ ] `dispatcher/ros_adapter/clock_ros.py#L3-L4` — "与迁移前 utils/control_plane.py … 逐字一致"
- [ ] `dispatcher/ros_adapter/core_channels_ros.py#L6` — "和迁移前 engine.py 逐字一致"
- [ ] `dispatcher/tools/protocol.py#L6-L7` — "自 tools/model.py、registry.py、runtime.py 迁入，旧位置定义已直接删除"
- [ ] `dispatcher/core/prompt_queue.py#L28` — "恢复旧代码对误配的「跳过」容忍"
- [ ] `dispatcher/core/telemetry.py#L3` — "自 engine.py 迁出（零语义变更…）"
- [ ] `dispatcher/core/telemetry.py#L88-L89` — "与迁移前 try/except 包裹的语义一致"
- [ ] `dispatcher/core/actuators.py#L3-L7` — "自 engine.py 迁出 / 已迁 ros_adapter / 迁移前实测"
- [ ] `dispatcher/core/task_phase.py#L3` — "自 engine.py 迁出（零语义变更…）"
- [ ] `dispatcher/utils/rpc_plane.py#L4` — "不存在旧工具别名、参数转换或领域查询"

### 2.3 tests 待删旧链对照（4 文件）

- [ ] `tests/perception/test_vla_geometry.py#L1`（模块 docstring 首行"对比旧链"）、`#L7-L23`（期望值推导依据整段）、`#L211`、`#L271`、`#L276`、`#L281`、`#L289`、`#L301`、`#L323`、`#L375`、`#L442`、`#L447`、`#L453`、`#L471`、`#L514`、`#L527`、`#L535`
- [ ] `tests/core-boundary/test_vla_skill.py#L3-L14`（"期望值从旧链…"推导段）、`#L295`、`#L358`、`#L420`、`#L437`、`#L445`、`#L455`、`#L482`、`#L537`、`#L609`
- [ ] `tests/core-boundary/test_vla_composition.py#L5`、`#L250-L251`、`#L403`、`#L438`
- [ ] `tests/core-boundary/test_vla_skill_host.py#L215`、`#L272`

### 2.4 必须保留（功能性"旧"，非迁移引用）

- `dispatcher/core/state_ledger.py#L19`（"记录迁移来源、目标与原因"= 状态迁移）、`#L47`（"旧结果失效"）
- `dispatcher/core/action_gate.py#L73`（"旧代次"）
- `dispatcher/tools/runtime.py#L114`、`#L116`、`#L118`（"旧 active call / 旧技能 / 旧 call"）
- `tests/core-boundary/test_vla_skill.py#L559`、`#L567`、`#L593`（旧代次 / 旧动作）
- `tests/core-boundary/test_vla_skill_host.py#L5`、`#L222`、`#L226`（旧代次）
- `tests/core-boundary/test_vla_composition.py#L297`、`#L304`、`#L587`（旧 disposer / 旧调用）

### 2.5 vla 模块内（本次豁免删除）

`tools/vla/{geometry.py, vla_skill.py, ports.py, catalog.py}` 内的迁移说明
（"P2 迁入 / 与旧链逐字对齐 / 旧库 config"等）**保留不动**——用户指令明确
"除了 vla 模块以外"。改名触及的 2 处注释（§2.1）仍按改名同步。

## 3. 目标与约束

- **目标**：
  1. `geometry.py` → `vla_geometry.py`，全仓 import/注释同步，行为零变更。
  2. vla 模块以外不再出现"新旧迁移对应"描述（模块 .py 注释 + tests 说明）。
- **Non-Goals**：
  - 不改 `tools/vla/` 内的迁移说明（用户豁免）。
  - 不改 `doc/`、`specs/`（载体限定 `.py` + `tests`）。
  - 不改任何代码逻辑、常量、事件名、topic、param。
  - 不删功能性"旧"（§2.4）。
- **硬边界**：
  - 禁止新设计转接器来转接新旧接口（本方案不新增任何接口）。
  - 被替代的旧接口必须删除，不得保留为转接口或注释桩；本次仅删注释，
    不涉及旧接口。

## 4. 方案决策

- **目标目录树**（改后）：

  ```
  tools/vla/
    __init__.py
    catalog.py
    ports.py
    vla_geometry.py     # 由 geometry.py rename
    vla_skill.py
  ```

- **命名规范表**：

  | 类型 | 规范 | 示例 |
  |------|------|------|
  | 文件 | vla 家族统一 `vla_` 前缀（`__init__` 除外） | `vla_geometry.py`、`vla_skill.py` |
  | 类 | 保持现名，不改 | `GeometryService`、`VlaGeometryConfig`、`VlaGeometrySource` |
  | 模块路径 | `dispatcher.tools.vla.<file>` | `dispatcher.tools.vla.vla_geometry` |

- **接口形态**：无新增/变更接口；`geometry.py` 的导出符号（`GeometryService`/
  `VlaGeometryConfig`/`VlaGeometrySource`/`derive_nav_mode`/`normalize_direction`/
  `pose_to_list` 等）原样迁移到 `vla_geometry.py`。
- **旧接口 → 删除**：`dispatcher.tools.vla.geometry` 模块路径不再存在，
  不保留 shim/转发模块。

## 5. 迁移映射表

| 旧路径/命名 | 新路径/命名 | 动作 | 备注 |
|-------------|-------------|------|------|
| `tools/vla/geometry.py` | `tools/vla/vla_geometry.py` | rename | 文件本体 |
| `dispatcher.tools.vla.geometry` | `dispatcher.tools.vla.vla_geometry` | rewrite | import 5 处（§2.1） |
| 注释 `tools/vla/geometry.py` | `tools/vla/vla_geometry.py` | rewrite | 注释 2 处（§2.1） |
| 迁移对应注释（vla 模块外） | — | delete | §6 清单 |

## 6. 删除清单

| 删除项 | 理由 |
|--------|------|
| §2.2 模块 .py 迁移引用 23 处 | 迁移叙事，与旧库演讲解耦后失真 |
| §2.3 tests 旧链对照 36 处 | 同上；测试断言不变，仅去推导来源注释 |
| `dispatcher.tools.vla.geometry` 模块名 | 被 `vla_geometry` 取代，不保留转发桩 |
| `dispatcher-deferred-dependencies.md` 中的"旧版位置/旧版消费链"引用列 | 用户答复"保留条目、去旧版引用"（见 §7 P3） |

**保留**：§2.4 功能性"旧"；§2.5 vla 模块内迁移说明。

## 7. 实施步骤（P0/P1/P2/P3）

### P0 — 改名 `geometry.py` → `vla_geometry.py`

- 范围：`git mv`（或删除+新建）`tools/vla/geometry.py` → `tools/vla/vla_geometry.py`；
  同步 §2.1 的 5 处 import 与 2 处注释。
- 行为不变式：模块导出符号、类定义、常量、事件名、返回值字节级不变。
- 验收：`tools/vla/` 内外无 `tools.vla.geometry` 残留；import 自检通过。
- 回退：`git mv` 反向 + import 回改。

### P1 — 清理 vla 模块外模块 .py 迁移引用

- 范围：§2.2 的 15 个文件。
- 行为不变式：只改注释文本，`git diff` 不出现代码行变化（除 docstring
  收尾措辞）。
- 验收：`tools/vla/` 之外 grep 迁移关键词零匹配（排除 §2.4 功能性"旧"）。
- 回退：`git checkout -- <file>`。

### P2 — 清理 tests 旧链对照

- 范围：§2.3 的 4 个测试文件。
- 行为不变式：测试用例、断言、期望值一字不改。
- 验收：同上 grep 门禁；测试收集不报错。
- 回退：`git checkout -- <file>`。

### P3 — 保留项台账去旧版引用（按用户答复）

- 范围：`doc/l3-dispatcher-planner/rest/dispatcher-deferred-dependencies.md`
  （+ 必要时 `rest/README.md` 索引措辞）。
- 动作：保留 R01–R07 功能缺口条目与"何时接入"，仅删"旧版位置/旧版消费链"
  等引用列。
- 验收：台账仍能独立表达每条缺口与接入条件；无旧库路径引用。

## 8. 验收标准

> **统一声明**：除非使用者明确许可，否则跳过验收测试工作（`AGENTS.md` 硬性约束 §9）。

- [ ] `l3-dispatcher-planner/` 下 `tools.vla.geometry` / `vla/geometry` 零匹配
- [ ] `tools/vla/` 之外，`旧版|旧库|旧链|迁移前|迁入|逐字|留壳|对齐旧` 零匹配
- [ ] §2.4 功能性"旧"行仍在（人工比对清单）
- [ ] `git diff --stat` 仅含注释/docstring 变更 + 1 处 rename，无逻辑行改动
- [ ] import 自检：`python -c "import dispatcher.tools.vla.vla_geometry"`（环境允许时）

## 9. 风险与对策

| 风险 | 影响 | 对策 |
|------|------|------|
| 误删功能性"旧"（旧代次/旧结果/旧 call） | 注释语义丢失、误导 | §2.4 白名单逐条比对；grep 门禁排除 |
| 改名遗漏 import 点 | 运行期 ImportError | 全仓 grep `vla.geometry` + `vla/geometry` 双模式；`setup.py` 用 `find_packages()` 无需改 |
| docstring 改写破坏缩进/引号 | 语法错误 | 逐文件 `GetDiagnostics`/编译自检 |
| `test_vla_*` 属"vla 测试"是否算 vla 模块外存在歧义 | 范围偏差 | 本方案按"vla 模块 = `tools/vla/` 源码包"执行，tests 计入清理；如需保留 tests 说明，用户在确认时指出即可 |
| P3 触及 `doc/`，与"载体=.py+tests"表述冲突 | 越界改动 | P3 单列，待用户确认后再动 |

## 10. 修改点清单汇总

| 文件 | 动作 | 说明 |
|------|------|------|
| `tools/vla/geometry.py` → `tools/vla/vla_geometry.py` | rename | P0 |
| `tools/vla/ports.py` | edit | import 改名 |
| `tools/vla/vla_skill.py` | edit | import + 2 注释改名 |
| `tools/vla/__init__.py` | edit | 注释改名 |
| `dispatcher_node.py` | edit | import 改名 + 删迁移引用 |
| `dispatcher/engine.py` | edit | 删迁移引用 |
| `dispatcher/execution/waypoint_execution.py` | edit | 删迁移引用 |
| `dispatcher/execution/skill_host.py` | edit | 删迁移引用 |
| `dispatcher/execution/composition.py` | edit | 删迁移引用 |
| `dispatcher/ros_adapter/params_ros.py` | edit | 删迁移引用 |
| `dispatcher/ros_adapter/clock_ros.py` | edit | 删迁移引用 |
| `dispatcher/ros_adapter/core_channels_ros.py` | edit | 删迁移引用 |
| `dispatcher/tools/protocol.py` | edit | 删迁移引用 |
| `dispatcher/core/prompt_queue.py` | edit | 删迁移引用 |
| `dispatcher/core/telemetry.py` | edit | 删迁移引用 |
| `dispatcher/core/actuators.py` | edit | 删迁移引用 |
| `dispatcher/core/task_phase.py` | edit | 删迁移引用 |
| `dispatcher/utils/rpc_plane.py` | edit | 删迁移引用 |
| `tests/perception/test_vla_geometry.py` | edit | import 改名 + 删旧链对照 |
| `tests/core-boundary/test_vla_skill.py` | edit | 删旧链对照 |
| `tests/core-boundary/test_vla_composition.py` | edit | import 改名 + 删旧链对照 |
| `tests/core-boundary/test_vla_skill_host.py` | edit | 删旧链对照 |
| `doc/.../rest/dispatcher-deferred-dependencies.md` | edit | P3：保留条目、去旧版引用 |

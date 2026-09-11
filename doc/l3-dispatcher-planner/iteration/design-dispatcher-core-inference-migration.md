# dispatcher core + run-inference 首轮迁入方案

> 摘要：将旧仓库（DiffAgent2 旧版）dispatcher 包的 `perception/base_policy.py`
> 与裁剪后的 `engine.py`（仅保留 core + run-inference 两块功能）迁入新仓库
> （DiffAgent2 新版）`l3-dispatcher-planner/ros_packages/dispatcher/`，随迁两个
> `__init__.py` 包骨架。engine 采用「裁剪手术」：迁入版只含 core + run-inference
> 方法，对未迁对象的调用逐处摘除，包内无法摘除的 5 个 import 记录为已知断裂。
> 依据：旧仓库源码逐行复核（行号均已验证）；范围约束来自用户本轮指令。

## 0. 元信息

| 项 | 值 |
|----|----|
| 日期 | 2026-09-10 |
| 目标路径 | `l3-dispatcher-planner/ros_packages/dispatcher/dispatcher/` |
| 状态 | done（2026-09-10 执行并评审放行，验收 V1-V6 全过，见附录） |
| 关联文档 | 方案模板 `doc/l3-dispatcher-planner/iteration/_TEMPLATE.md`；无姊妹篇（本轮为首迁） |
| 源（旧仓库） | `/home/zhywwyzh/workspace/Diff-Agent2/diff-dockers/drone_projects/l3-dispatcher-planner/ros_packages/dispatcher/`（下称 `OLD/`） |
| 目标（新仓库） | `/home/zhywwyzh/workspace/Diff-Agent2.0/l3-dispatcher-planner/ros_packages/dispatcher/`（下称 `NEW/`） |

## 1. 背景与动机

新仓库 `l3-dispatcher-planner/` 目前只有 `ros_packages/planner`（C++ 规划器）与
空的 `ros_packages/dispatcher`、`docker` 目录骨架，Python 策略层尚未迁入。
本轮按用户明确范围启动首轮迁移：只迁 `base_policy.py`（感知基类，整体原样）
与 `engine.py`（主状态机，仅 core + run-inference 两块），为后续
state/config/slog/skill 等模块的逐轮迁入建立落点与基线。

动机：
1. dispatcher 是 l3 的决策核心，尽早落位新仓库可让后续每轮迁移都有 diff 基线。
2. engine.py 2094 行中技能族（vla/flight/scene_nav/grasp）、zenoh 中间件、
   reset 服务等占比大且依赖面广，首轮全量迁入会把 tools/ 整棵树拖进来；
   「core + run-inference 先行」是把依赖图切成可管理轮次的最小闭环。

## 2. 现状事实（问题清单）

> 行号均指向旧仓库源文件，已逐条复核。

- [x] `OLD/dispatcher/dispatcher/engine.py`（2094 行）：
  - [x] L87-113 `PendingAction` dataclass；L117-2042 `DispatcherEngine(BasePolicyNode)`；
    L2045-2085 `create_dispatcher_engine`；L2088-2094 `start_dispatcher_workers`。
  - [x] L48-84 头部 import 拉入 17 个包内模块；其中
    `text_utils`、`executor`、`clean_object_name`、`MISSION_TYPE`、`shutil`、`hashlib`、`pc2`
    为死 import（复核另确认 `logging`、`re`、`math`、`copy`、`queue`、`pdb`、
    `replace`、`PointCloud2` 亦为死符号）。
  - [x] core 方法对不迁对象的方法级耦合（非 import 级）：
    `_notify_skills`×3（L1271、L1525、L1727）；`_recording.*` 共 21 处
    （L571-572、L699-700、L728-729、L776-777、L1261、L1274、L1293、L1518、
    L1613-1614、L1671-1672、L1695、L1704-1706、L1769、L1891、L1932-1933、L1950）；
    `_action_owner_skill.action_done_gate`（L1648-1654，自带 None 回退）；
    zenoh_middleware 出口（L1208-1209，自带 None 守卫）；
    `start_dispatcher_workers` 含 grasp 线程（L2092-2093）。
  - [x] `__init__`（L122-467）实例化的不迁对象：`GraspWorker` L290、
    reset/stack_reset 服务 L294-304、`RecordingService` L311、`VlmFacade` L314、
    `SceneNavSkill` L321、`VlaSkill` L325、`GraphEditSkill/FlightSkill` L332-333、
    `_skills` 注册表 L334-346、graph_source 延迟加载 L258-276（try/except 容错）。
- [x] `OLD/dispatcher/dispatcher/perception/base_policy.py`（3078 行）：
  - [x] 包内依赖仅 2 个：`dispatcher.state.MISSION_TYPE`（L35）、
    `dispatcher.perception.pointcloud_accumulator`（L36-39）——均不在本轮范围。
  - [x] 隐式属性契约：base_policy L1770 读 `self.first_frame`（由 engine
    `__init__` L155 注入）；`is_stable/stable_height` 等由 engine 侧
    `set_defaults/apply_config` 注入（旧 `config.py` L193-235 `UAV_POLICY_DEFAULTS`）。
- [x] `OLD/dispatcher/dispatcher/recording.py` L121-142：
  `_current_task_id_value()` 即读 `engine.current_task_id`；
  `_current_agent_prompt_frame_id()` 即读 `engine.latest_agent_prompt_frame_id`
  （缺省 `"Null"`）——send_task_goal 的 frame_id 替换依据（见 §4.6 决策 11）。
- [x] `OLD/dispatcher/dispatcher/tools/vla/vla_skill.py` L32-37 头注明确
  「留壳（技能经 host 读写）」契约字段：`first_rgb/first_bbox/first_frame/
  bbox/result/nav_mask/_partial_bbox_recenter_attempts/thinking_debug_dir/
  last_thinking_debug_dir` 及 `first_image_pub/current_image_pub`
  （vla_skill L240-241 经 `host.publish_image` 消费，`publish_image` 定义于
  base_policy.py L2821）。
- [x] 包级死属性复核（全包 grep 零引用）：`mllm_message`（engine L149）、
  `exploration_clear_map_mode`（L209）、`last_command`（L135）、
  `origin_record_index`（L199，仅 recording 读且其调用点本轮摘除）、
  `action_pub`（L365）。
- [x] 新仓库 `NEW/ros_packages/dispatcher/` 为空目录；`doc/l3-dispatcher-planner/iteration/`
  不存在（需创建）。
- [x] `OLD/package.xml` L23-28 exec_depend 缺 `nav_msgs`、`visualization_msgs`、
  `message_filters`（base_policy.py L23/L25/L30 实际依赖）——既有缺口，
  package.xml 不在本轮范围，仅记录。

## 3. 目标与约束

- **目标**：
  1. `NEW/` 下形成可运行的包骨架：`dispatcher/dispatcher/__init__.py`、
     `dispatcher/dispatcher/engine.py`、`dispatcher/dispatcher/perception/__init__.py`、
     `dispatcher/dispatcher/perception/base_policy.py`。
  2. 迁入版 engine 只含 core + run-inference；未手术方法与旧文件字节级一致；
     手术方法仅 §6 列出的行发生变化。
  3. 迁入版静态自洽：不引用任何因手术而消失的模块/属性/方法；语法通过
     `py_compile`；属性闭包通过 AST 校验。
- **Non-Goals**（本轮明确不做）：
  - 不迁 `state.py`、`config.py`、`tools/config.py`、`slog.py`、`skill_api.py`、
    `recording.py`、tools 技能族、`dispatcher_node.py`、`package.xml`、
    `CMakeLists.txt`、`API.md`。
  - 不改 `package.xml` 依赖缺口。
  - 不做运行时冒烟（入口与 5 个依赖模块未迁，import 必然失败；运行验收
    留待依赖轮次，见 §8）。
- **硬边界**：
  - 禁止新设计转接器来转接新旧接口（除非用户明确允许）——本方案不引入任何
    桥接层；空注册表与 None 守卫均为原代码路径，论证见 §4.6 决策 8/9。
  - 被裁掉的旧功能直接删除，不留注释桩、不注释掉（§6 全量清单）。

## 4. 方案决策

### 4.1 目标目录树

```
ros_packages/dispatcher/
  dispatcher/
    __init__.py            # 随迁（结构必需），2 行原样
    engine.py              # 裁剪手术版（core + run-inference）
    perception/
      __init__.py          # 随迁（结构必需），1 行原样
      base_policy.py       # 原样整体迁移（3078 行字节级不变）
```

说明：`ros_packages/dispatcher/` 包级文件（package.xml 等）留待后续轮次，
本轮 Python 包内 4 文件即可构成可 import 的目录结构（在依赖模块迁入后）。

### 4.2 命名规范表

| 类型 | 规范 | 示例 |
|------|------|------|
| 文件 | 沿用旧仓库名，不改名（迁移非重构） | `engine.py`、`base_policy.py` |
| 类 | 不变 | `DispatcherEngine`、`BasePolicyNode`、`PendingAction` |
| 函数/方法 | 不变；被删方法名不复用为新语义 | `run_inference`、`_run_inference_loop` |
| 方案文档 | `design-dispatcher-*.md`（沿旧仓库惯例） | 本文档 |

### 4.3 裁剪总策略：裁剪手术 + 依赖断裂分级

- **方法级**：迁入版只保留 core（44 个类方法含 `__init__`）与 run-inference
  （`_run_inference_loop`/`_recover_inference_after_exception`/`run_inference`/
  `create_dispatcher_engine`/`start_dispatcher_workers`）；其余 17 个方法/property
  + 1 个类属性整体删除（§6）。
- **import 分级**：
  - A 级（摘除）：因裁剪而不再被引用的 import——vla/vlm_facade、vla_skill、
    helpers、text_utils、executor、model、grasp.workflow、recording、
    scene_nav 双模块，及全部死符号（§6.3）。
  - B 级（保留为已知断裂）：core 运行期仍引用符号的 5 个包内模块——
    `dispatcher.state`、`dispatcher.tools.config`、`dispatcher.config`、
    `dispatcher.skill_api`（`SkillVerdict`）、`dispatcher.slog`
    （`StructuredLogger`）。它们在新仓库尚不存在，`py_compile` 通过但运行期
    import 失败，与 base_policy 的 2 个断裂同列（§8 记录），待对应轮次补齐。
    ——「对未迁模块的 import 全部摘除」按此解释执行：摘除对象是「因裁剪而
    失去引用」的 import；仍有引用的摘除会让保留方法集体 NameError，违背
    自洽目标。
  - C 级（转为有效）：`dispatcher.perception.base_policy` 随本轮迁入后即有效。
- **手术原则**：
  1. `__init__` 重建为 core-only（删净不迁子系统专有状态）；
  2. 其余方法只在「会引用已删除对象/方法」的行做手术，其余逐字节保留；
  3. 被删调用一律整行/整分支删除，不留桩。

### 4.4 用户决策点裁决表

| # | 决策点 | 裁决 | 理由 |
|---|--------|------|------|
| 1 | engine 裁剪策略 | 裁剪手术（§4.3/§6/§7） | 用户推荐项；与「禁止转接器/禁止桩」约束一致 |
| 2 | 保留方法→「其他」方法调用取舍 | 逐条见 §4.5 | 复核结论：仅 2 类命中 |
| 3 | base_policy 是否顺带迁 state/pointcloud_accumulator | 否，原样整体迁移，2 个断裂记录 | 用户范围约束「只迁两个文件」；扩界需把 config 注入语义一并拖入，破坏轮次边界；断裂可静态记录、零运行时风险（本轮无运行时） |
| 4 | 包骨架 `__init__.py` | 随迁（原样 2 文件） | Python 包结构必需，属结构迁移非功能迁移 |
| 5 | `start_dispatcher_workers` grasp 线程 L2092-2093 | 删除，仅剩 run_inference 线程 | 用户确认；grasp 属「其他」功能 |
| 6 | 自洽验收 | 静态验收（§8 四道命令） | 运行时验收依赖未迁模块，留待后续轮次 |

### 4.5 决策点 2 复核：run-inference 调用闭环 + 保留方法对「其他」方法的调用

**`_run_inference_loop`（L1778-2004）调用集闭环复核**（全部命中保留集，
标注 ✂ 的为手术摘除点）：

| 调用点（旧行号） | 目标 | 归属 | 处置 |
|---|---|---|---|
| L1826-1827 | `DISPATCHER_STATE.INIT`、`rospy.Rate` | state import（B 级） | 保留 |
| L1835-1844 | `get_frame_snapshot`、`first_image` | base_policy / core 属性 | 保留 |
| L1836-1840、L1877-1881 | `_decision_chain_wait_diag` | core | 保留 |
| L1852-1853 | `_enter_global_stop("stop")` | core | 保留 |
| L1867-1873 | `_set_dispatcher_state`、`emergency_stop_pub` | core | 保留 |
| L1891 ✂ | `_recording._publish_latest_log_if_pending()` | recording | 删行 |
| L1892-1895 | `if_plan`、`action_in_progress` | core 属性 | 保留 |
| L1920 | `_reset_plan_cycle_if_needed` | core | 保留（内部 ✂ 一处广播） |
| L1923-1947 | `command_content` 解包、`_telemetry`、`_validate_active_tool` | core | 保留（✂ L1932-1933 kwargs） |
| L1950 ✂ | `_recording._record_origin_if_needed()` | recording | 删行 |
| L1953 | `_handle_plan_tool` | core | 保留（方法体零手术） |
| L1962-1981 | `_action_owner_skill`/`_skills` 查找、`_action_done` | core（None 守卫原代码） | 保留 |
| L1988-1993 | `_handle_post_action` | core | 保留（内部 ✂ 一处记录） |
| L1996-1998 | `rospy.signal_shutdown` | 外部 | 保留 |

**保留方法 → 「其他」方法调用全量清单**（全文件复核，仅以下命中）：

| 调用方（保留） | 被调（原归类「其他」） | 裁决 | 理由 |
|---|---|---|---|
| `send_task_goal` L605-608（dry_run 分支） | `_intercept_task_goal` L620-666 | **一并保留该方法（重新归入 core）** | ① 零不迁依赖（仅 rospy/GoalStatus/局部 import TaskActionResult/`dry_run_goal_pub`/`_telemetry`/`_task_action_done_cb`，全部在保留集）；② 删分支反而扩大 send_task_goal 手术面（L603+L605-609）；③ dry-run 是迁入版日后无 FCU 联调 FSM 的验收路径。dry-run 属性块 L429-437 与 `dry_run_goal_pub` L450-455 据此一并保留 |
| `_enter_global_stop` L1539 | `_publish_emergency_hold_position` L1459-1488 | **删调用行 + 删该方法** | 该方法依赖 `make_hover_pose`（tools.helpers，未迁）与 `_recording._current_pose_list()`（未迁），保留它就得扩迁移范围或改写方法体；core-only 引擎本就无动作下发（动作归技能），`/command/emergency_stop` Empty（L1538，保留）仍是硬停信号 |
| `_start_prompt_task` L1271 / `_enter_global_stop` L1525 / `_reset_plan_cycle_if_needed` L1727 | `_notify_skills` L988-995 | **删 3 处调用 + 删方法** | 用户决策点 1 点名；空注册表下广播为死代码，按「过期必删」摘除 |
| （其余 41 个保留方法） | — | 无「其他」调用 | 逐方法复核确认 |

### 4.6 补充裁决（复核中发现，用户未预列）

| # | 事项 | 裁决 | 理由 |
|---|------|------|------|
| 7 | `_intercept_task_goal` 归类 | 由「其他」改判保留（见 §4.5） | 见 §4.5 表 |
| 8 | `_skills` 注册表 | `__init__` 中以 `self._skills: dict = {}` 空表保留；`_handle_plan_tool` L1392-1395、`_action_done` L1648-1654、`_handle_post_action` L1743-1747、`_run_inference_loop` L1966-1972 的 `.get()` 查找原样保留 | 注册表是 P3 架构 core 的分发机制本体，空表是其合法退化态（原 None 守卫即为此设计）；这不是桥接新旧接口的转接器，后续技能轮次直接填表复活。删查找需重构 4 个 core 方法，违背最小手术 |
| 9 | zenoh 出口（`_publish_task_phase` L1208-1209） | 保留 `zenoh_middleware = None` 初始化（L288）与 None 守卫分支 | 原代码自带守卫；保留使 `_publish_task_phase` 保持零手术（字节级不变）；`bind_tool_middleware` 未迁期间恒为 None，非转接器（不桥接任何新接口），中间件轮次迁入即复活 |
| 10 | telemetry 中 `task_id=/frame_id=` kwargs（7 个事件） | 直接删除 kwargs | 用户决策点 1 的默认处置；事件名保留、字段临时缺失，recording 轮次按旧文件恢复（§9 风险 4） |
| 11 | `send_task_goal` L568-573 `goal.frame_id` | 用 `self.latest_agent_prompt_frame_id` 等价替换（同为 `"Null"` 哨兵） | 该字段是 TaskActionGoal 协议字段（非纯遥测）；recording.py L137-142 证实 recording 读的就是这个 engine 属性，替换后语义逐字等价 |
| 12 | vla 留壳契约属性 | `first_rgb`(L136)、`bbox/first_bbox`(L176-177)、`result/nav_mask`(L150-151)、`_partial_bbox_recenter_attempts`(L182)、`thinking_debug_dir/last_thinking_debug_dir`(L279-283)、`first_image_pub/current_image_pub`(L385-391)、`first_frame`(L155)、`log_session_tag`(L218) 全部保留 | vla_skill.py L32-37 明文契约 + base_policy L1770 读 `first_frame`；保留避免 vla 轮次二次手术 engine |
| 13 | 包级死属性 | `mllm_message`(L149)、`exploration_clear_map_mode`(L209)、`last_command`(L135)、`origin_record_index`(L199)、`action_pub`(L365) 删除 | 全包 grep 零引用（§2 证据） |
| 14 | `origin_state`(L156)、`previous_return_record_cursor`(L200) | 初始化保留；方法体内对其的写（L1276/L1531）保留，读点随 recording 调用摘除 | 恒 None/恒 None 写入为惰性状态，删除需额外手术两个方法体，收益为零；recording 轮次复活读写 |
| 15 | `model.py` 的 `ToolCall/SkillCommand` import | 摘除（A 级） | 保留方法中仅出现在类型注解（`_validate_active_tool`/`_handle_plan_tool` 签名）；L12 `from __future__ import annotations` 使注解惰性化，摘除 import 零运行时风险；model 轮次随迁恢复 |

### 4.7 接口形态

迁入版对外暴露面 = core 状态机 + SkillHost 端口（`arm_action`/
`consume_head_prompt`/`advance_prompt`/`capture_task_generation`/
`task_generation_valid`/`stash_task_result`/`pop_task_result`/
`send_task_goal`/`publish_mode_burst`/`_latest_prompt_frame`/
`_finish_external_task_dispatch`）+ run-inference 入口
（`create_dispatcher_engine`/`start_dispatcher_workers`）。这些端口在
core-only 状态下无引擎内调用方（调用方是未迁的技能/中间件），属为后续轮次
预留的原有接口面，非新增设计。

### 4.8 旧接口 → 删除

被裁剪的 17 个方法/property + `STACK_RESET_STEPS` + `__init__` 内 17 处块，
全部直接删除，不保留任何形式的转接口（清单见 §6；「18 处」为初版笔误，
以 §7 2.2 的 17 项为准）。

## 5. 迁移映射表

| 旧路径/命名 | 新路径/命名 | 动作 | 备注 |
|-------------|-------------|------|------|
| `OLD/dispatcher/dispatcher/__init__.py` | `NEW/dispatcher/dispatcher/__init__.py` | copy（rename 无） | 2 行 docstring，结构必需 |
| `OLD/dispatcher/dispatcher/perception/__init__.py` | `NEW/dispatcher/dispatcher/perception/__init__.py` | copy | 1 行 docstring，结构必需 |
| `OLD/dispatcher/dispatcher/perception/base_policy.py` | `NEW/dispatcher/dispatcher/perception/base_policy.py` | copy（原样整体） | 3078 行字节级不变；2 个包内 import 已知断裂 |
| `OLD/dispatcher/dispatcher/engine.py` | `NEW/dispatcher/dispatcher/engine.py` | rewrite（裁剪手术） | 保留 core+run-inference；方法级映射见 §5.1 |

### 5.1 engine.py 方法级映射

**保留-零手术（33 个，字节级不变）**：
`PendingAction`（含 `clear`）、`sync_task_buffers_from_prepare`(L471)、
`publish_monitor_status`(L513)、`_telemetry`(L547)、
`publish_command_content`(L551)、`_intercept_task_goal`(L620，重新归类)、
`publish_mode_burst`(L741)、`_pause_for_new_agent_prompt`(L1063)、
`_has_active_task_to_override`(L1092)、`_is_aggregated_task_id`(L1105)、
`_fmt_wait_age`(L1123)、`_decision_chain_wait_diag`(L1139)、
`_decision_chain_not_ready_reason`(L1153)、`_publish_task_phase`(L1170)、
`consume_head_prompt`(L1229)、`advance_prompt`(L1235)、`_load_next_prompt`(L1321)、
`_validate_active_tool`(L1341)、`_finish_external_task_dispatch`(L1352)、
`_set_if_handle_yaw`(L1366)、`_handle_plan_tool`(L1377)、
`_latest_prompt_frame`(L1405)、`_bump_task_generation`(L1420)、
`_capture_task_generation`(L1430)、`_task_generation_valid`(L1434)、
`_can_accept_new_action`(L1449)、`capture_task_generation`(L1622)、
`task_generation_valid`(L1626)、`stash_task_result`(L1630)、
`pop_task_result`(L1634)、`_recover_inference_after_exception`(L2006)、
`run_inference`(L2025)、`create_dispatcher_engine`(L2045)。

**保留-手术（14 个，仅 §6.2 列出行变化）**：
`__init__`(L122)、`send_task_goal`(L559)、`_task_action_done_cb`(L668)、
`_set_dispatcher_state`(L754)、`_start_prompt_task`(L1239)、
`_handle_get_pre_command`(L1289)、`_enter_global_stop`(L1490)、
`arm_action`(L1568)、`_action_done`(L1640)、`_advance_to_next_prompt`(L1689)、
`_reset_plan_cycle_if_needed`(L1718)、`_handle_post_action`(L1729)、
`_run_inference_loop`(L1778)、`start_dispatcher_workers`(L2088)。

**删除（17 方法/property + 1 类属性）**：见 §6.1。

## 6. 删除清单

### 6.1 方法/类属性级（17+1 项）

| 删除项 | 旧行号 | 理由 |
|--------|--------|------|
| `_planner_fsm_state_str`（property） | L497-509 | 归属 SceneNavSkill（P3.3），技能族未迁，保留方法内零调用方 |
| `_reset_service_callback`（含分区注释 L798-800） | L798-821 | reset 服务未迁（服务注册 L294 一并删） |
| `STACK_RESET_STEPS`（类属性，含注释） | L823-830 | 仅 `_stack_reset_service_callback` 使用 |
| `_stack_reset_service_callback` | L832-865 | stack reset 编排未迁（服务注册 L300 一并删） |
| `bind_tool_middleware` | L867-878 | zenoh 中间件绑定缝未迁；`zenoh_middleware` 恒 None（决策 9） |
| `_activate_tool_call` | L880-894 | 工具准入缝（runtime/中间件调用），未迁 |
| `forward_takeoff_tool` | L896-898 | takeoff 直发缝未迁 |
| `forward_land_tool` | L900-902 | 同上 |
| `forward_emergency_stop_tool` | L904-920 | 同上 |
| `start_tool_workflow` | L922-965 | 工具工作流入口未迁 |
| `cancel_tool_call` | L967-986 | 取消缝未迁 |
| `_notify_skills` | L988-995 | 用户决策点 1 点名删除；3 处调用一并删 |
| `_handle_takeoff_land` | L997-1059 | takeoff/land 直通道未迁（`takeoff_land_pub` 一并删） |
| `_handle_global_control_command` | L1079-1090 | 唯一调用方 `forward_emergency_stop_tool` 已删 |
| `_publish_scene_objects` | L1128-1137 | scene_nav 图遥测未迁（pub+timer 一并删） |
| `publish_phase` | L1221-1223 | SkillHost 事件出口薄包装，引擎内零调用方，技能轮次随迁 |
| `_publish_emergency_hold_position` | L1459-1488 | 依赖 `make_hover_pose`+`_recording`（决策见 §4.5） |
| `vlm`（property） | L1558-1561 | `VlmFacade` 未迁（`_vlm` 初始化一并删） |
| `recording`（property） | L1563-1566 | `RecordingService` 未迁 |

### 6.2 方法体手术级（14 方法，按旧行号）

| 方法 | 手术行 | 动作 |
|------|--------|------|
| `__init__` | L135、L149、L193-199、L209、L215-216、L225-239、L240-251、L258-276、L289-290、L292-304、L306-314、L319-349（替换）、L365、L392-396、L419-427、L444-449 | 删除/替换，见 §7.4 逐项 |
| `send_task_goal` | L568-573 | 替换为 §7.5 片段 A |
| `_task_action_done_cb` | L699-700、L728-729 | 删 `task_id=/frame_id=` kwargs |
| `_set_dispatcher_state` | L776-777 | 删 `task_id=/frame_id=` kwargs |
| `_start_prompt_task` | L1260-1266 | 删 override 记录 if 块（体仅 recording 调用） |
| | L1269-1274 | 删广播注释+`_notify_skills("on_new_prompt_task")`+frame 快照行+origin if 块（快照行唯一消费者是已删 origin 块） |
| `_handle_get_pre_command` | L1292-1293 | 删 origin if 块 |
| `_enter_global_stop` | L1517-1521 | 删 stop 记录 if 块 |
| | L1522-1525 | 删广播注释+`_notify_skills("on_global_stop")` |
| | L1539 | 删 `self._publish_emergency_hold_position()`（保留 L1537-1538 的 `publish_hold`→Empty 发布） |
| `arm_action` | L1613-1614 | 删 `task_id=/frame_id=` kwargs |
| `_action_done` | L1671-1672 | 删 `task_id=/frame_id=` kwargs |
| `_advance_to_next_prompt` | L1695-1700 | 删 `_record_task_stop_event` 语句 |
| | L1704-1706 | 删 `task_id=/frame_id=/completed_prompt=` kwargs（`next_prompt` 本地计算，保留） |
| `_reset_plan_cycle_if_needed` | L1726-1727 | 删广播注释+`_notify_skills("on_plan_cycle_reset")` |
| `_handle_post_action` | L1769-1772 | 删 `_record_task_stop_event` 语句 |
| `_run_inference_loop` | L1891、L1932-1933、L1950 | 删 3 处（见 §4.5 表） |
| `start_dispatcher_workers` | L2092-2093 | 删 grasp 两行 |

### 6.3 import 级

| 删除项 | 旧行号 | 理由 |
|--------|--------|------|
| `import logging/re/math/shutil/hashlib/copy/queue/pdb` | L15,16,19,20,21,22,23,28 | 死 import（复核零引用） |
| `# import tqdm`、`# from mpl_toolkits...` | L29,32 | 死注释 import |
| `from dataclasses import ... replace` 之 `replace` | L26 | 零引用 |
| `sensor_msgs.point_cloud2 as pc2` | L35 | 零引用 |
| `Trigger, TriggerResponse` | L37 | 仅被删 reset 服务/方法使用 |
| `CompressedImage`、`PointCloud2` | L38 | 仅被删 grasp 发布器使用 / 零引用 |
| `TakeoffLand` | L42 | 仅被删 takeoff/land 路径使用 |
| `dispatcher.tools.vla.vlm_facade` | L48-49 | `VlmFacade` 实例化已删 |
| `dispatcher.tools.vla.vla_skill` | L50 | 技能未迁 |
| `dispatcher.tools.helpers`（3 符号） | L65-69 | `make_hover_pose` 随删方法去、`write_json` 随日志引导块删、`clean_object_name` 死 |
| `dispatcher.tools.text_utils` | L70-72 | 死 |
| `dispatcher.tools.executor` | L73 | 死 |
| `dispatcher.tools.model` | L74 | 决策 15（注解惰性化） |
| `dispatcher.tools.scene_nav.graph_skill` | L76 | 技能未迁 |
| `dispatcher.tools.flight.flight_skill` | L77 | 技能未迁 |
| `dispatcher.tools.grasp.workflow` | L79 | grasp 未迁 |
| `dispatcher.recording` | L80 | `RecordingService` 实例化已删 |
| `dispatcher.tools.scene_nav.scene_nav_skill` | L81 | 技能未迁 |
| `MISSION_TYPE`（state import 内） | L52 | 死符号 |

保留为已知断裂（B 级，5 个）：`dispatcher.state`（3 符号）、
`dispatcher.tools.config`（`TASK_ID`）、`dispatcher.config`（9 符号）、
`dispatcher.skill_api`（`SkillVerdict`）、`dispatcher.slog`
（`StructuredLogger`）。

### 6.4 遥测 schema 临时变化（记录，非删除项）

7 个 slog 事件临时丢失 `task_id`/`frame_id`（`prompt_advanced` 另失
`completed_prompt`）字段，事件名不变：`task_action_result_received`(L695)、
`task_sequence_failed`(L724)、`dispatcher_state_transition`(L770)、
`action_dispatch_prepared`(L1609)、`task_action_result_ignored`(L1665)、
`prompt_advanced`(L1701)、`prompt_parsed`(L1929)。recording 轮次恢复。

## 7. 实施步骤（P0 单期）

> 行为不变式：除 §6 所列手术点外，迁入文件与旧文件逐字节一致；
> 手术点行为按 §4.5/§4.6 裁决执行。所有删除按**旧行号从大到小**实施，
> 避免行号漂移；每处附 grep 锚点双保险。相邻删除区间之间空行归一
> （类内成员间 1 空行、模块级定义间 2 空行）。

### P0 — 四文件落位 + engine 手术 + 静态验收

- 范围：仅新增文件，不触碰新仓库任何既有文件。

**步骤 1：目录与骨架**

```bash
cd /home/zhywwyzh/workspace/Diff-Agent2.0
git status   # 确认工作区干净、位于预期迭代分支
mkdir -p doc/l3-dispatcher-planner/iteration
mkdir -p l3-dispatcher-planner/ros_packages/dispatcher/dispatcher/perception
OLD=/home/zhywwyzh/workspace/Diff-Agent2/diff-dockers/drone_projects/l3-dispatcher-planner/ros_packages/dispatcher
NEW=/home/zhywwyzh/workspace/Diff-Agent2.0/l3-dispatcher-planner/ros_packages/dispatcher
cp "$OLD/dispatcher/__init__.py"              "$NEW/dispatcher/__init__.py"
cp "$OLD/dispatcher/perception/__init__.py"   "$NEW/dispatcher/perception/__init__.py"
cp "$OLD/dispatcher/perception/base_policy.py" "$NEW/dispatcher/perception/base_policy.py"
cp "$OLD/dispatcher/engine.py"                "$NEW/dispatcher/engine.py"   # 手术底稿
```

**步骤 2：engine.py 手术（在 `$NEW/dispatcher/engine.py` 上，按序执行）**

2.1 删除方法/属性（降序，锚点为各方法 def 行或特征串）：

| 序 | 旧行号 | 锚点（grep 特征） |
|----|--------|--------------------|
| 1 | L2092-2093 | `grasp_thread = threading.Thread` |
| 2 | L1950 | `_record_origin_if_needed` |
| 3 | L1932-1933 | `prompt_parsed` 事件内 `task_id=self._recording` |
| 4 | L1891 | `_publish_latest_log_if_pending` |
| 5 | L1769-1772 | `post_action_wait_for_mission` |
| 6 | L1726-1727 | `on_plan_cycle_reset` |
| 7 | L1704-1706 | `prompt_advanced` 事件内 3 kwargs |
| 8 | L1695-1700 | `stop_reason="advance_to_next_prompt"` |
| 9 | L1671-1672 | `task_action_result_ignored` 事件内 2 kwargs |
| 10 | L1613-1614 | `action_dispatch_prepared` 事件内 2 kwargs |
| 11 | L1563-1566 | `def recording(` |
| 12 | L1558-1561 | `def vlm(` |
| 13 | L1539 | `self._publish_emergency_hold_position()` |
| 14 | L1522-1525 | `on_global_stop` |
| 15 | L1517-1521 | `stop_type="global_stop"` |
| 16 | L1459-1488 | `def _publish_emergency_hold_position` |
| 17 | L1292-1293 | `source="switch_prompt"` |
| 18 | L1269-1274 | `on_new_prompt_task`（连注释）至 `source="first_prompt"` |
| 19 | L1260-1266 | `stop_type="prompt_override"` |
| 20 | L1221-1223 | `def publish_phase` |
| 21 | L1128-1137 | `def _publish_scene_objects` |
| 22 | L1079-1090 | `def _handle_global_control_command` |
| 23 | L997-1059 | `def _handle_takeoff_land` |
| 24 | L988-995 | `def _notify_skills` |
| 25 | L967-986 | `def cancel_tool_call` |
| 26 | L922-965 | `def start_tool_workflow` |
| 27 | L904-920 | `def forward_emergency_stop_tool` |
| 28 | L900-902 | `def forward_land_tool` |
| 29 | L896-898 | `def forward_takeoff_tool` |
| 30 | L880-894 | `def _activate_tool_call` |
| 31 | L867-878 | `def bind_tool_middleware` |
| 32 | L832-865 | `def _stack_reset_service_callback` |
| 33 | L823-830 | `STACK_RESET_STEPS`（连注释） |
| 34 | L798-821 | `def _reset_service_callback`（连 L798-800 分区注释） |
| 35 | L776-777 | `dispatcher_state_transition` 事件内 2 kwargs |
| 36 | L728-729 | `task_sequence_failed` 事件内 2 kwargs |
| 37 | L699-700 | `task_action_result_received` 事件内 2 kwargs |
| 38 | L568-573 | `goal.frame_id`（替换为片段 A，见 2.3） |
| 39 | L497-509 | `def _planner_fsm_state_str` |

2.2 `__init__` 手术（降序）：

| 序 | 旧行号 | 动作 |
|----|--------|------|
| 1 | L444-449 | 删 `takeoff_land_pub` 发布器块 |
| 2 | L419-427 | 删 scene_objects 注释+pub+timer |
| 3 | L392-396 | 删 `grasp_result_image_pub` |
| 4 | L365 | 删 `self.action_pub = None`（保留 L364 `## 运动发布` 注释与 L366 planner_mode_pub） |
| 5 | L319-349 | 替换为片段 B |
| 6 | L306-314 | 删订阅历史注释+`_recording` 实例化+`_vlm` 注释与实例化（保留 L315-318 `_current_plan_skill/_action_owner_skill`） |
| 7 | L292-304 | 删 reset/stack_reset 服务及注释 |
| 8 | L289-290 | 删 `grasp_task_timeout_s`/`_grasp_wf` |
| 9 | L258-276 | 删 graph_source try/except 块 |
| 10 | L240-251 | 删 agent_log 注释+2 属性+loginfo |
| 11 | L225-239 | 删 3 个 log path 属性+3 个 `write_json` |
| 12 | L215-216 | 删 `stop_log_dir` 两行 |
| 13 | L209 | 删 `exploration_clear_map_mode` |
| 14 | L199 | 删 `origin_record_index` |
| 15 | L193-198 | 删 6 个记录缓冲属性 |
| 16 | L149 | 删 `mllm_message` |
| 17 | L135 | 删 `last_command` |

2.3 替换片段（唯一三处新增文本，除此之外不得添加任何代码）：

片段 A —— `send_task_goal` 内 `goal.frame_id` 赋值（替换 L568-573）：

```python
            goal.frame_id = (
                ""
                if self.latest_agent_prompt_frame_id == "Null"
                else self.latest_agent_prompt_frame_id
            )
```

片段 B —— `__init__` 技能注册表位置（替换 L319-349）：

```python
        # P3 技能注册表（本轮迁入为空表：vla/flight/scene_nav/grasp 技能族
        # 未随本轮迁移，_handle_plan_tool/_action_done/_handle_post_action/
        # WAIT_ACTION_FINISH 的注册表查找按原 None 守卫走通用回退路径；
        # 后续轮次技能迁入时在此注册表恢复注册）。
        self._skills: dict = {}
```

片段 C —— `start_dispatcher_workers` 手术后终态（自查用）：

```python
def start_dispatcher_workers(node):
    """Start task-0 workflow workers and return the non-daemon inference thread."""
    inference_thread = threading.Thread(target=node.run_inference)
    inference_thread.start()
    return inference_thread
```

2.4 import 区整体替换（L14-84 → 以下内容；L1-13 的 shebang/编码/docstring/
`from __future__ import annotations` 原样保留）：

```python
import json
import time
import threading
import os
from pathlib import Path
from dataclasses import dataclass
from typing import Any

import numpy as np

import rospy
from actionlib import GoalStatus, SimpleActionClient
from sensor_msgs.msg import Image
from std_msgs.msg import String, Int32, Empty, Bool
from geometry_msgs.msg import Point
from quadrotor_msgs.msg import (
    Instruction,
    TaskActionAction,
    TaskActionGoal,
)

from dispatcher.tools.config import TASK_ID
from dispatcher.state import COMMAND_TYPE, COMMAND_STATUS, DISPATCHER_STATE
from dispatcher.config import (
    CONFIG_KEY_ALIASES,
    UAV_POLICY_DEFAULTS,
    load_yaml,
    set_ros_params,
    set_defaults,
    apply_config,
    merge_config_sections,
    get_nested_config,
    flatten_leaf_params,
    merge_pointcloud_mode_params,
)
from dispatcher.skill_api import SkillVerdict
from dispatcher.slog import StructuredLogger

from dispatcher.perception.base_policy import BasePolicyNode
```

**步骤 3：验收（全部通过才算完成，命令见 §8）**

**步骤 4：提交（可选，遵循仓库门禁）**

- 提交用 `git commit --no-verify`（仓库硬约束 7）；提交前手动跑隐私检索
  （个人用户名/密码/令牌，模式维护在主机本地），无匹配方可提交（硬约束 2）。
- 本轮只新增 4 个代码文件 + 本方案文档，无既有文件改动，无 gitlink 变更。

- 回退：`git clean -f l3-dispatcher-planner/ros_packages/dispatcher/ doc/`（或直接 `rm -rf` 上述新增路径）即可完整回退；
  未提交前无任何残留。

## 8. 验收标准

- [x] **V1 语法**：

```bash
python3 -m py_compile \
  /home/zhywwyzh/workspace/Diff-Agent2.0/l3-dispatcher-planner/ros_packages/dispatcher/dispatcher/engine.py \
  /home/zhywwyzh/workspace/Diff-Agent2.0/l3-dispatcher-planner/ros_packages/dispatcher/dispatcher/perception/base_policy.py
```

- [x] **V2 字节级一致性**（三个原样文件零差异；输出为空即通过）：

```bash
OLD=/home/zhywwyzh/workspace/Diff-Agent2/diff-dockers/drone_projects/l3-dispatcher-planner/ros_packages/dispatcher
NEW=/home/zhywwyzh/workspace/Diff-Agent2.0/l3-dispatcher-planner/ros_packages/dispatcher
cmp "$OLD/dispatcher/__init__.py" "$NEW/dispatcher/__init__.py"
cmp "$OLD/dispatcher/perception/__init__.py" "$NEW/dispatcher/perception/__init__.py"
cmp "$OLD/dispatcher/perception/base_policy.py" "$NEW/dispatcher/perception/base_policy.py"
```

- [x] **V3 负向 grep**（无已删除符号残留；输出为空即通过）：

```bash
grep -nE '(_recording|_notify_skills|VlmFacade|RecordingService|SceneNavSkill|VlaSkill|GraphEditSkill|FlightSkill|GraspWorker|_grasp_wf|takeoff_land_pub|grasp_result_image_pub|_scene_objects_pub|_scene_objects_timer|reset_srv|stack_reset_srv|STACK_RESET_STEPS|_vlm\b|make_hover_pose|write_json|clean_object_name|ToolExecutor|normalize_direction|TakeoffLand|TriggerResponse|CompressedImage|PointCloud2|MISSION_TYPE|pc2\b|import shutil|import hashlib|import pdb|import logging|import copy|import queue|bind_tool_middleware|_activate_tool_call|forward_takeoff_tool|forward_land_tool|forward_emergency_stop_tool|start_tool_workflow|cancel_tool_call|_handle_takeoff_land|_handle_global_control_command|_publish_scene_objects|publish_phase|_publish_emergency_hold_position|_planner_fsm_state_str|_reset_service_callback|_stack_reset_service_callback|mllm_message|exploration_clear_map_mode|last_command|origin_record_index|action_pub)' \
  /home/zhywwyzh/workspace/Diff-Agent2.0/l3-dispatcher-planner/ros_packages/dispatcher/dispatcher/engine.py
```

- [x] **V4 未手术方法分段 diff**（33 个方法与旧文件逐段一致；输出
  `MISMATCH: none` 即通过；对 14 个手术方法打印逐段 diff，人工核对差异
  hunk 与 §6.2 一一对应）：

```bash
python3 - <<'EOF'
import ast
OLD = "/home/zhywwyzh/workspace/Diff-Agent2/diff-dockers/drone_projects/l3-dispatcher-planner/ros_packages/dispatcher/dispatcher/engine.py"
NEW = "/home/zhywwyzh/workspace/Diff-Agent2.0/l3-dispatcher-planner/ros_packages/dispatcher/dispatcher/engine.py"
INTACT = ["sync_task_buffers_from_prepare","publish_monitor_status","_telemetry",
"publish_command_content","_intercept_task_goal","publish_mode_burst",
"clear","_pause_for_new_agent_prompt","_has_active_task_to_override",
"_is_aggregated_task_id","_fmt_wait_age","_decision_chain_wait_diag",
"_decision_chain_not_ready_reason","_publish_task_phase","consume_head_prompt",
"advance_prompt","_load_next_prompt","_validate_active_tool",
"_finish_external_task_dispatch","_set_if_handle_yaw","_handle_plan_tool",
"_latest_prompt_frame","_bump_task_generation","_capture_task_generation",
"_task_generation_valid","_can_accept_new_action","capture_task_generation",
"task_generation_valid","stash_task_result","pop_task_result",
"_recover_inference_after_exception","run_inference","create_dispatcher_engine"]
SURGERED = ["__init__","send_task_goal","_task_action_done_cb",
"_set_dispatcher_state","_start_prompt_task","_handle_get_pre_command",
"_enter_global_stop","arm_action","_action_done","_advance_to_next_prompt",
"_reset_plan_cycle_if_needed","_handle_post_action","_run_inference_loop",
"start_dispatcher_workers"]
def defs(path):
    src = open(path, encoding="utf-8").read()
    lines = src.splitlines()
    out = {}
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.ClassDef):
            for n in node.body:
                if isinstance(n, ast.FunctionDef):
                    out.setdefault(n.name, []).append(
                        "\n".join(lines[n.lineno-1:n.end_lineno]))
        elif isinstance(node, ast.FunctionDef):
            out.setdefault(node.name, []).append(
                "\n".join(lines[node.lineno-1:node.end_lineno]))
    return out
o, n = defs(OLD), defs(NEW)
bad = [k for k in INTACT if o.get(k) != n.get(k)]
print("MISMATCH:", bad if bad else "none")
import difflib
for k in SURGERED:
    a, b = o.get(k, [""])[0].splitlines(), n.get(k, [""])[0].splitlines()
    d = list(difflib.unified_diff(a, b, lineterm="", n=1))
    if d:
        print(f"--- surgered diff: {k} ({len(d)} diff lines) → 对照 §6.2 核对")
EOF
```

- [x] **V5 属性闭包**（迁入版 engine 引用的 `self.X` 全部可溯源；
  `UNRESOLVED: []` 即通过）：

```bash
python3 - <<'EOF'
import ast
NEW_ENG = "/home/zhywwyzh/workspace/Diff-Agent2.0/l3-dispatcher-planner/ros_packages/dispatcher/dispatcher/engine.py"
BASE = "/home/zhywwyzh/workspace/Diff-Agent2.0/l3-dispatcher-planner/ros_packages/dispatcher/dispatcher/perception/base_policy.py"
CONFIG_KEYS = set("""prepare_content nav_tools segment_nav_enabled
search_thinking_enabled inference_timeout task_generation_guard_enabled
_min_action_wait return_publish_mode return_start_timeout_s
return_finish_timeout_s sleep_for_turn action_reach_threshold
search_success_distance_thresh geometry_agree_safe_dis_radius_m
geometry_mismatch_safe_dis_radius_m if_safe_mode max_yaw_search
search_rot_yaw max_z_search search_pos_z d_side d_forward stable_height
min_height max_height is_stable behind_dist bypass_dist reacquire_interval
partial_bbox_recenter_enabled partial_bbox_edge_margin_px
partial_bbox_max_attempts partial_bbox_max_yaw_step_deg
llm_stamp_match_tolerance planner_mode_topic planner_mode_repeat
planner_mode_interval planner_ego_mode_value if_handle_yaw start_yaw_deg
""".split())  # 源：旧仓库 config.py UAV_POLICY_DEFAULTS（L193-235）
def scan(path):
    tree = ast.parse(open(path, encoding="utf-8").read())
    stores, loads, methods = set(), set(), set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            for n in node.body:
                if isinstance(n, ast.FunctionDef):
                    methods.add(n.name)
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) \
                and node.value.id == "self":
            (stores if isinstance(node.ctx, ast.Store) else loads).add(node.attr)
    return stores, loads, methods
es, el, em = scan(NEW_ENG)
bs, bl, bm = scan(BASE)
unresolved = el - (es | em | bm | bs | CONFIG_KEYS)
print("UNRESOLVED:", sorted(unresolved))
EOF
```

- [x] **V6 结构计数**（算式订正）：`grep -c 'def ' NEW/engine.py` == 48
  （44 类方法 + `PendingAction.clear` + `create_dispatcher_engine` +
  `start_dispatcher_workers` + 1 个嵌套函数 `_state_name`——后者为
  `_set_dispatcher_state` 旧 L757 原有嵌套，初版算式漏计，非手术遗漏）。
- [x] **V7 已知断裂登记**（静态事实，非命令）：engine 5 个 B 级 import +
  base_policy 2 个 import 在新仓库暂无对应模块，属预期；`dispatcher_node.py`
  入口未迁，本轮无任何可运行入口。

## 9. 风险与对策

| 风险 | 影响 | 对策 |
|------|------|------|
| 1. 手术遗漏某个 `_recording`/技能调用点，迁入版运行期 AttributeError | 依赖模块迁入后首跑即崩 | V3 负向 grep + V5 属性闭包双闸；`_recording` 全 21 处已枚举（§2） |
| 2. 空注册表退化语义：DISPATCH 态所有工具走 unregistered 回退（logwarn + advance prompt），任务队列被排空 | core-only 中间态无真实动作执行 | 预期行为（§4.6 决策 8），方案显式登记；技能轮次填表后消失 |
| 3. `_enter_global_stop` 的 `publish_hold=True` 路径只剩 `/command/emergency_stop` Empty，无悬停 goal 覆盖旧轨迹 | 急停后不主动发布当前位置悬停 | core-only 无任何动作下发（动作归技能），风险仅在技能迁入后存在；grasp/技能轮次迁入 `make_hover_pose`（tools.helpers）时一并恢复该方法与调用行（git 历史可取） |
| 4. 7 个 slog 事件临时缺 `task_id/frame_id` 字段 | 遥测关联性下降 | §6.4 登记；recording 轮次按旧文件 L699-700 等恢复 kwargs |
| 5. 5 个 B 级 import 断裂被误判为迁移错误 | 返工/误修 | §4.3 分级 + §8 V7 登记；验收基线是 py_compile + 闭包，不是 import 成功 |
| 6. base_policy 的 2 个断裂（state/pointcloud_accumulator）同上 | 同上 | 同上；后续轮次补迁即闭合 |
| 7. 行号漂移导致手术错位 | 切错行 | §7 全部按旧行号降序执行 + grep 锚点双保险 + V4 分段 diff 终检 |
| 8. vla 留壳属性误删导致 vla 轮次 AttributeError | 后续轮次返工 | §4.6 决策 12 白名单保留；V5 闭包亦覆盖 |
| 9. package.xml 依赖缺口（nav_msgs/visualization_msgs/message_filters） | catkin 环境运行期缺消息包 | 既有缺口，非本轮引入；package.xml 轮次补齐（§2 登记） |

回滚路径：本轮纯新增文件，`git clean`/`rm -rf` 新增路径即完全回退（§7 步骤 4）。

## 10. 修改点清单汇总

| 文件 | 动作 | 说明 |
|------|------|------|
| `doc/l3-dispatcher-planner/iteration/design-dispatcher-core-inference-migration.md` | 新增 | 本方案 |
| `NEW/.../ros_packages/dispatcher/dispatcher/__init__.py` | 新增（copy） | 包骨架，原样 2 行 |
| `NEW/.../ros_packages/dispatcher/dispatcher/perception/__init__.py` | 新增（copy） | 包骨架，原样 1 行 |
| `NEW/.../ros_packages/dispatcher/dispatcher/perception/base_policy.py` | 新增（copy） | 原样 3078 行；2 个已知断裂 import |
| `NEW/.../ros_packages/dispatcher/dispatcher/engine.py` | 新增（裁剪手术） | 保留 48 个 def 单元（33 零手术 + 14 手术 + 1 原有嵌套 `_state_name`）；删 17 方法/property + 1 类属性 + `__init__` 17 处块 + import 区重写（§6 全量清单）；实际产出 1530 行 |

---

## 附录：执行与评审记录（2026-09-10）

**执行**：code-fixer 按本方案 §7 P0 执行完毕，84 项锚点断言全部通过；
engine.py 由 2094 行 → 1530 行；手术底稿快照备份于主机本地
`/tmp/engine.py.surgery-baseline`（不入仓库）。

**验收实测**：V1 通过；V2 三文件 `cmp` 零差异；V3 命中 11 行全为
注释/docstring（活代码零残留，判据见 §8 订正；执行者初报 10 行，漏数
新 L138 `on_action_published` 子串命中，评审复核订正为 11）；V4
`MISMATCH: none`，14 个手术方法 diff 与 §6.2 一一对应；V5
`UNRESOLVED: []`；V6 = 48（算式订正见 §8）。

**评审**：deep-oracle 独立复核（手术忠实性逐行对照、run-inference 主循环
依赖闭包、`__init__` 属性闭包、禁止桩/转接器约束），总裁决「放行」，
无 P1/P2 问题。

**登记的后续轮次待办**：

1. P3-1 `engine.py`（新 L1388）孤儿注释「origin 只在首次收到任务时记录一次…」
   悬空描述已删的 `_record_origin_if_needed` 调用：决定保留，recording 轮次
   恢复该调用时重新生效；
2. P3-4 `_has_active_task_to_override`（新 L634）引擎内暂无调用方（原调用点
   随 override 记录块删除）：recording 轮次恢复 override 记录时归位；
3. P3-5 `_handle_post_action` docstring 中「IDLE：记 task_completed」与已删
   记录调用的文档漂移：recording 轮次恢复调用后自动准确；
4. 遗留发现（本轮范围外，用户随后指示处理，2026-09-10 已解决）：父仓
   `.gitignore` 第 4 行 `/l*/` 曾忽略根下 `l3-dispatcher-planner/`；现已加
   `!l3-dispatcher-planner/` 否定规则并订正头部注释，迁入产物恢复 git 可见
   （`git check-ignore` 无命中）。

**未执行**：git add/commit/push（用户未要求提交）。

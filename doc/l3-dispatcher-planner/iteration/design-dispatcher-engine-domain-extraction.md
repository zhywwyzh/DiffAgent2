# dispatcher engine 域外迁（路线 B：字段群 + 协作对象）方案

> 摘要：`engine.py`（实测 784 行）过长的根因是「字段群 + 操作字段的方法」仍集中在引擎本体。
> 路线 A（原地铺方法 + 注释分区）已被用户否决；本方案按用户确认的路线 B，把三类内聚域
> ——prompt 队列生命周期（B）、状态与代次账本（C）、动作完成判定与裁决（D）——按
> 「字段群 + 方法」整体迁出为三个 core 协作对象（`PromptQueue` / `StateLedger` /
> `ActionGate`），预期 engine 784 → 约 500 行（-35% 量级）。同时修订端侧契约
> `l3-core-boundary.spec.md` §4.1 白名单（G2 判定基准，用户已放行）。
>
> 本方案为 S0–S7 之后的新增轮次，不在编排总表 S0–S7 内（锚点见
> `design-dispatcher-execution-plan.md#L15` 与 `#L328` 后续轮次登记）。

## 0. 元信息

| 项 | 值 |
|----|----|
| 日期 | 2026-09-15 |
| 目标路径 | `l3-dispatcher-planner/ros_packages/dispatcher/dispatcher/core/`（新增三个协作对象）；同目录 `engine.py`（减负）；`specs/implemented/inner/l3-core-boundary.spec.md`（白名单修订） |
| 状态 | done |
| 关联文档 | 总纲 `design-dispatcher-architecture-stabilization.md`；编排总表 `design-dispatcher-execution-plan.md`（§2：S0–S7 全 done）；S3 姊妹篇 `design-dispatcher-engine-relocate-non-core.md`（done，历史不改写）；契约 `specs/implemented/inner/l3-core-boundary.spec.md` / `l3-skill-contract.spec.md` / `l3-coding-style.spec.md`；模板 `_TEMPLATE.md`；独立任务 `design-dispatcher-tool-workflow-rename.md`（workflow.py 改名） |

## 1. 背景与动机

1. S3 已完成「端口注入 + 横向协作对象」抽取（`core/` 五个协作对象，engine 1067 → 754 行；
   S3 落盘后随后续迭代增至当前实测 784 行），但主程序仍然过长：`_run_inference_loop` 253 行（含 45 行 FSM docstring）、`__init__` 121 行、
   DISPATCH 分支 74 行，且大量内联辅助方法与其操作的字段群仍附着在 engine 本体。
2. 用户否决「路线 A」——原地把内联代码抽成更多小方法、字段群全部留在 engine、仅用注释分区，
   结果方法数增多、行数不降反升（+55~70），engine 更碎。用户确认「路线 B」方向：按
   「字段群 + 操作字段的方法」整体迁出为协作对象（「放到 core 是合理的」）。
3. 用户已放行修改端侧契约描述文件：`l3-core-boundary.spec.md` §4.1 白名单是 G2 门禁判定基准，
   新增 core 模块/迁走 engine 方法必须先改本节（§4.1 注：「白名单随契约修订维护：新增方法须先改本节」）。
4. `workflow.py` 改名（`ToolWorkflowHost` 宿主模块）是用户点名的**独立任务**，不在本方案范围，
   见 `design-dispatcher-tool-workflow-rename.md`。

## 2. 现状事实（问题清单）

> 每条带「文件路径 + 行号」。

- [ ] `l3-dispatcher-planner/ros_packages/dispatcher/dispatcher/engine.py#L70-L190` — `__init__` 121 行：端口注入、配置落位（`set_defaults` + apply_config 后同步）、任务态字段群、五个协作对象构造全部交错在同一方法。
- [ ] `engine.py#L493-L746` — `_run_inference_loop` 253 行：含 45 行 FSM 转移表 docstring（`#L494-538`），是「主程序过长」的最主要来源。
- [ ] `engine.py#L629-L702` — DISPATCH 分支 74 行：单状态最长分支（frame 检查、队列头解包、prompt_parsed 发射、router 分发、未命中双分支 `_fail_unregistered_dispatch`）。
- [ ] `engine.py#L35-L61` — `PendingAction` + `clear()`：动作上下文 dataclass，仅被 `_action_done` / `_enter_global_stop` / `_recover_inference_after_exception` 消费，属 D 域随迁对象。
- [ ] B 域（prompt 队列生命周期）内联在 engine：`sync_task_buffers_from_prepare`（`#L194-216`）、`_handle_get_pre_command`（`#L251-273`）、`_load_next_prompt`（`#L275-293`）、`_advance_to_next_prompt`（`#L398-416`）、`_reset_plan_cycle_if_needed`（`#L418-425`）。
- [ ] C 域（状态与代次账本）内联在 engine：`_set_dispatcher_state` + 嵌套 `_state_name`（`#L221-248`）、`_bump_task_generation`（`#L296-304`）。
- [ ] D 域（动作完成判定与裁决）内联在 engine：`_action_done`（`#L352-396`，含代次守卫 `#L370-384`）、`_handle_post_action`（`#L427-465`，四裁决机械执行）。
- [ ] 外部调用面三处必须保住语义：`dispatcher_node.py#L107`（`node.sync_task_buffers_from_prepare()`）、`#L113`（`threading.Thread(target=node.run_inference)`）、`#L136`（`ToolControlPlane(engine.tools, …)`）。
- [ ] 配置落地约束：`dispatcher_node.py#L81-L106` `apply_config` 经 `setattr` 机械写 engine 属性（`uav_policy` 段含 `prepare_content`）；`engine.py#L96` `set_defaults(self, UAV_POLICY_DEFAULTS)` 同机制。→ B 域迁出后 `prepare_content` 需「配置落地属性 + 执行队列副本」双位处理（见 §4 决策 1）。
- [ ] 跨仓 SkillHost 契约：`tools/skill_api.py#L140-L151` 共享字段块（`dispatcher_state` / `action_in_progress` / `action_finish` / `action_start_time` / `waypoint` / `last_published_waypoint` / `min_height` / `max_height` / `planner_ego_mode_value`）——外部技能经 `self._host.<field>` 直读/机械写（`#L142-145` 注明「技能武装动作态时置位」「armed/disarm 机械写」）。→ 域字段搬走必须保持 host 同名属性可用（见 §4 决策 2）。
- [ ] 端口对应关系：`skill_api.py#L199-L200` `consume_head_prompt` / `advance_prompt` 端口注释指向 `_advance_to_next_prompt` 等机械操作；`#L193` `fail_sequence` 是 `_task_sequence_failed` 的写口。
- [ ] spec 白名单现状：`l3-core-boundary.spec.md#L77` engine.py 行共 16 方法 + `PendingAction.clear`；`#L85-87` 注记模块级装配函数不计入 core、嵌套 `def` 只允许 `_set_dispatcher_state._state_name`。
- [ ] 快照局限：技能层（`SkillBase` 子类、`arm_action` / `send_task_goal` / `_start_prompt_task` 等）在本仓无 `def` 实现（`tools/skill_api.py` 头注记 + `core/workflow.py#L91-105` 守卫）——SkillHost 契约面在本快照内不可端到端验证，验收只覆盖快照内可判定项。

## 3. 目标与约束

- **目标**：
  1. 按「字段群 + 操作字段的方法」整体迁出三个协作对象（`PromptQueue` / `StateLedger` / `ActionGate`），engine.py 由 784 行降为约 500 行（-35% 量级）；
  2. 统一目录架构与命名规范（平面目录小写单词、类大驼峰职责名词、文件小写下划线）；
  3. 修订 `l3-core-boundary.spec.md` §4.1 白名单（G2 判定基准随修订维护，用户已放行）。
- **Non-Goals**：
  - 不拆分 `_run_inference_loop` 为每态一跳 `_tick_*`（路线 A 已否）；循环保持单方法，分支内改为委托协作对象；
  - 不迁移技能实现层（本仓快照无实现）；`SkillHost` 契约方法名/共享字段名不改；
  - `workflow.py` 改名（独立任务，见 `design-dispatcher-tool-workflow-rename.md`）；
  - 不改动 perception / ros_adapter；不改写 S0–S7 已 done 各期方案历史内容。
- **硬边界**：
  - 先方案后改码：本方案经用户确认后执行；spec 修改已获放行（编排总表 §4.2 G-放行-2 场景）。
  - 禁止转接器：不在 engine 与协作对象之间设计桥接层；被替代的 engine 方法/字段直接删除，不留桩、不留注释调用、不 re-export。
  - 外部调用面保名：`sync_task_buffers_from_prepare` 的公开语义（调用点 `dispatcher_node.py:107`）、`run_inference`（`:113`）、`self.tools`（`:136`）不变。
  - SkillHost 共享字段（`skill_api.py#L140-151`）保持 host 同名可用，外部技能零改动。
  - 只登记不修：执行中发现的新问题不顺手修，登记到本方案「后续轮次待办」。

## 4. 方案决策

- **目标目录树**：

  ```
  ros_packages/dispatcher/dispatcher/core/
    __init__.py            # 空，不 re-export
    ports.py               # 既有（S3）：四类通道 + 节律/关停/日志端口
    telemetry.py           # 既有（S3）：RunTelemetry
    task_phase.py          # 既有（S3）：TaskPhaseBridge
    skill_router.py        # 既有（S3）：SkillRouter
    workflow.py            # 既有（S3）：ToolWorkflowHost —— 改名见独立方案，本轮不动
    actuators.py           # 既有（S3）：PlannerActuators
    prompt_queue.py        # 新增：PromptQueue（B 域：prompt 队列生命周期）
    state_ledger.py        # 新增：StateLedger（C 域：状态与代次账本）
    action_gate.py         # 新增：ActionGate + PendingAction（D 域：动作完成判定与裁决）
  ```

- **命名规范表**：

  | 类型 | 规范 | 示例 |
  |------|------|------|
  | 文件 | 小写下划线名词 | `prompt_queue.py` / `state_ledger.py` / `action_gate.py` |
  | 类 | 大驼峰职责名词 | `PromptQueue` / `StateLedger` / `ActionGate` |
  | 方法 | 与既有 `core/**` 动词同构 | `load_next_prompt` / `set_state` / `action_done` |

- **三类域的字段 / 方法清单**：

  | 协作对象 | 真持有字段（非 SkillHost 面） | 方法（整体迁入） | 经注入 accessor/回调访问的 host 共享字段 |
  |----------|-------------------------------|------------------|------------------------------------------|
  | `PromptQueue`（B 域） | `command_content` / `prepare_content` / `pre_prompt` / `prompt_bf` / `content` / `replan_content` / `previous_return_record_cursor` | `sync_task_buffers_from_prepare(config)`、`pop_next_task()`、`load_next_prompt(delay_sec)`、`advance_head_prompt(...)`、`reset_plan_cycle_if_needed()`、`clear_all()`、读口（`head_command()` / `is_command_empty()` / `is_prepared_empty()`） | `if_plan`（set）、`frame.current_state`（读，供 last_state 快照）、`command_status` / `_task_sequence_failed`（经 ledger） |
  | `StateLedger`（C 域） | `last_state` / `command_type` / `command_status` / `task_generation` / `_task_sequence_failed` | `set_state(new_state, reason)`（含嵌套 `_state_name`）、`bump_task_generation(reason)`、`fail_sequence(reason)`（对齐 `skill_api.fail_sequence` 端口）、`reset_running()`（供 recover） | `dispatcher_state`（set，emit 后 host 写）、`action_generation` / `action_in_progress`（emit 载荷，经 action_snapshot 回调） |
  | `ActionGate`（D 域） | `_action_generation` / `_action_finish_generation` / `_last_action_result` / `pending_action`（`PendingAction` 随迁） | `action_done()`、`handle_post_action()`、`clear_action_state()`（供急停/recover） | `action_in_progress` / `action_finish` / `action_start_time`（读写）、`waypoint` / `frame` / `min_action_wait`（读）、`if_plan`（set）、`dispatcher_state` / `command_status`（经 ledger） |

- **接口形态**：三个协作对象构造注入端口/回调（`runlog`、`task_phase`、`skills`、`ledger`、`queue` 及 accessor 回调集），**永不回引 engine**（A1 门禁：`dispatcher.engine` 零命中），与既有 `core/workflow.py` 的回调注入模式同构（`engine.py#L173-174`：`enter_global_stop=self._enter_global_stop`、`task_generation=lambda: self.task_generation`）。

- **依赖图**：

  ```
  engine
    ├─ prompt_queue ──► state_ledger ──► action_gate     （B → C → D 单向）
    │        │                │                │
    │        └──► skills / task_phase / runlog（端口注入）
    ├─ task_phase / skill_router / workflow / actuators（既有，不回引）
    └─ ports（四类通道 + 节律/日志）
  ```

- **关键决策**：

  1. **`prepare_content` 双位**：engine 保留配置落地属性（`apply_config` / `set_defaults` 经 `setattr` 机械写，见 `dispatcher_node.py#L81-L106`、`engine.py#L96`）；`PromptQueue` 持有执行期队列副本。`dispatcher_node.py#L107` 显式改调 `node.prompt_queue.sync_task_buffers_from_prepare(node.prepare_content)`（传值同步，非转接）。`_enter_global_stop` / recover 的清空改走 `prompt_queue.clear_all()`。
  2. **SkillHost 共享字段留 host**（`dispatcher_state` / `action_in_progress` / `action_finish` / `action_start_time` / `waypoint` / `last_published_waypoint` / `min_height` / `max_height` / `planner_ego_mode_value`）：外部技能经 `self._host.<field>` 直读/机械写（`skill_api.py#L140-151`），字段物理位置留在 engine（状态源在 host，属性真实可写，不经 property 造转接口）；协作对象经构造注入的 accessor/回调读写这些字段。迁走方法所需读取一律走注入面。
  3. **`if_plan` / `global_stop_active` / `first_image` 等保持 engine 字段**：主循环与急停直接读写，不迁。
  4. **E 域留 engine 编排**：`_enter_global_stop`（`#L306-350`）与 `_recover_inference_after_exception`（`#L748-765`）横切三个域的 reset，拆散会破坏急停语义；内部改为委托 `prompt_queue.clear_all()`、`action_gate.clear_action_state()`、`ledger.reset_running()` 等机械操作。
  5. **`_fail_unregistered_dispatch` 留 engine**（`#L467-488`）：域间编排（`task_phase.publish` fail + `ledger.fail_sequence` + `ledger.set_state`）。
  6. **旧接口 → 删除**：engine.py 中被迁走的 10 个方法 + `PendingAction` 类（`#L35-61`）+ 嵌套 `_state_name` 直接删除，无同名空方法、无注释桩。

- **新协作对象接口契约（构造签名与方法级接线，执行照此落实现）**：

  ```python
  # core/prompt_queue.py —— B 域：prompt 队列生命周期
  class PromptQueue:
      def __init__(self, *, runlog, task_phase, skills, ledger,  # 端口/既有协作对象（B→C 依赖 ledger）
                   if_plan_get, if_plan_set,                     # host 字段 accessor（读写 engine.if_plan）
                   last_state_get, last_state_set,               # host 字段 accessor（读写 engine.last_state）
                   frame_state_get): ...                         # -> engine.frame.current_state（无 frame 时为 None）
      def sync_task_buffers_from_prepare(self, config) -> None: ...   # 原 engine#L194-216，入参 config 代替 self.prepare_content
      def pop_next_task(self) -> bool: ...                            # 原 _handle_get_pre_command 机械段 #L255-268
      def load_next_prompt(self, *, delay_sec=0.0) -> bool: ...       # 原 _load_next_prompt #L275-293
      def advance_head_prompt(self, *, pop_current=True, delay_sec=0.0) -> bool: ...  # 原 _advance_to_next_prompt #L398-416
      def reset_plan_cycle_if_needed(self) -> None: ...               # 原 _reset_plan_cycle_if_needed #L418-425
      def clear_all(self) -> None: ...                                # 急停/recover：清任务队列派生字段
      def head_command(self) -> tuple | None: ...                     # DISPATCH 分支取队首 (cmd, skill_command)
      def is_command_empty(self) -> bool: ...                         # DISPATCH 前置保护
      def is_prepared_empty(self) -> bool: ...                        # 是否无准备队列

  # core/state_ledger.py —— C 域：状态与代次账本
  class StateLedger:
      def __init__(self, *, runlog, host_state_set, action_snapshot): ...
      # host_state_set 写 engine.dispatcher_state（SkillHost 共享字段留 host）；
      # action_snapshot() -> dict(action_generation, action_in_progress) 供 emit 载荷。
      def set_state(self, new_state, *, reason="") -> None: ...       # 原 _set_dispatcher_state #L221-248（含嵌套 _state_name）
      def bump_task_generation(self, reason="") -> int: ...           # 原 _bump_task_generation #L296-304
      def fail_sequence(self, reason="") -> None: ...                 # 原 _task_sequence_failed 写口（对齐 skill_api.py#L193 端口）
      def reset_running(self) -> None: ...                            # recover：command_status 复位为 RUNNING

  # core/action_gate.py —— D 域：动作完成判定与裁决（PendingAction 随迁）
  class ActionGate:
      def __init__(self, *, runlog, skills, ledger, queue,           # D 依赖 C、B（gate ← ledger ← queue）
                   host_state_get, host_state_set,                   # 读/写 engine.dispatcher_state
                   if_plan_set,                                      # 写 engine.if_plan
                   action_progress_get, action_progress_set,         # 读/写 engine.action_in_progress
                   action_finish_get, action_finish_set,             # 读/写 engine.action_finish
                   action_start_time_get,                            # 读 engine.action_start_time
                   waypoint_get, frame_get,                          # 读 engine.waypoint / engine.frame
                   min_action_wait_get): ...                         # 读 engine._min_action_wait
      def action_done(self) -> bool: ...                             # 原 _action_done #L352-396
      def handle_post_action(self) -> None: ...                      # 原 _handle_post_action #L427-465
      def clear_action_state(self) -> None: ...                      # 急停/recover：pending_action + action 标志复位
  ```

  接线要点（迁出后的行为映射，字节级保持）：
  - **`pop_next_task`**：内含 `ledger.bump_task_generation("switch_prompt")`、清 `command_content`、pop
    `pre_prompt`、last_state 快照（`frame_state_get()` → `last_state_set()`）、pop `prepare_content` →
    `replan_content`、append `command_content`、`runlog.publish_command_content(…)`、`if_plan_set(True)`、
    经 ledger 置 `command_status=RUNNING`（command_status 归 C 域账本）。`_handle_get_pre_command`
    整体消亡（§6），engine 无残留编排段。
  - **`load_next_prompt`** done 分支：`if_plan_set(False)`；非 `ledger.failed` 时经
    `skills.pop_task_result()` + `task_phase.publish("done", progress=task_phase._task_phase_progress,
    detail="prompt sequence finished", result=…)`（result 载荷同原 #L281-288）；队非空走 `pop_next_task()`。
  - **`advance_head_prompt`**：emit `prompt_advanced`（next_prompt=`prepare_content[1][0]`）、pop
    `command_content[0]`、经 ledger 置 `command_status=ADVANCE_READY` →（若仍 ADVANCE_READY）→
    `MISSION_DONE`、调 `load_next_prompt(delay_sec=…)`。
  - **`set_state`**：emit `dispatcher_state_transition`，载荷含 `task_generation`（自身字段）与
    `action_generation`/`action_in_progress`（经 `action_snapshot()` 回调）；host 写经 `host_state_set`。
    末尾分支保留原 L248-249 语义——仅当 `new_state == WAIT_FOR_MISSION` 时提前 return。
  - **`action_done`**：完成门 `skills.owner_skill()`；代次守卫 emit `task_action_result_ignored` 并
    `action_finish_set(False)`；最小等待经 `min_action_wait_get()`；waypoint 距离检查注释段（#L387-395
    被注释块）逐字保留。
  - **`handle_post_action`**：REPLAN → 清 `pending_action.replan_cmd/replan_reason`、
    `host_state_set(DISPATCH_STATE.DISPATCH)`、`if_plan_set(True)`；NEW_ACTION → 空转；
    ADVANCE → `queue.load_next_prompt()` + 经 ledger 置 MISSION_DONE；IDLE →
    `ledger.set_state(WAIT_FOR_MISSION, reason="post_action:no_advance_ready")`。
  - 所有注入项为构造期传入的回调/端口引用，**不 import `dispatcher.engine`**（A1 门禁零命中）。
  - `PendingAction` 字段与 `clear()` 逐字随迁 `core/action_gate.py`（`#L35-61`）。

- **spec 端侧契约修订内容（`l3-core-boundary.spec.md` §4.1，用户已放行；以下为执行期照抄文本）**：

  修订后 §4.1 白名单表（`engine.py` 行删 10 方法 + `PendingAction.clear`；新增三个协作模块行；
  `core/workflow.py` 行名 → `core/tool_workflow.py` 随独立改名方案同步）：

  ```markdown
  | 模块 | 允许的 `def`（方法名） |
  |------|------------------------|
  | `engine.py` | `__init__`、`_enter_global_stop`、`_run_inference_loop`、`_recover_inference_after_exception`、`run_inference`、`_fail_unregistered_dispatch` |
  | `core/telemetry.py`（`RunTelemetry`） | `__init__`、`emit`、`publish_command_content`、`fmt_wait_age`、`wait_diag` |
  | `core/task_phase.py`（`TaskPhaseBridge`） | `__init__`、`publish`、`set_active_frame`、`set_middleware` |
  | `core/skill_router.py`（`SkillRouter`） | `__init__`、`register`、`get`、`dispatch_plan`、`validate_active_tool`、`owner_skill`、`snapshot_owner`、`stash_task_result`、`pop_task_result` |
  | `core/actuators.py`（`PlannerActuators`） | `__init__`、`set_if_handle_yaw` |
  | `core/tool_workflow.py`（`ToolWorkflowHost`） | `__init__`、`bind_tool_middleware`、`_activate_tool_call`、`start_tool_workflow`、`cancel_tool_call` |
  | `core/prompt_queue.py`（`PromptQueue`） | `__init__`、`sync_task_buffers_from_prepare`、`pop_next_task`、`load_next_prompt`、`advance_head_prompt`、`reset_plan_cycle_if_needed`、`clear_all`、`head_command`、`is_command_empty`、`is_prepared_empty` |
  | `core/state_ledger.py`（`StateLedger`） | `__init__`、`set_state`、`_state_name`、`bump_task_generation`、`fail_sequence`、`reset_running` |
  | `core/action_gate.py`（`ActionGate`） | `__init__`、`action_done`、`handle_post_action`、`clear_action_state`；`PendingAction.clear` |
  | `core/ports.py`（端口 Protocol） | `CoreChannels`：`publish_emergency_stop`、`publish_if_handle_yaw`、`publish_command_content`、`publish_task_phase`；`Ticker`：`sleep`；`RuntimeClock`：`rate`、`is_shutdown`、`request_shutdown`；`LogSink`：`info`、`warn`、`err`、`warn_throttle`（端口名以 S3 方案 §4.5 冻结形态为准） |
  ```

  注记段落同步：
  - 原 `#L87`「嵌套 `def` 只允许 `_set_dispatcher_state._state_name`（状态名反查，随宿主方法）」→
    「嵌套 `def` 只允许 `StateLedger.set_state._state_name`（状态名反查，随宿主方法）」。
  - §4 门禁表 G1–G6 与 §4.1 题注（「集合包含」/「新增方法须先改本节」）文字不变，仅判据随上表更新。

## 5. 迁移映射表

> 旧 → 新 → 动作；行号为 engine.py 实测（2026-09-15）。

| 旧路径/命名 | 新路径/命名 | 动作 | 备注 |
|-------------|-------------|------|------|
| `engine.py#L35-61` `PendingAction` + `clear()` | `core/action_gate.py` `PendingAction`（随 `ActionGate`） | move | 类名/字段逐字保留 |
| `engine.py#L352-396` `_action_done` | `ActionGate.action_done` | move | host 字段经注入 accessor；代次守卫与 `task_action_result_ignored` 事件保留 |
| `engine.py#L427-465` `_handle_post_action` | `ActionGate.handle_post_action` | move | 四裁决机械执行；经注入 ledger/queue/accessor |
| `engine.py#L229-230` 嵌套 `_state_name` | `StateLedger` 内 `_state_name` | move | 随 `set_state` 宿主 |
| `engine.py#L221-248` `_set_dispatcher_state` | `StateLedger.set_state` | move | emit 事件 `dispatcher_state_transition` 键集/事件名不变（`l3-coding-style.spec.md` §6）；载荷跨域字段经 action_snapshot 回调 |
| `engine.py#L296-304` `_bump_task_generation` | `StateLedger.bump_task_generation` | move | |
| `engine.py#L128` `_task_sequence_failed` | `StateLedger` 字段 + `fail_sequence(reason)` | move | 与 `skill_api.py#L193` `fail_sequence` 端口对齐 |
| `engine.py#L194-216` `sync_task_buffers_from_prepare` | `PromptQueue.sync_task_buffers_from_prepare(config)` | move | 入参代替 `self.prepare_content` 读取（双位，§4 决策 1） |
| `engine.py#L255-268` `_handle_get_pre_command` 的队列机械（pop `pre_prompt` / pop `prepare_content` / append `command_content`） | `PromptQueue.pop_next_task` | refactor+move | 编排段（last_state 快照、`publish_command_content`、`if_plan`、`command_status`）全部并入队列方法（经注入 accessor/ledger，接线见 §4）；`_handle_get_pre_command` 整体消亡 |
| `engine.py#L275-293` `_load_next_prompt` | `PromptQueue.load_next_prompt` | move | done 分支经注入 task_phase/skills/ledger（`#L281-288`） |
| `engine.py#L398-416` `_advance_to_next_prompt` | `PromptQueue.advance_head_prompt` | move | 与 `skill_api.py#L200` `advance_prompt` 端口同名 |
| `engine.py#L418-425` `_reset_plan_cycle_if_needed` | `PromptQueue.reset_plan_cycle_if_needed` | move | |
| B 域字段 `command_content` / `prepare_content` / `pre_prompt` / `prompt_bf` / `content` / `replan_content` / `previous_return_record_cursor` | `PromptQueue` 字段 | move | `prepare_content` 双位（§4 决策 1） |
| C 域字段 `last_state` / `command_type` / `command_status` / `task_generation` | `StateLedger` 字段 | move | `dispatcher_state` 除外（SkillHost 面，留 host） |
| D 域字段 `_action_generation` / `_action_finish_generation` / `_last_action_result` / `pending_action` | `ActionGate` 字段 | move | `action_in_progress` / `action_finish` / `action_start_time` 除外（SkillHost 面，留 host） |

## 6. 删除清单

| 删除项 | 理由 |
|--------|------|
| `engine.py` 方法：`sync_task_buffers_from_prepare` / `_set_dispatcher_state` / `_state_name` / `_handle_get_pre_command` / `_load_next_prompt` / `_bump_task_generation` / `_action_done` / `_advance_to_next_prompt` / `_reset_plan_cycle_if_needed` / `_handle_post_action` | 整体迁入协作对象；过期必删，不留桩、不留注释、不 re-export |
| `engine.py` 类 `PendingAction`（含 `clear`） | 随迁 `core/action_gate.py` |
| `engine.py` 字段：B/C/D 域非 SkillHost 面字段（见 §5 表） | 状态单点移至协作对象 |
| `core/` 旧目录外任何桥接代码 | 禁止转接器 |

## 7. 实施步骤（P0/P1 分期）

> 每期包含：范围 + 行为不变式 + 验收 + 回退（编排总表 §4.3 六步流水线执行）。

### P0 — 新增三协作对象 + engine 委托（中间态可运行）

- 范围：
  1. 新建 `core/prompt_queue.py` / `core/state_ledger.py` / `core/action_gate.py`（含随迁 `PendingAction`），方法体自 engine 原样迁入，注入面按 §4 清单构造；
  2. `engine.__init__` 构造三个协作对象（注入端口/回调），被迁字段初始化移入协作对象；
  3. engine 调用点切换：`_run_inference_loop` 各分支、`_enter_global_stop`、`_recover_inference_after_exception`、`_fail_unregistered_dispatch` 内读改经协作对象；
  4. `dispatcher_node.py#L107` 改调 `node.prompt_queue.sync_task_buffers_from_prepare(node.prepare_content)`。
- 行为不变式：FSM 转移、slog 事件（`dispatcher_state_transition` / `task_action_result_ignored` / `prompt_parsed` / `prompt_advanced` / `inference_thread_recovered` 等）事件名与键集逐字不变；SkillHost 共享字段 host 语义不变。
- 验收：`python3 -m py_compile` 全绿；`pytest l3-dispatcher-planner/tests/tool-registry` 全绿；A1 门禁（core 零 `dispatcher.engine` 引用）零命中。
- 回退：恢复 engine 调用点 + 删除三个新文件 + 还原 `dispatcher_node.py:107`。

### P1 — 删除旧实现 + 消除残留 + 契约修订

- 范围：
  1. 删除 `engine.py` 中被迁走的 10 个方法 + `PendingAction` 类 + 已迁字段（§6 清单）；
  2. 修 `l3-core-boundary.spec.md` §4.1 白名单（§10 表）；
  3. 全仓检索旧方法名/字段名在 engine.py 零残留（不留注释桩）。
- 行为不变式：与 P0 相同；删除后行为零变化（纯减负重构）。
- 验收：G2 白名单复算通过（core def 集合 ⊆ 修订后 §4.1）；`grep` 旧符号在 `engine.py` 零命中；A1/A2/py_compile/pytest 全绿。
- 回退：从主机本地快照还原 `engine.py` / spec 白名单（执行前按编排总表 §7.0 快照）。

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
| SkillHost 共享字段被外部技能直读/机械写（`skill_api.py#L140-151`），字段搬走即破坏跨仓契约 | 高 | 共享字段留 host（状态源在 engine 属性）；协作对象经注入 accessor/回调读写，不以 property 造桥 |
| 技能实现层（`SkillBase` 子类、`arm_action` 等）不在本仓快照，`advance_prompt` / `consume_head_prompt` / `fail_sequence` 等端口无法端到端验证 | 中 | 本轮只登记；验收只覆盖快照内可判定项（白名单 + 端口名静态一致） |
| `prepare_content` 双位（配置落地属性 + 队列副本）脱同步 | 中 | 唯一同步点 `dispatcher_node.py:107` 显式传值；急停/recover 清执行副本；执行后回读校验 |
| `dispatcher_state_transition` emit 载荷跨域取值（含 `action_generation` / `action_in_progress`） | 低 | `StateLedger.set_state` 经注入 action_snapshot 回调取数，事件键集不变 |
| 执行中发现新问题（如 `_task_sequence_failed` 全仓无显式复位点） | 低 | 只登记不修，写入本方案「后续轮次待办」，不顺手修 |
| 行号漂移（代码与他期方案同日改动，编排总表 §4.7 文件隔离） | 中 | 执行前按编排总表 §4.3 第 1 步复核锚点；与改名方案（同动 `engine.py`）串行执行 |

**后续轮次待办（只登记）**：
- 任务注入轮次落地后复核 `_task_sequence_failed` 复位语义与 `fail_sequence` 端口接线；
- 技能实现层进快照后，端到端验证 SkillHost 共享字段读写面。

## 10. 修改点清单汇总

| 文件 | 动作 | 说明 |
|------|------|------|
| `l3-dispatcher-planner/ros_packages/dispatcher/dispatcher/core/prompt_queue.py` | 新增 | `PromptQueue`（B 域） |
| `l3-dispatcher-planner/ros_packages/dispatcher/dispatcher/core/state_ledger.py` | 新增 | `StateLedger`（C 域） |
| `l3-dispatcher-planner/ros_packages/dispatcher/dispatcher/core/action_gate.py` | 新增 | `ActionGate` + 随迁 `PendingAction`（D 域） |
| `l3-dispatcher-planner/ros_packages/dispatcher/dispatcher/engine.py` | 修改 | 删 10 方法 + `PendingAction` + 已迁字段；`__init__` 构造三协作对象；调用点改委托；行数 784 → 约 500 |
| `l3-dispatcher-planner/ros_packages/dispatcher/dispatcher_node.py` | 修改 | `#L107` 改调 `node.prompt_queue.sync_task_buffers_from_prepare(node.prepare_content)` |
| `specs/implemented/inner/l3-core-boundary.spec.md` | 修改（已放行） | §4.1 白名单照抄文本见 §4「spec 端侧契约修订内容」：engine.py 行删 10 方法 + `PendingAction.clear`；新增 `core/prompt_queue.py` / `core/state_ledger.py` / `core/action_gate.py` 三行（含各自迁入的 `def` 清单）；`#L87` 嵌套 def 特例改为 `StateLedger.set_state._state_name` |
| `doc/l3-dispatcher-planner/iteration/design-dispatcher-engine-domain-extraction.md` | 新增 | 本方案 |

最终交付记录：结构拆分、核心契约修复与用户追加的全部未迁入链路删除合并交付。`engine.py` 从开始时约 784 行缩为 373 行。`workflow.py` 在重命名阶段逐字迁移，后续通用入口接线与缺失链删除由 `design-dispatcher-unmigrated-chain-removal.md` 接管，故最终文件内容不再与旧版本逐字相同；无旧路径兼容入口。

结构理由已归档至 `specs/implemented/architecture/2026-09-15-dispatcher-core-and-capability-pruning.md`。工作区未提交、未推送。最初既有工具面基线为 52 通过、7 失败；删除无实现链路并将旧连接 queryable 断言对齐现行单 RPC 契约后，最终回归全绿。

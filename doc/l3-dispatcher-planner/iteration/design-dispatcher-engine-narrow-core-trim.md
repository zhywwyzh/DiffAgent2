# dispatcher engine 窄 core 二次裁剪方案

> 摘要：对首轮迁入的 `engine.py`（1530 行）做二次裁剪，以 `run_inference` 的
> self.X 方法调用闭包（22 个方法，已独立复核与调用方结论一致）为保留边界，
> 删除闭包外 22 个类方法中的 20 个（SkillHost 端口 / 任务生命周期端口 /
> /mission/task 动作通道 / 监控遥测面），连带删净 `__init__` 中 15 处只为
> 它们存在的初始化块与 6 处 import。只删代码、不重构 FSM 语义。

## 0. 元信息

| 项 | 值 |
|----|----|
| 日期 | 2026-09-11 |
| 目标路径 | `l3-dispatcher-planner/ros_packages/dispatcher/dispatcher/engine.py`（1530 行当前版） |
| 状态 | done（2026-09-11 执行并评审放行，验收 V1-V7 全过，见附录） |
| 关联文档 | 姊妹篇：`doc/l3-dispatcher-planner/iteration/design-dispatcher-core-inference-migration.md`（首轮迁入方案，其 §4.6 决策 12 留壳白名单与 §4.7 接口形态为本轮收窄对象）；模板：`doc/l3-dispatcher-planner/iteration/_TEMPLATE.md` |
| 对照基准 | Diff-Agent2 旧版源文件仅作语义参考，**本轮全部行号以新仓库 1530 行当前文件为准** |

## 1. 背景与动机

首轮迁移把旧仓库 dispatcher 的 `engine.py` 裁到 1530 行迁入新仓库，但保留了
完整的 SkillHost 端口族（arm_action / send_task_goal / publish_mode_burst /
代次口 / prompt 队列口）与任务生命周期端口（_start_prompt_task /
_task_action_done_cb / 监控 timer）。用户复核后裁决：这些端口是
/mission/task 生成链路的配套设施，在「engine 只承担 core + run-inference」
的目标形态下是无用代码。本轮把引擎收到窄 core：**以 `run_inference` 调用
闭包为唯一保留边界**，闭包外方法全删（两处经复核除外，见 §4.1），使
engine.py 成为纯粹的可静态自洽的 FSM 主状态机骨架，等待后续轮次由新的
外部接线（rpc / mission 轮次）直接驱动队列与状态。

## 2. 现状事实（问题清单）

> 行号均指向新仓库当前文件
> `l3-dispatcher-planner/ros_packages/dispatcher/dispatcher/engine.py`（1530 行）。

- [x] `engine.py#L1-L1530` 当前 48 个 def（44 类方法 + `PendingAction.clear`
  + 嵌套 `_state_name` + `create_dispatcher_engine` + `start_dispatcher_workers`）。
- [x] 以 `run_inference`（L1463）为根的 self.X 方法闭包 = 22 个方法（独立
  复核与调用方 AST 结论一致）：`run_inference`、`_run_inference_loop`、
  `_recover_inference_after_exception`、`_enter_global_stop`、
  `_reset_plan_cycle_if_needed`、`_validate_active_tool`、`_handle_plan_tool`、
  `_action_done`、`_handle_post_action`、`_advance_to_next_prompt`、
  `_load_next_prompt`、`_handle_get_pre_command`、`_publish_task_phase`、
  `_is_aggregated_task_id`、`publish_command_content`、`_set_dispatcher_state`、
  `_set_if_handle_yaw`、`_bump_task_generation`、`_telemetry`、
  `_decision_chain_wait_diag`、`_fmt_wait_age`、`pop_task_result`。
- [x] 闭包外 22 个类方法的外部调用口径逐项查证：
  - [x] `engine.py#L305` — `rospy.Timer(..., self.publish_monitor_status)`：
    publish_monitor_status 唯一接线点是本 timer 注册行。
  - [x] `engine.py#L434` — `done_cb=self._task_action_done_cb`：唯一接线点在
    send_task_goal 内；`engine.py#L485,L490` — _intercept_task_goal 内两处
    模拟回调；`engine.py#L231` — `SimpleActionClient("/mission/task", ...)`。
  - [x] `engine.py#L1522` — `create_dispatcher_engine` 调
    `node.sync_task_buffers_from_prepare()`；`engine.py#L106` — `__init__`
    亦调用 → **sync_task_buffers_from_prepare 不能删**（对调用方「22 个
    删除候选」清单的第一处订正）；`engine.py#L1528` —
    start_dispatcher_workers 只调 run_inference（闭包内）。
  - [x] 岛状互调确认零外部调用方：`_capture_task_generation` 唯一调用方
    L1083（capture_task_generation）、`_task_generation_valid` 唯一调用方
    L1087（task_generation_valid）、`_can_accept_new_action` 唯一调用方
    L1048（arm_action）、`_intercept_task_goal` 唯一调用方 L432
    （send_task_goal dry_run 分支）、`_pause_for_new_agent_prompt` 唯一
    调用方 L788（_start_prompt_task）；`_has_active_task_to_override`、
    `_finish_external_task_dispatch`、`_latest_prompt_frame`、
    `_decision_chain_not_ready_reason`、`consume_head_prompt`、
    `advance_prompt`、`stash_task_result`、`publish_mode_burst`、
    `send_task_goal`、`_start_prompt_task` 在迁入版全文零调用方。
- [x] TASK_ID 引用闭包内仍存活（对「tools.config/TASK_ID 可摘」预判的订正）：
  `engine.py#L109`（__init__）、`#L327`（sync_task_buffers_from_prepare）、
  `#L653-L660`（_is_aggregated_task_id，被 L839 _load_next_prompt 调用）、
  `#L814`（_handle_get_pre_command）→ `from dispatcher.tools.config import
  TASK_ID` 必须保留为 B 级断裂。
- [x] base_policy 隐式契约复核：
  `base_policy.py#L1770` 实读 `self.first_frame`（first_waypoint/first_depth
  首帧判定）→ first_frame 属性必须保留；`base_policy.py#L2821`
  `def publish_image(self, image, pub)` 的 pub 为**参数**而非 self 属性 →
  first_image_pub/current_image_pub 不在 base_policy 契约内，仅是未迁
  vla_skill 的传参目标（旧仓库 vla_skill L240-241）。
- [x] 只为删除方法存在的 `__init__` 状态（唯一引用点均在删除对象内）：
  `#L96-L98` task_generation_guard_enabled（唯一读 L948）、`#L114`
  action_finish_time（唯一写 L516）、`#L119` last_published_waypoint（零引用）、
  `#L122` origin_state（零引用）、`#L127` _last_action_time（唯一写 L871/L1066）、
  `#L160` latest_agent_prompt_frame_id（读点 L395-L396/L783 全在删除方法）、
  `#L197` _active_tool_call（零引用）；发布器/接线：
  `#L223-L226` planner_mode_pub、`#L228-L238` task_action_client、
  `#L243-L249` first_image_pub/current_image_pub、`#L252-L260` monitor 三 pub、
  `#L264-L266` finish_mission_pub、`#L273-L293` dry_run 块、`#L294-L302`
  finish_command/action_in_progress/if_plan 三 pub、`#L304-L305` monitor_timer。
- [x] 闭包内保留方法仍引用的壳属性（删方法后必须继续存在）：pending_action
  （L1004/L1458/L1200-L1201）、action_start_time（L1133）、_action_generation
  （L1118 等）、_action_finish_generation（L1118）、_last_action_result
  （L1193）、_task_sequence_failed（L839）、_task_phase_progress（L842-L843）、
  _active_task_frame_id（L722）、zenoh_middleware（L739）、
  _active_tool_name/_current_plan_skill/_action_owner_skill/_skills、
  previous_return_record_cursor（L1003 写点在闭包内）、first_image
  （L1286/L1289 写点在闭包内）、waypoint（L1135-L1138 读点在 _action_done）。
- [x] 迁入版不存在 agent_prompt_queue（grep 零命中）；任务队列唯一装载入口
  是 sync_task_buffers_from_prepare（配置面）与 _start_prompt_task（本轮删）。

## 3. 目标与约束

- **目标**：
  1. engine.py 收敛为窄 core：保留 24 个类方法（闭包 22 + `__init__` 瘦身版
     + sync_task_buffers_from_prepare）+ `PendingAction` + 两个模块级工厂
     函数；删除 20 个闭包外类方法。
  2. `__init__` 删净只为删除方法存在的初始化；import 区删 6 处（详见 §6.3）。
  3. 静态自洽：py_compile 通过；所有 self.X 方法调用可解析（无孤儿引用）；
     __init__ 属性闭包 UNRESOLVED 为空；def 计数 = 28。
- **Non-Goals**：
  - 不重构 FSM 语义：`_run_inference_loop` 及全部闭包内方法**零手术**
    （本轮对保留方法体一行不改）。
  - 不新增任何任务注入入口 / 动作武装口 / 转接层：窄 core 下 FSM 停在
    WAIT_FOR_MISSION 是预期行为，由后续接线轮次驱动（§4.5）。
  - 不触碰 `base_policy.py`、`dispatcher/__init__.py`、
    `perception/__init__.py`、B 级 5 个包内 import（§4.4）。
  - 不做运行时冒烟（B 级断裂未闭合，沿用首轮静态验收基线）。
- **硬边界**：
  - 禁止转接器：不新增任何桥接新旧接口的层。
  - 禁止注释桩：被删方法/属性/发布器直接删除，不注释掉、不留 docstring 桩
    （保留方法内既有注释/docstring 中对已删端口的语义描述属文档漂移，
    登记 §9 风险 7，不改写）。
  - 不 commit：执行后仅留在工作区，提交需用户显式指令。

## 4. 方案决策

### 4.1 保留边界的总裁决

保留 = run_inference 闭包（22 方法）+ 以下两项经复核的例外：

| 例外 | 裁决 | 理由 |
|------|------|------|
| `__init__` | 保留 + 15 处块删除（§6.2） | 构造必需 |
| `sync_task_buffers_from_prepare`(L309) | 保留 | `create_dispatcher_engine` L1522 与 `__init__` L106 两处模块级/构造期调用方存活；它是配置面（prepare_content）到任务队列的唯一装载路径，删它则工厂函数立即 NameError |

其余 20 个闭包外方法全部删除（§6.1）。

### 4.2 外部调用口径逐项裁决（复核结论）

| # | 口径 | 裁决 | 理由 |
|---|------|------|------|
| a | rospy.Timer 回调 publish_monitor_status（L305 注册） | **删方法 + 删 timer** | 监控遥测面独立于 run-inference 主状态机；迁入版无监控消费方；用户已将其列入删除候选 |
| b | actionlib 接线：_task_action_done_cb（L434 done_cb）、SimpleActionClient（L231）、dry_run 接线 _intercept_task_goal（L432→L444） | **三方法连删 + client 块删 + dry_run 块删** | 宿主 send_task_goal 已判死代码（/mission/task 生成链路）；_task_action_done_cb 无其他调用方；dry_run 的唯一劫持点在 send_task_goal 内 |
| c | 模块级工厂：sync_task_buffers_from_prepare（L106/L1522）保留；start_dispatcher_workers（L1526）零手术 | 见 §4.1 | 工厂调用是 AST self.X 闭包统计不到的活引用 |
| d | 岛状互调五组（_capture_task_generation←capture_task_generation 等，§2 已列） | **随宿主连删** | 复核确认每组私有实现的唯一调用方即公开口本身，公开口删除后零引用 |

### 4.3 B 级断裂清单更新（订正用户预判）

首轮 5 个包内 import 的本轮变化：

| import | 裁决 | 依据 |
|--------|------|------|
| `dispatcher.tools.config`（TASK_ID） | **保留（订正：不可摘）** | 闭包内 4 处存活引用：L109/L327/L653-L660/L814；_is_aggregated_task_id 是 done 相位聚合判定（L839），摘 import 即 NameError |
| `dispatcher.state`（COMMAND_TYPE/COMMAND_STATUS/DISPATCHER_STATE） | 保留 | 闭包内密集引用 |
| `dispatcher.config`（9 符号） | 保留 | __init__/工厂函数引用 |
| `dispatcher.skill_api`（SkillVerdict） | 保留 | _handle_post_action L1195/L1199/L1206/L1209 |
| `dispatcher.slog`（StructuredLogger） | 保留 | __init__ L152，_telemetry 出口 |

结论：**B 级断裂清单零摘除，5 个原样登记**；仅引用点计数变化（tools.config
由 5 处降为 4 处）。

### 4.4 PendingAction 与 vla 壳属性再评估

- **PendingAction：保留**。pending_action 属性被三个闭包内保留方法引用
  （_enter_global_stop L1004 `pending_action.clear()`、
  _recover_inference_after_exception L1458、_handle_post_action L1200-L1201
  REPLAN 清账）；arm_action/_finish_external_task_dispatch 删除后 clear 的
  三个调用点余二，dataclass 与 L126 初始化原样保留。
- **vla 数据壳：全部维持首轮决策 12**（first_rgb L103、bbox/first_bbox
  L142-L143、result/nav_mask L116-L117、first_frame L121、
  _partial_bbox_recenter_attempts L148、thinking_debug_dir/
  last_thinking_debug_dir L189-L190、log_session_tag L174、first_image L101）。
  first_frame 有 base_policy L1770 实读契约；first_image 有闭包内写点
  （L1286/L1289）；其余为 vla 轮次壳契约，非 /mission/task 生成设施。
- **first_image_pub/current_image_pub：删除**（对首轮决策 12 该两项的推翻）。
  复核 base_policy L2821 publish_image(image, pub) 参数化传 pub，不读
  self 属性 → 不构成 base_policy 契约；唯一潜在消费者是未迁的 vla_skill
  传参；保留它们需连带保留 `sensor_msgs.msg.Image` import。vla 轮次恢复
  成本 = `__init__` 两行 + 一行 import。
- **latest_agent_prompt_frame_id（L160）：删除**。读点全在 send_task_goal/
  _start_prompt_task；未来接线轮次写该属性时自会恢复初始化。
  `_active_task_frame_id`（L166）保留（闭包内 L722 读点）。

### 4.5 窄 core 语义声明（本轮不重构、仅删除的边界）

删除 _start_prompt_task / arm_action / _finish_external_task_dispatch /
_task_action_done_cb 后，迁入版引擎的运行语义为：

1. **队列装载**：sync_task_buffers_from_prepare 仍从配置面 prepare_content
   初始化队列（工厂 L1522 必经）；_start_prompt_task 删除后引擎内不再有
   AgentPrompt 注入端口，**队列由外部（rpc/mission 轮次）喂入的预期不变**
   ——外部接线直接操作 prepare_content / if_plan 属性或经未来新入口调用
   _load_next_prompt。本方案不改 FSM 分支语义。
2. **WAIT_FOR_MISSION 语义完整保留**：分支只看 if_plan 与
   action_in_progress（L1332-L1337），不感知注入者身份；初始态 if_plan
   恒 False，FSM 停在 WAIT_FOR_MISSION 等待外部置位，属预期窄 core 行为。
3. **WAIT_ACTION_FINISH 在引擎内不可达**：action_in_progress 的置 True
   路径（arm_action L1068 / _finish_external_task_dispatch L873）已删，
   action_finish 的置 True 路径（_task_action_done_cb L517）已删；完成门
   _action_done 保留且恒安全返回 False（L1115 提前返回，代次检查不可达）。
   动作武装与完成信号由后续接线/技能轮次恢复。
4. **DISPATCH 退化路径**：空注册表下 _handle_plan_tool 走 unregistered
   回退（logwarn + _advance_to_next_prompt），队列被空转排空后
   _load_next_prompt 发 done 相位——与首轮决策 8 的退化语义一致。

## 5. 迁移映射表（方法级去留，行号=当前 1530 行文件）

| 方法 | 当前行号 | 动作 |
|------|----------|------|
| `__init__` | L90-L305 | 保留 + 15 处块删除（§6.2） |
| `sync_task_buffers_from_prepare` | L309-L333 | 保留（工厂调用方存活，§4.1 例外） |
| `publish_monitor_status` | L336-L368（含分区注释 L336） | **删除** |
| `_telemetry` | L371-L373 | 保留（零手术） |
| `publish_command_content` | L375-L380 | 保留（零手术） |
| `send_task_goal` | L382-L442（含分区注释 L382） | **删除** |
| `_intercept_task_goal` | L444-L490 | **删除** |
| `_task_action_done_cb` | L492-L558 | **删除** |
| `publish_mode_burst` | L560-L572（含分区注释 L560） | **删除** |
| `_set_dispatcher_state` | L574-L614 | 保留（零手术，含嵌套 _state_name） |
| `_pause_for_new_agent_prompt` | L616-L632（含分区注释 L616-L617） | **删除** |
| `_has_active_task_to_override` | L634-L645 | **删除** |
| `_is_aggregated_task_id` | L647-L663 | 保留（零手术；TASK_ID 依赖，§4.3） |
| `_fmt_wait_age` | L665-L668 | 保留（零手术） |
| `_decision_chain_wait_diag` | L670-L682 | 保留（零手术） |
| `_decision_chain_not_ready_reason` | L684-L699 | **删除**（迁入版零调用方，原调用方 start_tool_workflow 首轮已删） |
| `_publish_task_phase` | L701-L750 | 保留（零手术） |
| `consume_head_prompt` | L752-L760（含分区注释 L752-L754） | **删除** |
| `advance_prompt` | L762-L764 | **删除** |
| `_start_prompt_task` | L766-L801 | **删除** |
| `_handle_get_pre_command` | L803-L831 | 保留（零手术） |
| `_load_next_prompt` | L833-L851 | 保留（零手术） |
| `_validate_active_tool` | L853-L862 | 保留（零手术；ToolCall 惰性注解，首轮决策 15） |
| `_finish_external_task_dispatch` | L864-L876 | **删除** |
| `_set_if_handle_yaw` | L878-L887 | 保留（零手术；if_handle_yaw_pub 保留） |
| `_handle_plan_tool` | L889-L915 | 保留（零手术；SkillCommand 惰性注解） |
| `_latest_prompt_frame` | L917-L929 | **删除**（迁入版零调用方，原调用方 vla_skill 未迁） |
| `_bump_task_generation` | L932-L940 | 保留（零手术） |
| `_capture_task_generation` | L942-L944 | **删除**（岛状互调，§4.2d） |
| `_task_generation_valid` | L946-L959 | **删除**（岛状互调） |
| `_can_accept_new_action` | L961-L969 | **删除**（岛状互调） |
| `_enter_global_stop` | L971-L1016 | 保留（零手术） |
| SkillHost 分区注释块 | L1019-L1027 | **删除**（宿主端口 4/5 已删，pop_task_result 有自述 docstring） |
| `arm_action` | L1029-L1079 | **删除** |
| `capture_task_generation` | L1081-L1083 | **删除** |
| `task_generation_valid` | L1085-L1087 | **删除** |
| `stash_task_result` | L1089-L1091 | **删除**（无 stash 方则 _task_result_stash 恒 None，pop_task_result 保留并安全返回 None） |
| `pop_task_result` | L1093-L1097 | 保留（闭包内：_load_next_prompt L840） |
| `_action_done` | L1099-L1144 | 保留（零手术） |
| `_advance_to_next_prompt` | L1146-L1164 | 保留（零手术） |
| `_reset_plan_cycle_if_needed` | L1166-L1173 | 保留（零手术） |
| `_handle_post_action` | L1175-L1215 | 保留（零手术） |
| `_run_inference_loop` | L1220-L1442 | 保留（零手术） |
| `_recover_inference_after_exception` | L1444-L1461 | 保留（零手术） |
| `run_inference` | L1463-L1480 | 保留（零手术） |
| `create_dispatcher_engine` | L1483-L1523 | 保留（零手术） |
| `start_dispatcher_workers` | L1526-L1530 | 保留（零手术） |
| 模块级 `PendingAction`（L55-L82） | — | 保留（§4.4） |

统计：删除类方法 20 个；保留类方法 24 个；**全部保留方法零手术**（本轮
无任何方法体改写，区别于首轮的 14 个手术方法）。

## 6. 删除清单

### 6.1 方法级（20 项，理由归并）

| 删除组 | 方法 | 理由 |
|--------|------|------|
| /mission/task 动作通道 | send_task_goal、_intercept_task_goal、_task_action_done_cb、publish_mode_burst、_finish_external_task_dispatch | 用户裁决：/mission/task 生成链路为死代码；五者在迁入版互为唯一调用方或零调用方（§2/§4.2b） |
| SkillHost 端口 | arm_action、capture_task_generation、task_generation_valid、stash_task_result、consume_head_prompt、advance_prompt、_latest_prompt_frame | 首轮 §4.7 以「后续轮次预留」保留，用户本轮裁决推翻；全部零引擎内调用方 |
| 任务生命周期 | _start_prompt_task、_pause_for_new_agent_prompt、_has_active_task_to_override | 同上；岛状互调随宿主（§4.2d） |
| 岛状私有实现 | _capture_task_generation、_task_generation_valid、_can_accept_new_action | 公开口删除后零引用 |
| 监控遥测面 | publish_monitor_status | timer 注册点（L305）随删（§4.2a） |
| 诊断孤儿 | _decision_chain_not_ready_reason | 原调用方首轮已删，迁入版零调用方 |

### 6.2 `__init__` 块级（15 项，降序见 §7）

| 序 | 当前行号 | 删除项 | 连带 |
|----|----------|--------|------|
| I1 | L304-L305 | `## ROS Timer` 注释 + monitor_timer | publish_monitor_status 随 M 段删除 |
| I2 | L294-L302 | finish_command_pub、action_in_progress_pub、if_plan_pub | 唯一消费者 publish_monitor_status |
| I3 | L273-L293 | dry_run 注释 + dry_run_enabled/dry_run_result/warn 块 + dry_run_goal_pub | 唯一消费者 _intercept_task_goal/send_task_goal |
| I4 | L264-L266 | finish_mission_pub | 同 I2 |
| I5 | L252-L260 | monitor_command_type_pub、monitor_dispatcher_state_pub、monitor_command_status_pub | 同 I2 |
| I6 | L243-L249 | `## 图像可视化发布` 注释 + first_image_pub + current_image_pub | §4.4 裁决（非 base_policy 契约） |
| I7 | L228-L238 | `## TaskAction 通道` 注释 + task_action_client 整块 | §4.2b |
| I8 | L223-L226 | `## 运动发布` 注释 + planner_mode_pub | 唯一消费者 publish_mode_burst |
| I9 | L197 | `self._active_tool_call = None` | 零引用 |
| I10 | L160 | `self.latest_agent_prompt_frame_id = "Null"` | 读点全在删除方法（§4.4） |
| I11 | L127 | `self._last_action_time = 0.0` | 唯一写点在删除方法 |
| I12 | L122 | `self.origin_state = None` | 零引用 |
| I13 | L119 | `self.last_published_waypoint = None` | 零引用 |
| I14 | L114 | `self.action_finish_time = 0` | 唯一写点 _task_action_done_cb |
| I15 | L96-L98 | task_generation_guard_enabled 覆盖块（3 行） | 唯一读点 _task_generation_valid |

保留不动：first_image(L101)、first_rgb(L103)、first_frame(L121)、
last_state(L115)、waypoint(L118)、previous_return_record_cursor(L159)、
_active_task_frame_id(L166)、_task_result_stash(L167)、pending_action(L126)、
task_generation(L151)、emergency_stop_pub(L219-L221)、if_handle_yaw_pub
(L239-L241)、command_content_pub(L261-L263)、task_phase_pub(L267-L271)、
_task_phase_progress(L272)、_skills(L208)、zenoh_middleware(L198) 等——
均为闭包内保留方法或 base_policy 契约的活引用（§2 证据）。

### 6.3 import 级（6 项）

| 当前行号 | 删除项 | 依据（符号全部引用点均在删除对象内） |
|----------|--------|--------------------------------------|
| L17 | `import os` | 仅 L275/L281 os.environ（dry_run 块） |
| L25 | `from actionlib import GoalStatus, SimpleActionClient` | L231/L485/L490/L494/L503 |
| L26 | `from sensor_msgs.msg import Image` | 仅 L245/L248（I6） |
| L27 | `from std_msgs.msg import String, Int32, Empty, Bool` → **替换**为 `from std_msgs.msg import String, Empty, Bool` | Int32 引用 L225/L253/L256/L259/L339/L343/L347/L567 全删；String/Empty/Bool 闭包内存活 |
| L28 | `from geometry_msgs.msg import Point` | 仅 L398（send_task_goal） |
| L29-L33 | `from quadrotor_msgs.msg import (Instruction, TaskActionAction, TaskActionGoal)` | L231/L290/L390/L444/L1061 |

B 级 5 个包内 import 与 `dispatcher.perception.base_policy` 原样保留（§4.3）。

## 7. 实施步骤（P0 单期）

> 行为不变式：本轮为**纯删除 + 1 行替换**——除 §7.3 替换片段外不新增任何
> 文本；全部 24 个保留方法与模块级函数逐字节不变。所有删除按当前行号
> **从大到小**执行；每步先 grep 锚点确认再删。相邻删除区间合并后空行归一：
> 类内成员间恰好 1 空行、模块级定义间 2 空行。

### P0 — engine.py 窄 core 二次裁剪

- 范围：仅修改
  `l3-dispatcher-planner/ros_packages/dispatcher/dispatcher/engine.py`。
- 回退：术前快照 `cp .../engine.py /tmp/engine.py.narrow-core-baseline`；
  回滚 `cp /tmp/engine.py.narrow-core-baseline .../engine.py`（或该文件已
  入库时 `git checkout -- <path>`）。

**步骤 0：基线快照与断言**

```bash
cd <new-repo-root>
F=l3-dispatcher-planner/ros_packages/dispatcher/dispatcher/engine.py
cp "$F" /tmp/engine.py.narrow-core-baseline
test "$(grep -c 'def ' "$F")" = "48" || { echo 'BASELINE MISMATCH'; exit 1; }
```

**步骤 1：方法区删除（降序；连续段已合并为一次删除）**

| 序 | 删除区间 | 锚点（删除前 grep 必须唯一命中起始行） |
|----|----------|----------------------------------------|
| D1 | L1019-L1091 | `# SkillHost 窄端口（P3.5 拆解` 起，至 `self._task_result_stash = dict(result)` 止（连续 5 单元：分区注释+arm_action+capture_task_generation+task_generation_valid+stash_task_result）；终态断言：`_enter_global_stop` 尾行 `reason=f"global_stop:{reason}")` 之后空 1 行即 `def pop_task_result` |
| D2 | L942-L969 | `def _capture_task_generation` 起至 `_can_accept_new_action` 的 `return True` 止（连续 3 单元）；终态断言：`## 全局状态控制` 注释(L931)与 `def _enter_global_stop` 之间无其他 def |
| D3 | L752-L801 | `# SkillHost prompt 队列机械端口` 注释起至 `self._load_next_prompt(delay_sec=0.2)` 止（连续 3 单元）；终态断言：`_publish_task_phase` 尾 `)` 之后空行即 `def _handle_get_pre_command` |
| D4 | L684-L699 | `def _decision_chain_not_ready_reason` 至其 `return f"dispatcher_state=...` 行止 |
| D5 | L616-L645 | `# 命令处理流程模块函数` 注释起至 `_has_active_task_to_override` 的 `return False` 止（连续 2 单元+2 注释行）；终态断言：`_set_dispatcher_state` 尾注释块后空行即 `def _is_aggregated_task_id` |
| D6 | L560-L572 | `## 规划模式发布` 注释起至 `rospy.sleep(max(0.0, float(interval)))` 止 |
| D7 | L382-L558 | `## 动作与图像发布` 注释起至 `_task_action_done_cb` 尾 `)` 止（连续 3 单元）；终态断言：`self.command_content_pub.publish(content_msg)` 后空行即 `def _set_dispatcher_state` |
| D8 | L336-L368 | `## 监控状态发布` 注释起至 `self.if_plan_pub.publish(if_plan_msg)` 止；终态断言：`# 发布模块函数`(L335) 之后空行即 `## 指令与任务状态发布` |

**步骤 2：`__init__` 块删除（按下表行号从大到小：I1→I15）**

| 项 | 行号 | 锚点 |
|----|------|------|
| I1 | L304-L305 | `## ROS Timer` |
| I2 | L294-L302 | `monitor/finish_command` |
| I3 | L273-L293 | `Dry-run hijack` 注释行起，至 dry_run_goal_pub 块尾 `)` 止 |
| I4 | L264-L266 | `monitor/finish_mission` |
| I5 | L252-L260 | `monitor/command_type`（起）至 `monitor/command_status` 块尾止 |
| I6 | L243-L249 | `## 图像可视化发布` |
| I7 | L228-L238 | `## TaskAction 通道` |
| I8 | L223-L226 | `## 运动发布`（注意保留其后的 if_handle_yaw_pub 块 L239-L241） |
| I9 | L197 | `self._active_tool_call = None` |
| I10 | L160 | `self.latest_agent_prompt_frame_id = "Null"`（仅此一行；其下 L161-L165 注释块保留） |
| I11 | L127 | `self._last_action_time = 0.0` |
| I12 | L122 | `self.origin_state = None` |
| I13 | L119 | `self.last_published_waypoint = None` |
| I14 | L114 | `self.action_finish_time = 0` |
| I15 | L96-L98 | `task_generation_guard_enabled`（3 行整块：bool( 起至 `)` 止） |

**步骤 3：import 区（行号从大到小）**

1. 删 L29-L33 quadrotor_msgs 块（锚点 `from quadrotor_msgs.msg import`）；
2. 删 L28（锚点 `from geometry_msgs.msg import Point`）；
3. L27 按 §7.3 片段 R 替换；
4. 删 L26（锚点 `from sensor_msgs.msg import Image`）；
5. 删 L25（锚点 `from actionlib import`）；
6. 删 L17（锚点 `^import os$`）。

**§7.3 替换片段 R（全文件唯一允许的新增/改写文本）**

替换 `from std_msgs.msg import String, Int32, Empty, Bool` 为：

```python
from std_msgs.msg import String, Empty, Bool
```

**步骤 4：验收（§8 全绿才算完成；不 commit）**

## 8. 验收标准

- [x] **V1 语法**：

```bash
python3 -m py_compile \
  <new-repo-root>/l3-dispatcher-planner/ros_packages/dispatcher/dispatcher/engine.py
```

- [x] **V2 负向 grep**（活代码零残留；命中行若为注释/docstring 则按白名单
  核对，白名单外零命中）：

```bash
grep -nE '\b(publish_monitor_status|send_task_goal|_intercept_task_goal|_task_action_done_cb|publish_mode_burst|_pause_for_new_agent_prompt|_has_active_task_to_override|_decision_chain_not_ready_reason|consume_head_prompt|advance_prompt|_start_prompt_task|_finish_external_task_dispatch|_latest_prompt_frame|_capture_task_generation|_task_generation_valid|_can_accept_new_action|arm_action|capture_task_generation|task_generation_valid|stash_task_result)\b|\b(monitor_timer|monitor_command_type_pub|monitor_dispatcher_state_pub|monitor_command_status_pub|finish_mission_pub|finish_command_pub|action_in_progress_pub|if_plan_pub|planner_mode_pub|task_action_client|first_image_pub|current_image_pub|dry_run_enabled|dry_run_result|dry_run_goal_pub|latest_agent_prompt_frame_id|_active_tool_call|_last_action_time|last_published_waypoint|origin_state|action_finish_time|task_generation_guard_enabled)\b|\b(SimpleActionClient|GoalStatus|TaskActionAction|TaskActionGoal|TaskActionResult|Instruction|Point|Int32|Image)\b|^import os$' \
  <new-repo-root>/l3-dispatcher-planner/ros_packages/dispatcher/dispatcher/engine.py
```

注释/docstring 白名单（预期仅这 8 处，均位于保留方法的说明文本内，描述
FSM 目标架构与 _active_task_frame_id 语义，不构成代码引用。勘误 3：下方
①-⑧的行号为 1530 行基线行号；裁剪后实际位置为 L145/L146/L357/L472/
L644/L700/L701/L718，复跑时按内容锚定）：
① L162 注释 `in _start_prompt_task;`；② L163 注释
`use it instead of latest_agent_prompt_frame_id`；③ L717 docstring
`显式传 latest_agent_prompt_frame_id`；④ L897 注释 `arm_action 快照为`；
⑤ L1187 docstring `VlaSkill._dispatch_waypoint：arm_action + 立即发 goal`；
⑥⑦ L1243-L1244 docstring `arm_action（通用记账+切态）` 与 `只 arm_action`；
⑧ L1261 docstring `arm_action 已切态`。

- [x] **V3 方法闭包复核**（删后所有 self.X 方法调用可解析、run_inference
  闭包恰为 22 方法；输出 `UNRESOLVED: []` 与 `CLOSURE-OK`）：

```bash
python3 - <<'EOF'
import ast
ENG = "<new-repo-root>/l3-dispatcher-planner/ros_packages/dispatcher/dispatcher/engine.py"
BASE = "<new-repo-root>/l3-dispatcher-planner/ros_packages/dispatcher/dispatcher/perception/base_policy.py"
EXPECT = {"run_inference","_run_inference_loop","_recover_inference_after_exception",
"_enter_global_stop","_reset_plan_cycle_if_needed","_validate_active_tool",
"_handle_plan_tool","_action_done","_handle_post_action","_advance_to_next_prompt",
"_load_next_prompt","_handle_get_pre_command","_publish_task_phase",
"_is_aggregated_task_id","publish_command_content","_set_dispatcher_state",
"_set_if_handle_yaw","_bump_task_generation","_telemetry",
"_decision_chain_wait_diag","_fmt_wait_age","pop_task_result"}
def load(path):
    tree = ast.parse(open(path, encoding="utf-8").read())
    cls = [n for n in tree.body if isinstance(n, ast.ClassDef)][0]
    methods, calls = {}, {}
    for m in cls.body:
        if isinstance(m, ast.FunctionDef):
            methods[m.name] = {
                a.func.attr for a in ast.walk(m)
                if isinstance(a, ast.Call) and isinstance(a.func, ast.Attribute)
                and isinstance(a.func.value, ast.Name) and a.func.value.id == "self"
            }
    return methods
eng = load(ENG); base = load(BASE)
seen, stack = set(), ["run_inference"]
while stack:
    m = stack.pop()
    if m in seen or m not in eng: continue
    seen.add(m); stack.extend(eng[m])
resolved = set(eng) | set(base) | {"clear"}  # clear = PendingAction
unresolved = {c for cs in eng.values() for c in cs} - resolved
print("UNRESOLVED:", sorted(unresolved))
print("CLOSURE-OK" if seen == EXPECT else f"CLOSURE-MISMATCH: {sorted(seen ^ EXPECT)}")
EOF
```

- [x] **V4 def 计数**：`grep -c 'def ' <engine.py>` == **28**
  （24 类方法 + `PendingAction.clear` + `_state_name` +
  `create_dispatcher_engine` + `start_dispatcher_workers`）。

- [x] **V5 `__init__` 属性闭包**（engine+base_policy+CONFIG_KEYS 三源；
  输出 `UNRESOLVED: []`）：

```bash
python3 - <<'EOF'
import ast
ENG = "<new-repo-root>/l3-dispatcher-planner/ros_packages/dispatcher/dispatcher/engine.py"
BASE = "<new-repo-root>/l3-dispatcher-planner/ros_packages/dispatcher/dispatcher/perception/base_policy.py"
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
""".split())
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
es, el, em = scan(ENG); bs, bl, bm = scan(BASE)
unresolved = el - (es | em | bm | bs | CONFIG_KEYS)
print("UNRESOLVED:", sorted(unresolved))
EOF
```

注：CONFIG_KEYS 中 task_generation_guard_enabled 虽保留在键集（config 注入
面），其 __init__ 覆盖块与读点已删，属无害冗余键。

- [x] **V6 纯删除性核对**（除片段 R 外无任何新增行；`NON-DELETE ADDITIONS: 0`
  即通过）：

```bash
python3 - <<'EOF'
import difflib
OLD = open("/tmp/engine.py.narrow-core-baseline", encoding="utf-8").read().splitlines()
NEW = open("<new-repo-root>/l3-dispatcher-planner/ros_packages/dispatcher/dispatcher/engine.py", encoding="utf-8").read().splitlines()
adds = [l for l in difflib.unified_diff(OLD, NEW, lineterm="", n=0)
        if l.startswith("+") and not l.startswith("+++") and l.strip() != "+"]
allowed = {"+from std_msgs.msg import String, Empty, Bool"}
print("NON-DELETE ADDITIONS:", len([a for a in adds if a not in allowed]))
EOF
```

- [x] **V7 已知断裂登记**（静态事实）：B 级 5 个包内 import + base_policy
  2 个 import 维持首轮登记，零变化（§4.3）；运行时验收留待依赖轮次。

## 9. 风险与对策

| 风险 | 影响 | 对策 |
|------|------|------|
| 1. 删除量大（20 方法 + 15 块 + 6 import，约 520 行）误删保留段 | 语法/语义损坏 | §7 降序+锚点双保险；V3 闭包断言 + V4 计数 + V6 纯删除性核对三闸；保留方法零手术（V6 保证逐字节不变） |
| 2. FSM 失去任务注入与动作武装入口：WAIT_FOR_MISSION 恒停、WAIT_ACTION_FINISH 引擎内不可达 | 窄 core 下无端到端任务流 | 预期行为（§4.5 显式声明）；队列由外部 rpc/mission 轮次喂入的预期不变；接线/技能轮次恢复武装与完成信号路径 |
| 3. dry-run 验收路径随 _intercept_task_goal 删除而消失 | 首轮设想的「无 FCU 联调 FSM」验收手段失效 | 迁入版本就无运行时验收（B 级断裂），本轮仍静态验收；dry-run 若需复活由接线轮次整体重设计，不做桩保留 |
| 4. vla 轮次需恢复 first_image_pub/current_image_pub 两行 + Image import | 后续轮次小量返工 | §4.4 论证其非 base_policy 契约（publish_image 参数化）；vla 数据壳全部保留，返工面仅此两行 |
| 5. latest_agent_prompt_frame_id 删除后未来接线直接写该属性会 AttributeError | 接线轮次首跑报错 | §4.5 语义声明 + 本方案登记；接线轮次自会恢复初始化（写点即需求点） |
| 6. 负向 grep 命中保留方法注释/docstring 中的端口名 | 验收误判失败/放行两难 | V2 白名单逐条登记 8 处（§8），白名单外零命中判据 |
| 7. 保留方法 docstring 漂移（_run_inference_loop/_handle_post_action 等描述技能经 arm_action 武装的转移） | 文档与窄 core 暂态不符 | 与首轮 P3-1/P3-3/P3-5 同类处理：保留目标架构描述，接线/技能轮次恢复端口后自动准确；不为本轮改写保留方法文本（V6 纯删除约束优先） |
| 8. tools.config 不可摘的预判订正未同步 | 若执行者按「可摘」预判操作则闭包内 NameError | §4.3 已订正并给 4 处行号证据；V1+V3 双闸兜底 |
| 9. previous_return_record_cursor/waypoint/action_start_time 等成为「恒初值」属性 | 读者困惑 | §4.4/§6.2 保留理由逐项登记（闭包内写/读点存活，删除需手术保留方法，违背零手术不变式） |

回滚路径：§7 步骤 0 快照回拷，或 git checkout（该文件当前若已入库）；
工作区不留任何中间产物（/tmp 快照不入仓库）。

## 10. 修改点清单汇总

| 文件 | 动作 | 说明 |
|------|------|------|
| `l3-dispatcher-planner/ros_packages/dispatcher/dispatcher/engine.py` | 修改（纯删除 + 1 行替换） | 1530 行 → 987 行；删 20 方法 + `__init__` 15 块 + 6 import；保留 24 类方法零手术；def 48→28 |
| `doc/l3-dispatcher-planner/iteration/design-dispatcher-engine-narrow-core-trim.md` | 新增 | 本方案 |

不触碰：`base_policy.py`、两个 `__init__.py`、B 级 5 个 import、任何其他
文件；不 commit。

---

## 附录：执行与评审记录（2026-09-11）

**执行**：code-fixer 按本方案 §7 P0 执行完毕。删除统计：20 个方法
（456 行）+ `__init__` 15 块（78 行）+ import 5 删 1 替换（9 行），含空行
归一 13 行，合计 543 行；engine.py 1530 → 987 行，def 48 → 28。术前快照
`/tmp/engine.py.narrow-core-baseline`（主机本地，不入仓库）。

**验收实测**：V1 py_compile 通过；V2 恰 8 处命中且与白名单按内容一一对应
（裁剪后行号 L145/L146/L357/L472/L644/L700/L701/L718），白名单外零命中；
V3 `UNRESOLVED: []` + `CLOSURE-OK`（闭包恰 22 方法）；V4 def = 28；
V5 `UNRESOLVED: []`；V6 `NON-DELETE ADDITIONS: 0`（唯一新增行为片段 R）。

**评审**：deep-oracle 独立复核（双文件全文逐段对齐、§5×§6.1×§7 三方交叉
映射、V3 脚本静态推演、V2 白名单逐条读、主循环依赖清点），总裁决「放行」，
无阻断问题。三项执行偏差全部核实属实且处置正确：

1. 勘误 1（已回写）：§7 步骤 1 表初版漏列 `_latest_prompt_frame`（L917-929）
   与 `_finish_external_task_dispatch`（L864-876）两个删除区间（§5/§6.1
   已列、步骤表漏项）；执行者按一致性补删（记 D2b/D2c），评审确认无第三处
   漏列、实删清单与 §6.1 恰好 20 项名字一致。
2. 勘误 2（已回写）：§8 V3 脚本类选择器 `[0]` 会选中文件首个类
   （engine 的 PendingAction / base_policy 的 Frame）而非目标类，该缺陷在
   裁剪前基线上即存在；执行者仅在终端按类名锚定运行（BFS/EXPECT 语义
   不变），本文档脚本已同步修正，防止后续轮次照抄得到假阴性。
3. 勘误 3（已回写）：§8 V2 白名单初版行号为基线行号，已标注裁剪后实际
   位置，复跑按内容锚定。

空行归一 13 行属 §7 序言明文授权（只删不增、未触碰方法体），总删除 543
行 > 区间标称 530 行由此而来，非范围扩大。

**未执行**：git add/commit/push（等待用户显式指令）。

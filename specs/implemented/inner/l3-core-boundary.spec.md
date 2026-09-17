# dispatcher core 边界

Status: implemented

Contract-ID: l3-dispatcher/core-boundary
Parent: specs/implemented/l3-dispatcher.spec.md

> 限定 dispatcher 中 core（`engine.py` 及其直接配套）的准入。
> 适用对象：被判定为 core 的模块；技能与共享服务不受本契约约束。

## 1. 职责

core 只做五件事：

1. 接收外部任务入口（RPC / 传输层）并装入任务队列；
2. 运行六态 FSM：`INIT / WAIT_FOR_MISSION / DISPATCH / WAIT_ACTION_FINISH /
   POST_ACTION / STOP`；
3. 按工具名把队首命令分发给已注册技能；
4. 上报任务相位与终态；
5. 全局停止与异常自愈。

## 2. 禁令

> 违反任一条即缺陷。

- **B1 领域无关**：core 不得 import 任何技能模块或领域包（`skills/*`、
  `tools/vla`、`tools/flight`、`tools/scene_nav`等）。
- **B2 无任务编号**：l3 中不存在任务编号这一概念。core 不得定义、映射或
  按任务编号做分支；直接依据 rpc-json 解析出的任务名进行分配与处理。
  引入编号作为中间表示属无谓开销与概念污染。
- **B3 无领域端点**：core 的对外通道是**语义白名单**，固定为四类——急停、
  `if_handle_yaw`、任务相位、命令内容监控。该白名单**不豁免**
  `l3-dispatcher/ros-adapter-boundary` R1/R2/R4：四类通道的 ROS 实现必须落在
  适配文件，core 只持有端口引用。其余主题由技能或适配层自建。
- **B4 状态数固定**：`DISPATCHER_STATE` 成员数固定为 6；新增状态须先改本契约。
- **B5 无隐式成功**：分发未命中已注册技能时，必须上报失败相位并停在
  `WAIT_FOR_MISSION`；禁止排空队列后上报完成。
- **B6 不替技能决策**：动作完成判定与后续走向由技能的完成门与裁决钩子决定；
  core 只机械执行四裁决（`REPLAN / ADVANCE / IDLE / NEW_ACTION`）。
- **B7 编号零残留**：l3 任何模块都不得定义、传递或存储任务编号，也不得
  自产（含由工具名、能力名或配置派生编号后注入内部载荷）。若上游调用
  协议仍携带该字段，由适配层在入口处丢弃，不得进入领域层；wire 未携带
  该字段时，适配层亦不得补造。
- **B8 无中间映射**：任务识别到能力归属之间不得插入任何编号或枚举映射层；
  rpc-json 的解析结果直接作为分发依据。

## 3. 运行状态的可观测性

> core 的退化与等待必须可被外部判读，不得静默。

- **O1 等待点名**：任何等待循环必须周期性输出等待原因与输入通道年龄，
  区分"从未收到"与"收到但已过期"。
- **O2 状态迁移留痕**：状态迁移必须记录来源状态、目标状态与原因。
- **O3 未注册可诊断**：分发未命中时上报的信息必须包含未命中的工具名，
  使缺失的技能可被直接定位。

## 4. 门禁

> 与禁令和可观测性要求一一对应，可脚本化。

| 门禁 | 检查 |
|------|------|
| G1 | AST 检查 core 的 import 闭包不含任何技能 / 领域模块（B1） |
| G2 | `DISPATCHER_STATE` 成员数 == 6，且 core 的 `def` 集合 ⊆ 本契约 §4.1 白名单（B4） |
| G3 | 分发未命中路径存在 fail 相位上报且无 done 上报（B5） |
| G4 | core 的发布器集合是 B3 四类白名单的子集（B3） |
| G5 | l3 的 core 与领域层零命中任务编号标识符；若上游协议仍含该字段，只允许出现在适配层的丢弃逻辑（B2、B7、B8） |
| G6 | 每个等待循环存在周期性诊断输出且区分"从未收到"与"已过期"（O1） |

### 4.1 core 方法白名单（G2 判定基准）

> `def` 集合的作用域 = `engine.py` 与其协作模块 `core/**`；核心判据是
> 「集合包含」而非「数量」。白名单随契约修订维护：新增方法须先改本节。

| 模块 | 允许的 `def`（方法名） |
|------|------------------------|
| `engine.py` | `__init__`、`_enter_global_stop`、`_run_inference_loop`、`_recover_inference_after_exception`、`run_inference`、`_fail_unregistered_dispatch`、`_sleep_unlocked` |
| `core/telemetry.py`（`RunTelemetry`） | `__init__`、`emit`、`publish_command_content`、`fmt_wait_age`、`wait_diag` |
| `core/task_phase.py`（`TaskPhaseBridge`） | `__init__`、`publish`、`set_active_frame`、`set_middleware` |
| `core/skill_router.py`（`SkillRouter`） | `__init__`、`register`、`get`、`dispatch_plan`、`validate_active_tool`、`owner_skill`、`snapshot_owner`、`stash_task_result`、`pop_task_result`、`dispose` |
| `core/actuators.py`（`PlannerActuators`） | `__init__`、`set_if_handle_yaw` |
| `core/tool_workflow.py`（`ToolWorkflowHost`） | `__init__`、`bind_tool_middleware`、`_activate_tool_call`、`start_tool_workflow`、`cancel_tool_call` |
| `core/prompt_queue.py`（`PromptQueue`） | `__init__`、`sync_task_buffers_from_prepare`、`pop_next_task`、`load_next_prompt`、`advance_head_prompt`、`reset_plan_cycle_if_needed`、`clear_all`、`head_command`、`is_command_empty`、`is_prepared_empty` |
| `core/state_ledger.py`（`StateLedger`） | `__init__`、`set_state`、`_state_name`、`bump_task_generation`、`fail_sequence`、`reset_running` |
| `core/action_gate.py`（`ActionGate`） | `__init__`、`action_done`、`handle_post_action`、`clear_action_state`；`PendingAction.clear` |
| `core/ports.py`（端口 Protocol） | `CoreChannels`：`publish_emergency_stop`、`publish_if_handle_yaw`、`publish_command_content`、`publish_task_phase`；`Ticker`：`sleep`；`RuntimeClock`：`rate`、`is_shutdown`、`request_shutdown`；`LogSink`：`info`、`warn`、`err`、`warn_throttle`（本表为端口名的权威定义） |

- 类标注以外的 `def` 节点：模块级装配函数（`create_dispatcher_engine` /
  `start_dispatcher_workers`）随装配职责落 `dispatcher_node.py`，**不计入 core**；
  嵌套 `def` 只允许 `StateLedger.set_state._state_name`（状态名反查）及
  `SkillRouter.register.dispose`（注册资源的逆操作，不持有领域判断）。

## 5. 迁移判定

> 旧库文件能否进 core 的判定顺序；顺序在上者优先。
> 完整裁决顺序见 `l3-dispatcher/migration-protocol` §2。

1. 属于 FSM 骨架、任务队列、相位上报、急停之一 → 进 core；
2. 只在某一工具的流程中被调用 → 进对应技能；
3. 跨多个工具共享的感知或几何能力 → 进共享服务；
4. 无任何调用方 → 不迁移（遵循"过期必删"，不留桩、不留注释）。

任务准入/取消、全局停止与单次 FSM 处理共享可重入生命周期锁；等待时必须释放锁，
避免阻塞新调用。`_sleep_unlocked` 只管理等待期间的锁释放/恢复，不承担领域决策。

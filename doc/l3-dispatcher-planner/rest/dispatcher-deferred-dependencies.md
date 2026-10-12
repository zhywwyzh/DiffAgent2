# dispatcher 待迁依赖与保留项台账

更新日期：2026-10-10。当前 R03/R05 已迁移到原生 action 执行，代码交付但未编译、未验收，详见文末“原生 action 接入”。此前直连 topic 与家族执行器条目保留为迁移历史，不能作为现行接口说明。R01/R02/R04/R06 等无关保留项继续挂账。

用户本轮明确要求清除未接入目标能力的预留，覆盖此前附加目标字段的保留决定。
消息、领域目标、适配赋值及三后端拒绝分支已同步删除；无消费者的感知开关也已删除。
实现归属及接口影响见[清理方案](../iteration/design-remove-unused-follow-reservation.md)。本轮未运行测试、门禁、构建或验收；现有停止链的运行证据仍须在用户许可后补齐，删除预留不关闭 R03/R05。

本文件记录已批准的暂时保留及后续处理线索，不定义新契约。用户明确要求：保留项在未来接入或优化时重新判断，不能因为当前生产技能为空而直接删除。未来实现方案仍按 `iteration/_TEMPLATE.md` 落盘；如需改变端口或行为契约，先更新 `specs/`。

去除 task-id 后的任务身份与旧业务判据另见用户指定位置的
[工具名与业务语义迁移遗留项](../../rest/task-id-to-tool-name-deferred.md)：任务继续使用
`navigation.vla_nav` 等原始 tool 名识别；panorama 等原来源限制不能因删除编号而丢失，
对应语义须上行到 dispatcher 的技能/策略中。当前仅记录该缺口，不表示已恢复等价策略。

## 取证与使用方式

| 标记 | 含义 |
|----|----|
| `N/` | 相对 `l3-dispatcher-planner/ros_packages/dispatcher/dispatcher/` |
| 定位方式 | 优先按符号搜索，再参考行号；以符号为准，避免未来编辑造成锚点失效 |
| 维护要求 | 对应能力开始设计时即读本条目，不要等写完代码才补查；本轮未改造的缺口不算已交付能力 |

### 为什么有些开关只有参数，没有完整功能

早期[核心迁移方案](../iteration/20260915-20260917/design-dispatcher-core-inference-migration.md)将 recording、悬停辅助方法和技能实现排除在 core-only 迁移范围之外；[结构稳定化方案](../iteration/design-dispatcher-architecture-stabilization.md)把相关能力登记为后续轮次。新版提交 `7fc6827` 中已经存在“保留 record_stop_event 参数、没有记录调用”的状态，不是本轮清理才删掉逻辑。

随后用户允许删除所有未迁入生产工具链；当前的保留状态是这次审核明确决定留下的迁移线索。它们没有使空生产注册面自动恢复。

<a id="r01"></a>
## R01 — 停止事件记录开关与任务覆盖语义

| 项 | 内容 |
|----|----|
| 对应审核 | B01、D01；本轮保留 `record_stop_event` |
| 新版位置与现状 | `N/engine.py::DispatcherEngine._enter_global_stop`。参数仍在，但函数体不读取它，**当前不产生停止记录**；不能把传 True 理解为已经落盘。 |
| 何时重新参考 | 开始迁入 RecordingService、停止/完成过程记录、任务覆盖或仿真重置流程时；或准备删除此参数时。 |
| 接入位置与顺序 | 先明确记录服务的独立归属和注入接口；再在跨域停止入口按开关调用服务；最后检查覆盖、取消、硬停、软停、重置每个调用点是否应记停止事件。保持 core 无具体技能 import。 |
| 仍未处理 | 新版没有记录服务实例；新任务覆盖暂只传 `shutdown_program=False, publish_hold=False`。接入记录功能时必须同时复查，否则默认 True 会开始产生此前没有的记录。 |
| 必须验证 | 每类停止记录的产生/不产生与次数；记录关联原调用而非新覆盖调用；重复停止不产生重复终态；记录服务失败不妨碍队列和动作安全清理。 |
| 何时可删除 | 明确放弃停止记录，或新服务已提供等价且验证过的生命周期策略、不再需要此开关时，连同参数和调用点一起删除；不能只因当前没有消费者删除。 |

<a id="r02"></a>
## R02 — 软停日志开关与结构化停止事件

| 项 | 内容 |
|----|----|
| 对应审核 | B02、D01/D02；本轮保留 `emit_soft_stop_log` |
| 新版位置与现状 | `N/engine.py::_enter_global_stop` 中 `if emit_soft_stop_log` **仍有效**，控制软停的 `runlog.warn`；它不控制急停发布或任务清理。 |
| 何时重新参考 | 接入统一运行日志/结构化事件、重置服务、覆盖或取消流程，或重整停止日志策略时。 |
| 接入建议 | 区分普通文本日志、结构化停止事件、R01 的持久化记录，分别决定哪些场景应抑制。先确定事件字段与消费者，再恢复结构化上报，不要让同一停止被多个层重复记录。 |
| 仍未处理 | 结构化事件与文本警告不完全等价；部分传 False 的调用方尚未接入。不是“整个条件分支没迁”，也不是“所有调用都需要日志”。 |
| 必须验证 | 软停 True/False 各自输出；硬停不受该开关影响；关闭日志仍完成清理；任务覆盖不制造错误的操作员急停记录。 |
| 何时可删除 | 新日志策略确认无需调用方选择、且所有原传 False 场景已得到等价处理时，再删开关；不得与 R01 的开关混为一项。 |

<a id="r03"></a>
## R03 — 急停悬停与执行侧停止路径

| 项 | 内容 |
|----|----|
| 对应审核 | B03、D01/D02；保留 `publish_hold`，本轮注明“急停悬停” |
| 新版位置与现状 | `N/engine.py::_enter_global_stop` 在 True 时只调用 `channels.publish_emergency_stop()`；`N/ros_adapter/core_channels_ros.py::RosCoreChannels` 默认发布 `/command/emergency_stop` 的 Empty。**不额外构造悬停 goal**；全局信号保持原语义；当前取消/保持意图由 WaypointExecution 经既有目标口编排，不再依赖新增 EGO 取消回调，修正版未复验。 |
| 何时重新参考 | 接入飞行 skill、航点执行端口、下行执行缝、planner/飞控桥、租约丢失安全停或修改急停语义时，必须在端到端接线前读取。 |
| 本轮方案判断 | 保持“急停后悬停”的目标，不改成停桨、返航或自动降落。当前缺少速度、可用定位和控制模式等实机证据，不能判定另一种方案普遍更好。应由执行侧以可实现的制动轨迹进入悬停，core 只触发安全停止，不在 core 增加飞行动作算法。 |
| 已有下游线索 | 新版 `ros_packages/planner/ego_planner/plan_manage/src/ego_replan_fsm.cpp` 的 `mandatoryStopCallback`（约 1285 行）进入 EMERGENCY_STOP，相关分支调用 `callEmergencyStop(odom_pos_)`（约 361 行）；订阅名是 `mandatory_stop`（约 89 行）。bringup/launch/ego.launch 保留既有急停信号映射；新增取消回调和后端停止修改已撤回，当前修正版未重跑 cmd 验证。 |
| 接入/优化步骤 | 先验证急停主题到所用 planner 的链路、停止轨迹的生成与跟踪、制动后保持和恢复条件；再决定是否还需要额外 hover goal。若已有停止链可靠完成悬停，避免同时发送相互覆盖的两类目标；若仍需 hover goal，将其放在执行缝/适配端口，按现行契约实现。 |
| 必须验证 | 运动中触发后速度收敛与位置保持、旧 goal 不再继续、重复触发、定位不可用、模式切换和重启时停止语义；取消/覆盖 False 不发布急停；硬停请求发出不等于实机已悬停。 |
| 何时可删除或改名 | 只有最终安全停止链已选定、无需独立 hover goal 的结论有运行证据时，才重新评审 publish_hold 的名称或拆分；若删除 hover 路径，需记录替代路径和验证结果。当前不做仅按 Empty 发布行为的机械改名。 |

<a id="r04"></a>
## R04 — 返航快照、历史游标与任务文本回退

| 项 | 内容 |
|----|----|
| 对应审核 | B08、B10、B11 |
| 新版保留位置 | `N/core/state_ledger.py::StateLedger.last_state`；`N/core/prompt_queue.py::PromptQueue.replan_content`、`previous_return_record_cursor`，以及 `frame_state_get`、`last_state_set` 写入回调。 |
| 当前有效部分 | `pop_next_task` 复制当前 frame.current_state 写入 ledger.last_state，并把准备队首存入 replan_content 再放入 command_content；全局停止会清 replan_content 和游标。last_state 是位置状态快照，不是 FSM 上一状态。 |
| 何时重新参考 | 接入 `flight.return`、返回上一位置/原点、过程轨迹记录、导航历史恢复，或把队列数据迁往服务时。 |
| 接入建议 | 先实现历史记录和目标解析服务，再让飞行技能通过服务解析返航目标；从现有快照/队首接口传入所需数据。位置快照实际在 `host.ledger.last_state`；不能靠给 engine 增加同名属性桥接，也不能让技能绕过端口到处读内部对象。 |
| 仍未处理 | ReturnSkill 已通过 FlightSession 消费确认的起飞原点，不使用 last_state 冒充原点；历史集合/逐步回退尚未实现，游标仍不前移。快照字段继续保留待其真实消费者接入。 |
| 必须验证 | 连续两次返回上一位置确实逐步后退；无记录/无原点时的回退或明确失败；快照不是随帧原地更新的别名；重置、覆盖与新会话不读取过时位置；任务文本回退仍对应本次调用。 |
| 何时可删除 | 历史服务已独立拥有位置与游标，或产品明确取消逐步返航且调用方已清理时，删除这些字段及快照回调。replan_content 只有在记录服务不再使用该文本回退并有替代后才能改为纯局部变量。 |

<a id="r05"></a>
## R05 — 动作上下文、武装接口与 VLA 重规划

| 项 | 内容 |
|----|----|
| 对应审核 | C01–C03 |
| 新版保留位置 | `N/core/action_gate.py::PendingAction`、`ActionGate.pending_action`；`handle_post_action` 的 REPLAN 标记清理和 `clear_action_state` 的全量清理。 |
| 当前状态 | DispatcherFlightHost.start_goal 已接入飞行动作武装、实例归属、代次和当前批次反馈；取消/停止控制已改为 dispatcher 的目标覆盖方式，本次未复验。**VLA 专属重规划已退役（2026-09-20，[机上收窄方案](../iteration/design-dispatcher-vla-waypoint-executor-migration.md)）**：station 解算 `waypoint_world` 后机上为一次调用（单次消费、无 replan/无重试）；2026-10-09 起内部依次执行位置、可选终末偏航与贴地腿，最后一腿才收敛终态，技能自有 replan 状态与 `far_push`/`depth_match_ok` 一并删除；`PendingAction.replan_cmd` 与 `SkillVerdict.REPLAN` 保留为通用账务/裁决机制（技能契约 §4）。契约见 [技能契约 §10](../../../specs/implemented/inner/l3-skill-contract.spec.md)；归档见 [2026-09-20 决策](../../../specs/implemented/architecture/2026-09-20-vla-waypoint-executor.md)。 |
| 执行实现归属（2026-09-21） | 航点下发执行（批次/反馈/超时/取消保持）已按使用者下沉到 `N/tools/flight/flight_waypoint.py`（`FlightWaypointExecution`）与 `N/tools/vla/vla_waypoint.py`（`VlaWaypointExecution`）各一份（逐字等价），`N/execution/waypoint.py` 已删除；`execution/` 平面收缩为共享动作端口（ports）+ 家族宿主（skill_host）+ 装配（composition），行为零变化。方案见[航点下发执行按家族归属方案](../iteration/design-dispatcher-waypoint-execution-family-ownership.md)；归档见 [2026-09-21 决策](../../../specs/implemented/architecture/2026-09-21-waypoint-execution-family-ownership.md)。 |
| 记录消费现状 | VLA 航点发布时的过程记录消费（`host.recording._record_process_event`，远推进腿不记）**暂不迁、继续挂账**：记录服务未建（R01/R06）；状态可见性先由 `publish_phase` 覆盖。 |
| 字段级区分 | replan_cmd、prompt_raw、action_name、instruction_type 是明确的读点；replan_reason 见写入/清理；waypoint、look_forward、nav_yaw、yaw_source、is_far_push 在该上下文快照中未确认完整消费者，不能把 skill 中其他同名概念当成此对象读点。整类保留不等于每个字段永久保留。 |
| 何时重新参考 | 实现 SkillHost.arm_action 通用化、飞行/场景技能动作发布，或调整动作元数据模型时仍须读本条。 |
| 已接入（2026-09-17） | `navigation.vla_nav` 已按 [VLA 迁移方案](../iteration/design-dispatcher-vla-migration.md) P1–P3 落地：REPLAN 判据为技能自有 `_replan_cmd/_replan_reason`（`N/tools/vla/vla_skill.py::on_action_result` 四裁决），与 arm_action 记账同源写入，取消/覆盖/全局停止路径清理；重新武装后旧代次结果被完成门拒绝（tests/core-boundary/test_vla_skill.py 代次门与引擎节拍端到端用例）。剩余挂账：记录消费（下行）。 |
| 接入顺序 | 通用动作账务与技能内部语义的区分已裁决：VLA 的 REPLAN 判据走**技能自有 replan 状态**（迁移方案 §4），不读宿主 `ActionGate.pending_action`，不造显式读取端口或旧入口转接器；契约依据为 [技能契约 §10](../../../specs/implemented/inner/l3-skill-contract.spec.md)。动作武装、实例归属、代次、结果与清理继续经端口接入；记录消费待记录服务（R01/R06）后另行接入。 |
| 必须验证 | VLA 任一失败腿不得继续，位置/偏航/贴地腿全部成功才 done；批次结束后原目标及动态停稳门有效；重新武装后旧结果被代次拒绝；停止/覆盖后标记清理；动作归属不随名字重新注册漂移；对外调用终态唯一。 |
| 何时可删除 | 技能自有会话/通用动作记录已覆盖所有真实读点，并验证重规划、记录与发送文本后，逐字段裁剪或整体替换。保留清理生命周期，不能只搬数据而丢掉停止时的逆操作。 |

<a id="r06"></a>
## R06 — 运行会话标签与记录服务

| 项 | 内容 |
|----|----|
| 对应审核 | B14 |
| 新版保留位置 | `N/core/telemetry.py::RunTelemetry.log_session_tag`；engine.runlog 持有该对象。trace 当前确实使用同次构造生成的 session_tag。 |
| 何时重新参考 | 迁入 RecordingService、日志快照/上行、重连补发，或设计跨进程会话关联时。 |
| 接入建议 | 从遥测对象显式传入会话标签或记录配置；不要在记录服务另造一个会话标签，也不要给 engine 加转接属性。严格日志要求见 [日志契约](../../../specs/implemented/inner/observability-log.spec.md)，接入时按其明确字段含义。 |
| 仍未处理 | 上行记录与快照服务尚未建立；当前标签格式的唯一性需求未做新的保证，不能等同 call_id。 |
| 必须验证 | 同次运行 trace 与记录服务使用相同会话标签；重启/并行实例是否满足实际关联要求；快照和补发记录不跨会话误归属。 |
| 何时可删除 | 新会话服务成为唯一来源、所有记录消费者已切换，或明确只保留 trace 且不需要向其他服务传出标签时，才删除重复属性。 |

<a id="r07"></a>
## R07 — VLA 多图思考调试目录

| 项 | 内容 |
|----|----|
| 对应审核 | B15 |
| 新版保留位置 | 无（已删除）。原 `N/core/telemetry.py::RunTelemetry.thinking_debug_dir`、`last_thinking_debug_dir` 及目录创建逻辑已随 VLA 迁移方案 P1 移除。 |
| 当前状态 | **已关门（2026-09-17，方案 P1）**：`RunTelemetry.thinking_debug_dir` 字段与目录创建逻辑属「仅创建、无消费者」的孤儿字段。按 [dispatcher VLA 技能迁移方案](../iteration/design-dispatcher-vla-migration.md) §6/§7 P1 删除孤儿字段，本条目关门。普通 trace 独立工作，不受影响。 |
| 何时重新参考 | 已关门，无常规触发条件。若未来需要多图推理调试落盘，按新需求重新设计归属，不恢复旧字段名。 |
| 归属裁决 | 不迁入技能、不建共享调试服务：双侧零消费者的孤儿字段按过期必删处理；删除范围仅 `N/core/telemetry.py` 的 `thinking_debug_dir`/`last_thinking_debug_dir` 字段、创建逻辑与开启日志，不动日志根目录与 trace。 |
| 必须验证 | 删除前全库 grep（生产/测试）`thinking_debug_dir` 零命中；删除后 trace 行为不变；不影响任务终态与运行日志根目录。 |
| 何时可删除 | 已执行：P1 删除后留本记录关门（证据见下）。 |

R07 关门证据（2026-09-17，方案 P1）：

- 删前 grep：`l3-dispatcher-planner/` 代码树（生产 + tests）内 `thinking_debug_dir` 仅 `core/telemetry.py` L69-L73 自身定义命中（零消费者）；`specs/` 0 命中；`doc/` 命中均为台账/方案记录文字。
- 删后 grep：`l3-dispatcher-planner/` 全树 `thinking_debug_dir` **0 命中**。
- 行为核验：trace（`attach_trace`/session_tag）与 `dispatcher_started` 事件不受影响（删除块位于二者之后）；core-boundary 既有测试回归通过（30 项中 29 通过，唯一失败为环境缺 zenoh 的收集错误，与本次改动前的基线一致）。

<a id="r08"></a>
## R08 — GRASP 抓取感知（已删除登记项，不自动恢复）

| 项 | 内容 |
|----|----|
| 状态 | **已删除，不自动恢复**。由 [grasp 退役登记方案](../iteration/20260915-20260917/design-dispatcher-grasp-retirement.md) 裁定为不迁移并登记。 |
| 新版已删除面 | `N/iteration/design-dispatcher-unmigrated-chain-removal.md:108`：资源主题 `grasp_result/*`、ROS 反馈 `/agent/grasp_result_image`、grasp 线程均已删除；`N/tests/tool-registry/test_methods.py:21-29` 空发现面锚定 22 个已删除名一律 `method_not_found`；新版 l3 代码与 specs 全树 grep “grasp” 0 命中。 |
| 何时重新参考 | 仅当出现**真实站端消费者**需求（如站端在飞行动作词汇上明确要求 GRASP 抓取感知结果）时，先读本条目与 [grasp 退役登记方案](../iteration/20260915-20260917/design-dispatcher-grasp-retirement.md)。不存在“顺手恢复”场景。 |
| 接入条件（技能化） | 先按 `l3-skill-contract.spec.md` 出契约（身份三声明、生命周期钩子、四裁决、语义端口）；实现与测试**同批**交付并通过 `N/tests/core-boundary/`、`N/tests/tool-registry/`；技能进入发现面时同步更新 `l3-tool-plane.spec.md` 的集合与 `revision`。感知入口（如 vla 私有的 `_serve_search`）与几何能力（`GeometryService`）若复用须重新设计归属，不原样搬运、不造转接器、不引入任务编号。 |
| 必须验证 | 技能完成门/裁决与实例归属；感知结果与图像按现行端口契约出站；发现面 revision 与 spec 一致；站端读模型有真实消费者且非恒 404 的占位路由。 |
| 何时可删除 | 本条目唯一存在价值是留证与触发条件登记：若产品明确永久放弃 GRASP 感知、且上述接入条件不再需要被任何未来任务触发，可删除本条目与 [grasp 退役登记方案](../iteration/20260915-20260917/design-dispatcher-grasp-retirement.md)；删除前须在「后续关闭条目的记录格式」表中留一行处理记录。 |

<a id="r09"></a>
## R09 — 对象导航下行与在线建图链（不迁，登记）

| 项 | 内容 |
|----|----|
| 对应裁决 | [场景图迁移方案](../iteration/design-dispatcher-scenegraph-migration.md) §4.1 裁决 6/8/9 |
| 当前状态 | **不迁，登记**。旧库对象导航执行体在 `mission_executive`（`src/handlers/mission_core_object_nav.cpp`、`mission_executive/handlers/object_nav.py`），受 `l3-execution-seam` §1 与门禁 G10 禁止迁入；其 object 级语义（到达判据=位置+终端偏航、任务级 deadline 与重规划上限、终态原因 `reached`/`unreachable`/`timeout`/`failed`）按 [技能契约 §11](../../../specs/implemented/inner/l3-skill-contract.spec.md) 重新实现到 `scene.navigate` 技能，**不搬运代码**。在线建图链（`expandSkeleton` 全套、`initSceneGraph`/`updateSceneGraph`、`cloud_fov_limit`）因旧库已失去地图接口依赖（`rayCast` 只剩 facet 碰撞、`searchPathInRawMap` 为 stub、`find_package(catkin)` 无 `map_interface` 组件）而不可用，不迁。对象导航终态语义已按旧库 2026-09-24 裁决同步到 `l3-scenegraph` §5 与 [技能契约 §11](../../../specs/implemented/inner/l3-skill-contract.spec.md)（终点=所挂拓扑节点、aim 偏航=节点→对象 bearing，2026-09-26）。 |
| 新版位置与现状 | 目标契约已先行：[场景图能力契约](../../../specs/proposed/inner/l3-scenegraph.spec.md)（`proposed`）+ [技能契约 §11](../../../specs/implemented/inner/l3-skill-contract.spec.md) + [工具面 §1 目标集合](../../../specs/implemented/inner/l3-tool-plane.spec.md)。代码尚未迁入：`ros_packages/` 无 `scene_graph` 包，`dispatcher/tools/` 无 `scene_nav` 家族，`dispatcher/perception/` 为空。 |
| 何时重新参考 | ① 实施 `scene.navigate` 的 object 级状态机时；② 需要恢复机上在线建图时；③ 讨论把 object 语义移回 planner 侧（方案 §4.4 备选 C）时；④ 需要新增 `Instruction` 类下行消息时。 |
| 接入条件 | ① `l3-dispatcher/scenegraph` 与 `l3-dispatcher/skill-contract` §11 就位（已满足）；② `scene.navigate` 的完成语义 `workflow_result` 与结果字段已在工具面登记（已满足）；③ 在线建图若恢复，须先接回地图接口依赖并另立契约，**不得在 executor 侧复活建图入口**；④ 若走备选 C（object 语义归 planner），须 planner 契约先行，属 `l3-migration-protocol` §2-⑤ 运动规划范围，不在本条目内放行。 |
| 必须验证 | 到达判据（位置 + 终端偏航）与失败原因在真实链路可判读；无图/无对象/无通路/无法挂载时 fail-closed 且不静默成功；取消与覆盖后旧动作结果失效；终态唯一。 |
| 何时可删除 | 本条目唯一存在价值是留证与触发条件登记。`scene.navigate` 按方案 P2/P3 落地并验收后，把「当前状态」的 ① 部分改为「已接入」并保留在线建图部分；若产品明确永久放弃机上在线建图且其归属另有定论，删除 ② 部分。删除前须在「后续关闭条目的记录格式」表中留一行处理记录。 |

## 当前队列如何执行（回应 B10）

| 阶段 | 调用与数据变化 | 保留的历史依赖 |
|----|----|----|
| 接受调用 | `ToolWorkflowHost.start_tool_workflow` 检查技能与输入，激活调用并通知技能；同步技能不入队 | 当前注册六个 basic_flight 技能；通用链及真实 EGO cmd 均有测试 |
| 同步任务 | 异步调用将 `(prompt_text, SkillCommand)` 列表传给 `PromptQueue.sync_task_buffers_from_prepare`；构造独立 prepare_content 列表 | 删除了纯文本副本，未删除 prompt 本身或原始 ToolCall |
| 装载队首 | `pop_next_task` 推进任务代次、复制 frame.current_state 到 ledger.last_state；pop 准备队首，存入 replan_content，再加入 command_content，置 if_plan=True | R04 的位置快照和文本回退仍写入 |
| 分发 | FSM 从 WAIT_FOR_MISSION 进 DISPATCH，按 skill_command.call.name 查注册表；`dispatch_plan(skill_command)` 调用技能 plan_tick | 无任务编号或中间名字映射；cmd 文本仍用于监控与日志 |
| 动作完成 | WAIT_ACTION_FINISH 经技能完成门/代次判定后进 POST_ACTION；ActionGate 执行四裁决 | R05 保留重规划标记清理 |
| 下一步 | REPLAN 围绕当前命令继续；ADVANCE 调 load_next_prompt 装下一条，队空时 done；IDLE 收敛完成；NEW_ACTION 不替技能再次调度 | 同一调用的内部序列不能被当作多次独立外部调用 |
| 失败/停止 | 未注册只报 fail 并回空闲，不用排空冒充完成；全局停止/恢复清执行副本与动作状态 | 不修改配置来源列表；返航历史与会话重置策略见 R04 |

例如准备队列中有两条同一次调用的内部命令，第一次 pop 后第一条进入执行队列、第二条留在准备队列；收到 ADVANCE 才装载第二条；后续 ADVANCE 发现准备队空才收敛完成。名称相同不代表动作归属可以重查，完成门仍绑定发布动作的技能实例。

## 本轮明确删除，不自动恢复的内容

| 内容 | 处置与未来边界 |
|----|----|
| first_image、感知中的 first_frame/first_waypoint/first_depth 残留 | 用户明确暂不保留 first 系列首帧功能；后续 VLA 迁移不得因为曾有 first_rgb/首帧发布器就默认恢复。若新方案确需首帧对比，重新明确需求和归属。点云去重的局部 first_indices 不是首帧缓存功能，保持不动。 |
| last_plan_time | 核对未发现实际读取；删除无效计时缓存。若以后需要耗时测量，应设计真实的时间来源及消费者。 |
| ActionGate 四个未调用回调、PromptQueue 两个未调用 getter | 只删多余接线，不删实际宿主状态/帧/航点及 R04 的快照写入；未来技能需要读数据时按端口重新设计。 |
| pre_prompt、prompt_bf、content | 删除文本副本；保留结构化队列、prompt 与 replan_content，避免误伤记录服务待接入依赖。 |
| dispatch_plan 的 cmd 入参 | 调用只传 SkillCommand；不删原始调用名或日志文本。 |

## 后续关闭条目的记录格式

| 日期 | 条目 | 状态 | 接入/替代/删除实现位置 | 验收证据 | 尚需参考的触发条件 |
|----|----|----|----|----|----|
| 2026-09-16 | R01–R07 | 保留待接入 | 见各项新版位置，本轮不迁生产技能 | 本轮验证保留状态未被清理，不能替代未来生产能力验收 | 按各项“何时重新参考”触发 |
| 2026-09-16 | R03、R05 与 l4 对接前置 | 继续保留；设计中 | [RPC 对接方案](../iteration/20260915-20260917/design-dispatcher-l4-rpc-integration.md)、[基础飞行方案](../iteration/20260915-20260917/design-dispatcher-basic-flight-migration.md) | 只读检查发现 owner watch 未接 acquire；复现快速终态丢失、非法 JSON 顶层无回复和失效租约重放获准。未改生产代码，未完成物理停止验证 | 前置轮次先修协议与监听；飞行轮次接完整执行缝、动作账务与急停轨迹；VLA 专属重规划仍待其技能迁移 |
| 2026-09-16 | R04、R06 原点/历史边界 | 继续保留；仅原点子能力已出方案 | [基础飞行方案 §4.5](../iteration/20260915-20260917/design-dispatcher-basic-flight-migration.md#45-原点服务与-r04-范围) | 当前只读 l4 的 plan_tools.json 定义 return 空参返回起飞点；FlightSession 仅为设计，尚无实现/运行证据 | 起飞原点随基础飞行接入；previous、历史集合、游标和文本回退待真实消费者接入，不因本轮无公开入口裁掉；日志 session_tag 不等于飞行会话 |
| 2026-09-17 | R05、R07 | R05 由 VLA 迁移方案接管（P0 契约先行）；R07 裁决删孤儿后关门（删除动作在方案 P1） | [dispatcher VLA 技能迁移方案](../iteration/design-dispatcher-vla-migration.md) §5/§7；[工具面契约 §1](../../../specs/implemented/inner/l3-tool-plane.spec.md)；[技能契约 §10](../../../specs/implemented/inner/l3-skill-contract.spec.md) | 本轮仅文档与 spec 更新，无代码与运行证据；工具面 revision 新值已按 §1 七工具元数据重算一致 | R05：P1–P3 实现后按方案 §8 回填验收（REPLAN 技能自有状态、不读宿主 pending_action），`_record_process_event` 记录消费待记录服务（R01/R06）继续挂账；R07：方案 P1 删字段并 grep 零命中后关门 |
| 2026-09-17 | R07 | **已关门**（方案 P1 执行删除） | `l3-dispatcher-planner/ros_packages/dispatcher/dispatcher/core/telemetry.py`：删 `thinking_debug_dir`/`last_thinking_debug_dir` 孤儿字段与目录创建逻辑，原位留中文注释指向本条目 | 删前 grep：代码树内仅 telemetry.py 自身定义命中（零消费者），specs/ 0 命中；删后 grep：`l3-dispatcher-planner/` 全树 `thinking_debug_dir` 0 命中；core-boundary 回归通过（当轮 29 passed，环境缺 zenoh 的 1 项为基线环境问题） | 无（关门）；未来多图调试需求按新设计重新立项，不恢复旧字段 |
| 2026-09-20 | R09 | 登记（不迁） | [场景图迁移方案](../iteration/design-dispatcher-scenegraph-migration.md) §4.1 裁决 6/8/9；契约先行产物见 `l3-scenegraph`、`l3-skill-contract` §11、`l3-tool-plane` §1 目标集合 | 本轮仅契约与文档改动，无代码与运行证据；未运行测试或构建 | `scene.navigate` 落地时按条目「必须验证」回填；在线建图恢复须先接回地图依赖并另立契约 |
| 2026-09-20 | R05（VLA 部分） | **VLA REPLAN 退役**（记录消费继续挂账） | [机上收窄方案](../iteration/design-dispatcher-vla-waypoint-executor-migration.md) P0–P3：`vla_skill` 重写为航点执行器（三裁决），机上几何/`geometry_source`/`get_fast_rgb` 删除，`base_policy` 几何族退役（3029→1302 行），`_FAIL_REASONS` 登记 `invalid_station_waypoint`；归档 [2026-09-20 决策](../../../specs/implemented/architecture/2026-09-20-vla-waypoint-executor.md) | `py_compile` 全包通过、删除项 grep 零残留、`revision` 按真实注册面重算回填 spec；经使用者许可运行 `pytest l3-dispatcher-planner/tests`（排除 4 个 zenoh 环境基线收集失败）→ **167 passed / 1 failed**，唯一失败 `test_import_closure_has_no_domain_or_ros` 为既有基线（`core/skill_router.py` 提交 `28db4d1` 的 import 与禁用前缀冲突，`core/` 未被本轮触碰） | `host.recording._record_process_event` 记录消费仍待 R01/R06 记录服务；站端 `waypoint_world` 产出归外部仓库（本库 `l4-agent` 非最新），具备条件后补真机/仿真整链验收 |
| 2026-09-26 | VLA 旋转腿补注册（[旧库 VLA 变动迁移方案](../iteration/design-dispatcher-old-repo-vla-convergence.md) P1） | `navigation.vla_rotate` 补注册为第 8 个生产工具（同一 `RotateSkill` 实例双名注册，对齐旧库 `engine._skills`）；`tools/vla/catalog.py` + `execution/composition.py` + `l3-tool-plane` §1 集合/`revision` 同批更新 | 静态验证：`py_compile` 通过；`revision` 复算与契约记录一致（`sha256:32b34a60…1228`）；装配级注册/销毁干净（`install_flight` 双名同实例、`dispose` 后零残留） | 站端重扫腿端到端验收待真机/仿真；测试断言（7 工具集合 + 旧 `revision`）未同步，待使用者许可 |

未来处理后在此追加记录并同步 README 索引。若仍不能接入，不只写“以后处理”，应说明缺少哪个端口/服务、下一次由哪种任务触发；若决定删除，应记录消费者如何退役或被替代。

## dispatcher 直连 planner 的设计约束

2026-09-16 用户已确定不迁入 /mission/task 中间转换层；见
[直连架构决策](../../../specs/implemented/architecture/2026-09-16-dispatcher-direct-planner.md)
及[执行总纲](../iteration/20260915-20260917/design-dispatcher-migration-execution-order.md)。R03 的停止链和
R05 的动作发送/结果接线应直接面向 planner 端口。R04 原点与历史的保留边界不变。当前仅更新设计约束，
代码未改、条目未关闭，仍需直连完成/取消/停止的实现和运行证据。

2026-09-17 执行进度：RPC 前置实现与 103 项回归已完成，飞行接线仍在 S3。已确认
launch/remap、quadrotor_msgs 和 planner_backend 切换链。用户指定
当前 EGO、交付到 cmd；R03 本轮验证停止/保持命令与反馈，不扩展 cmd 后的物理处理；
R04/R05 继续等待对应飞行实现，不以 RPC 完成关闭。

## 2026-09-17 修正前接入验收（历史记录）

| 条目 | 当前处置 | 实现/证据 | 剩余触发条件 |
|---|---|---|---|
| R03 | 已接入至 cmd | planner_execution_ros.py、EGO cancel/mandatoryStop 回调、ego.launch；tests/ros/test_ego_cmd.py 验证实际保持命令 | 更换后端、停止/恢复机制变化时复核；cmd 下游不属本轮 |
| R04 | origin 子能力已接入，其余保留 | tools/flight/session.py、ReturnSkill；无原点失败、会话/坐标重置及真实返航测试 | previous、历史集合、文本回退的真实消费者接入时继续核对 |
| R05 | 飞行动作账务已接入，VLA 部分保留 | execution/skill_host.py、WaypointExecution、ActionGate、生命周期锁；迟到结果/取消/覆盖/实例归属测试 | VLA REPLAN 判据、记录元数据消费接入时继续核对 |

上述实现曾有 115 项完整测试通过；对应 EGO 专属取消/停止代码现已撤回，此结果不覆盖修正版。R01/R02/R06/R07 不被删除或标为已迁。

## 当前职责上行修正

依据[边界修正决策](../../../specs/implemented/architecture/2026-09-17-dispatcher-planner-boundary-correction.md)，
仅删除来源任务编号，当时恢复 yaw_low_speed 及附加目标字段（后者已按当前清理决定移除）。EGO 新取消入口、额外
停止清理及偏航修改已撤回，planner 保持原行为；stopMotion 职责由 dispatcher
的 WaypointExecution 承接，通过同一个目标口发送新批次保持意图。

R03/R05 的取消待处理、旧结果失效和新动作准入守卫均位于 dispatcher；取消发送
失败时不假报停止。R04 及其他保留字段不因本次纠偏被裁剪。按用户要求本轮不新增
测试、不执行测试或构建；此前 115 项通过只作历史，当前修正版不得标为已复验。

共享依赖路径纠正：camera_fov 保持 include/vis_utils/camera_fov.h、
src/camera_fov.cpp 布局，CMake 已同步；不再把公开头文件或实现文件移入额外的适配目录。
本项不改变能力状态，不运行测试或构建。

## 2026-09-17 日志规范归属整理

R01/R02/R06 继续保留待接入。日志规范已补齐 observability 父契约，mission
生产者职责明确归 dispatcher 工具及工具状态机；不为日志恢复已删除的包或构建入口。
本次证据仅为文档 header、父子清单、引用与一致性检查，不代表记录服务交付。
接入条件、历史状态与场景日志消费者核对见
[规范整理与日志迁移核对记录](spec-history-and-log-migration.md)。

## 2026-10-09 直连任务结果收敛

依据[方案](../iteration/design-flight-vla-result-convergence.md)和
[决策](../../../specs/implemented/architecture/2026-10-09-flight-vla-result-convergence.md)，
R03/R05 的执行链已作如下代码修正，状态为**代码已接入、运行未验收**：

| 条目 | 实现证据 | 剩余触发条件 |
|------|----------|--------------|
| R05：失败与任务终态 | `N/tools/vla/vla_skill.py::on_action_result` 先检查 success，最后一腿才 ADVANCE；取消复位技能子状态 | 经明确许可后补失败、超时、取消、多腿及重复结果验收 |
| R05：批次后停稳 | `N/tools/flight/flight_waypoint.py`、`N/tools/vla/vla_waypoint.py` 的 poll 保存目标、关联批次并检查递增 odometry 和持续停稳 | 实际反馈时序、原目标不可达、速度差分噪声、重复快照与停稳超时需受控运行证据 |
| R05：新鲜状态与高度 | `N/execution/skill_host.py::VlaSkillHost.state`、`N/execution/ports.py::FlightConfig`；删除近点成功路径和重复高度配置 | 迁移部署参数；贴地须配置 ground_z；旧 vla 高度/近点参数明确拒绝 |
| R05：累计旋转 | `N/tools/flight/rotate_skill.py` 解缠实际偏航、逐段核对累计角 | 多圈、跨 ±π、反向运动及观测缺口需运行验收 |
| R03：取消/保持 | 沿用既有目标覆盖和取消待处理机制；VLA 每一腿失败均走 fail_sequence，未恢复 mission 层 | 运动中取消、失联后保持重试及 cmd 收敛仍需运行证据；不关闭 R03 |

新增动态信息由 `N/ros_adapter/planner_execution_ros.py` 写入快照，领域执行器
进行停稳判定。未新增测试、未运行验收或构建，旧测试构造的状态及 VLA 参数
需在获许可后的测试轮次同步，不沿用历史通过数字。R01/R02/R06 记录服务继续
挂账；core 依赖、通用 schema 原因码与既有参数全量命名整理不属于本轮。


## 2026-10-09 原生 action 接入

依据[原生 action 方案](../iteration/design-planner-native-action.md)，R03/R05 迁移归属如下。

| 条目 | 当前实现位置及行为 | 剩余触发条件 |
|----|----|----|
| R03 停止与保持 | `ros_packages/planner/planner_execution/src/execution.cpp` 统一停止阶段；EGO/DIFF 原生停止轨迹及 SUPER 保持 cmd 接管；动态停稳后确认取消 | 经明确许可后覆盖真实运动中取消、定位丢失、停止超时、后端差异与实机动态；未关闭 |
| R05 动作通信与停稳 | `ExecuteWaypoints.action`、服务端 `settle_monitor.cpp`；旧消息与两家族执行器已删除；原始目标和新鲜连续观测仍为成功依据 | 经许可后补新接口领域与至 cmd 证据；外部消费者须同步迁移；未关闭 |
| R05 客户端归属 | `N/execution/action_session.py` 和 `N/execution/skill_host.py` 共用会话并绑定发送代次/owner；取消结果未确认时禁止后继目标 | 验证迟到终态、断连、重启、覆盖和同名重注册；旧代次不允许标记为当前代次 |
| R03 安全恢复 | `/planner/execution_state` 提供启动标识、恢复代次与就绪；显式停止确认后解除本地闭锁 | 验证丢失结果及恢复时序；不以连接恢复作为已停止证据 |
| 配置与启动 | `bringup/config/planner_execution.yaml`、EGO launch 与构建脚本；旧执行参数拒绝 | 所有部署侧启动器加载同源配置；SUPER/DIFF 补运行证据；未接入能力显式拒绝 |

本轮依据为上述实现位置，**没有测试、构建或运行证据**。起降和急停工具的 forwarded 语义、
VLA 多腿、累计旋转及其他保留项不因引入 action 自动关闭。R03/R05 的可关闭条件仍包含
真实后端停止与恢复证据；相关代码再次调整时须同时维护此处和索引。


## 2026-10-10 强制取消与资源边界更新

当前 R03/R05 的取消归属以下表为准，前述“普通取消不发急停、owner 保留到停稳”的记录退为历史。

| 条目 | 当前实现证据 | 剩余触发条件 |
|----|----|----|
| R03 强制停止入口 | `N/tool_plane/runtime.py`、`control_plane.py`；取消与急停绕过普通队列，停止发送先于异步清理 | 许可后补满队列、长调用、异常钩子和发送竞态的运行证据 |
| R05 任务资源释放 | `N/execution/action_session.py` 的 StopRecord 与 token 回调；`core/skill_router.py::release_call`；代次失效、清指令及技能多腿状态 | 迟到结果、旧调用清理与新调用并发、资源引用释放须验收 |
| R03 独立保持 | `planner_execution/command_output_ros.cpp`；独立回调及短锁输出屏障；三后端原生停止 | 定位缺失、制动效果、输出连续性和停止超时需真实证据 |
| R03 DIFF 跟踪接管 | `diff_planner/Apps/traj_server.cpp`、PolyTraj 归属字段、CommandState 回执 | 生成消息须同步重建；跨 topic 时序、断连与跟踪进程重启待验收 |
| 常驻资源保护 | 停止只清导航目标、轨迹和任务归属；不调用地图清空、飞行原点 reset 或端点注销 | 许可后证明停止期间建图和定位连续，地图及原点保留 |
| 外部调用链 | 本仓库现行线上契约仍为站端独立急停工具调用；未定位 CoPaw 按钮实现和设备控制闭环证据 | 取得站端源码和部署入口后核对按钮请求及设备控制边界；不得据本地修改关闭条目 |

本轮没有构建、测试或运行证据；R03/R05 保持未关闭，其他记录服务保留项不变。


<a id="r10"></a>
## R10 — 连续目标跟踪（代码接入，未验收）

- **触发条件**：迁移 `navigation.track`、调整视觉观测、连续规划、导航与跟踪切换、
  正常完成或取消时，须同时读取本项及 R03/R05。
- **DiffAgent2 旧版调用链**：站端 grounding/人工框选 → `tools/track/skill.py` →
  UETrack 服务与 bbox → mission tracking 生命周期 → Elastic → MotionGate。
  原动作取消回执不构成新版动态停止证据。
- **DiffAgent2 新版归属**：`N/tools/track/track_skill.py` 持有流程；
  `N/perception/tracking_frames.py` 保存原始 seed；`N/ros_adapter/tracking_*_ros.py`
  收发图像与观测；`N/execution/action_session.py` 共用 owner、结果与停止账务。
  `ros_packages/planner/elastic_tracker/` 是纯算法与 ROS 外壳；
  `planner_execution` 共用原生 action 生命周期和唯一 CommandOutput；EGO 注入地图查询。
- **实现证据**：新增 `TrackTarget.action`、`TrackingObservation.msg`、
  `bringup/launch/tracking.launch`、`bringup/config/tracking.yaml` 和 `docker/tracker/`。
  普通导航满足目标门后追加保持接管与动态停稳；连续动作内部收尾只有在业务候选与
  stop_confirmed 汇合后才提交 workflow_result。旧 mission/MotionGate/任务编号未迁入。
- **接入建议与部署条件**：仅显式入口装配第九项工具；默认八项不变。先准备本地模型权重
  及摘要清单、GPU 服务、相机外参、对齐深度和原图时戳，再对齐站端发现与完成元数据。
  首期只装配 EGO；SUPER/DIFF 连续跟踪未迁。记录服务仍归 R01/R06。
- **验收与剩余条件**：本轮未运行测试、编译、门禁或验收，无运行证据。须获明确许可后
  覆盖 seed 错帧、低置信度、无深度、地图失效、旧代次、长规划中取消、完成后保持、
  与普通导航切换，以及真实站端到 `/setpoint_cmd` 链路。
- **可删除条件**：相关实现获准验收、站端消费者完成对齐、生产集合与契约同步后，才可
  关闭迁移条目；不得仅因新版已有代码就删台账或宣布可飞行。

### R03/R05 本轮补充（2026-10-10）

tracking 共用原生停止门和设备停止确认；正常业务结束使用内部 action 取消并保留技能 owner，
外部取消仍立即释放任务资源。普通航点成功增加保持阶段，安全停止或取消优先于成功候选。
`CommandOutput::requestStopIfCurrent` 只封锁匹配代次，防止迟到采样撤销后继导航。
上述均为代码接入证据；R03/R05 继续未关闭，原有实机动态与恢复条件不变。


### 2026-10-12 地图方案作废与重新评估

此前 `design-shared-map-compatibility.md`、`design-single-map-migration.md` 及其共享地图优化代码全部作废并撤销；此前已提交的 tracking 迁移保留。新的讨论边界是 EGO 与 Elastic 是否独立建图，EGO 内部大小图保留原有职责。

[重新评估方案](../iteration/design-ego-elastic-map-sharing.md)取代上述方案。当前代码恢复为 EGO 注入占据查询的迁移基线，未恢复 Elastic 独立融合器；地图兼容性仍未解决。未知/越界分类、目标屏蔽与交付检查、观测覆盖和读取一致性均为剩余条件。R10 及关联 R03/R05 不关闭，先前代码交付记录不代表地图语义已兼容。此次仅撤销代码和重新设计，未运行测试、构建或验收；没有新的运行证据。

第二轮源码评估已细化至重新评估方案 §4.6–§4.10：膨胀非占据不能证明射线自由观测，直接取消目标屏蔽可能阻断预测，读取协议须避免 EGO/Elastic 依赖环，分类快照与观测记录均需计入增量资源。共享仍为条件性候选；没有实现变更和运行证据，相关剩余条件保持开放。


### 2026-10-12 重新评估方案第一版尝试接入

[新方案 §11–§12](../iteration/design-ego-elastic-map-sharing.md)已接入 EGO 小图一致分类快照，替换 MapPort、freeze 接入及伪 OccGridMap；EGO 内部大小图保留。Elastic 无独立概率融合器，飞机通行和交付使用未屏蔽地图及历史射线自由证据，目标预测与飞机碰撞分开。源时戳/融合时间/单调期限及重置代次显式判定有效性。

R10 当前为代码尝试交付、未编译与验收。后续触发条件包括：逐格观测年龄策略、厚目标及贴墙可见性、完整预测覆盖、读取锁争用、离散轨迹检查和增量资源预算；与 R03/R05 的停止及切换条件一并保留。未执行测试、构建或门禁，没有运行证据，不满足条目可删除条件。

# dispatcher 待迁依赖与保留项台账

更新日期：2026-09-17。状态：R03/R05 的控制职责已上行修正到 dispatcher，修正版未重跑测试；R04 原点子能力保留，其余历史/VLA 消费继续保留；R01/R02/R06/R07 待迁；R08 已删除且不自动恢复。

本文件记录已批准的暂时保留及后续处理线索，不定义新契约。用户明确要求：保留项在未来接入或优化时重新判断，不能因为当前生产技能为空而直接删除。未来实现方案仍按 `iteration/_TEMPLATE.md` 落盘；如需改变端口或行为契约，先更新 `specs/`。

## 取证与使用方式

| 标记 | 含义 |
|----|----|
| `N/` | DiffAgent2 新版：`l3-dispatcher-planner/ros_packages/dispatcher/dispatcher/` |
| `O/` | DiffAgent2 旧版：`drone_projects/l3-dispatcher-planner/ros_packages/dispatcher/dispatcher/` |
| 旧版快照 | 所属编排仓库提交 `1b5fef5`，核对时 dispatcher 源码相对该提交无差异；这里只记录相对路径，主机检出位置不入库 |
| 定位方式 | 优先按符号搜索，再参考行号；旧版行号取自上述快照，新版以符号为准，避免未来编辑造成锚点失效 |
| 维护要求 | 对应能力开始设计时即读本条目，不要等写完代码才补查；本轮未改造的缺口不算已交付能力 |

### 为什么有些开关只有参数，没有完整功能

早期[核心迁移方案](../iteration/design-dispatcher-core-inference-migration.md)将 recording、悬停辅助方法和技能实现排除在 core-only 迁移范围之外；[结构稳定化方案](../iteration/design-dispatcher-architecture-stabilization.md)把相关能力登记为后续轮次。新版提交 `7fc6827` 中已经存在“保留 record_stop_event 参数、没有记录调用”的状态，不是本轮清理才删掉逻辑。

随后用户允许删除所有未迁入生产工具链；当前的保留状态是这次跨版本审核明确决定留下的迁移线索。它们没有使空生产注册面自动恢复。旧方案中含任务编号的实现只用来理解历史用途，不得迁入新版。

<a id="r01"></a>
## R01 — 停止事件记录开关与任务覆盖语义

| 项 | 内容 |
|----|----|
| 对应审核 | B01、D01；本轮保留 `record_stop_event` |
| 新版位置与现状 | `N/engine.py::DispatcherEngine._enter_global_stop`。参数仍在，但函数体不读取它，**当前不产生停止记录**；不能把传 True 理解为已经落盘。 |
| 旧版生产/消费链 | `O/engine.py:1546` 依据开关调用 `_recording._record_task_stop_event`；任务覆盖入口 `_pause_for_new_agent_prompt`（`:1073`）传 False，防止把覆盖动作误记为普通停止。 |
| 何时重新参考 | 开始迁入 RecordingService、停止/完成过程记录、任务覆盖或仿真重置流程时；或准备删除此参数时。 |
| 接入位置与顺序 | 先明确记录服务的独立归属和注入接口；再在跨域停止入口按开关调用服务；最后检查覆盖、取消、硬停、软停、重置每个调用点是否应记停止事件。保持 core 无具体技能 import。 |
| 仍未处理 | 新版没有记录服务实例；新任务覆盖暂只传 `shutdown_program=False, publish_hold=False`，未恢复旧版的 `record_stop_event=False` 选择。接入记录功能时必须同时复查，否则默认 True 会开始产生此前没有的记录。 |
| 必须验证 | 每类停止记录的产生/不产生与次数；记录关联原调用而非新覆盖调用；重复停止不产生重复终态；记录服务失败不妨碍队列和动作安全清理。 |
| 何时可删除 | 明确放弃停止记录，或新服务已提供等价且验证过的生命周期策略、不再需要此开关时，连同参数和调用点一起删除；不能只因当前没有消费者删除。 |

<a id="r02"></a>
## R02 — 软停日志开关与结构化停止事件

| 项 | 内容 |
|----|----|
| 对应审核 | B02、D01/D02；本轮保留 `emit_soft_stop_log` |
| 新版位置与现状 | `N/engine.py::_enter_global_stop` 中 `if emit_soft_stop_log` **仍有效**，控制软停的 `runlog.warn`；它不控制急停发布或任务清理。 |
| 旧版依据 | `O/engine.py:1540` 控制结构化事件 `emergency_stop_soft`；重置回调（`:814`）和任务覆盖入口（`:1073`）显式传 False。 |
| 何时重新参考 | 接入统一运行日志/结构化事件、重置服务、覆盖或取消流程，或重整停止日志策略时。 |
| 接入建议 | 区分普通文本日志、结构化停止事件、R01 的持久化记录，分别决定哪些场景应抑制。先确定事件字段与消费者，再恢复结构化上报，不要让同一停止被多个层重复记录。 |
| 仍未处理 | 旧版结构化事件和新版文本警告不完全等价；旧版某些传 False 的调用方尚未迁入。不是“整个条件分支没迁”，也不是“所有调用都需要日志”。 |
| 必须验证 | 软停 True/False 各自输出；硬停不受该开关影响；关闭日志仍完成清理；任务覆盖不制造错误的操作员急停记录。 |
| 何时可删除 | 新日志策略确认无需调用方选择、且所有原传 False 场景已得到等价处理时，再删开关；不得与 R01 的开关混为一项。 |

<a id="r03"></a>
## R03 — 急停悬停与执行侧停止路径

| 项 | 内容 |
|----|----|
| 对应审核 | B03、D01/D02；保留 `publish_hold`，本轮注明“急停悬停” |
| 新版位置与现状 | `N/engine.py::_enter_global_stop` 在 True 时只调用 `channels.publish_emergency_stop()`；`N/ros_adapter/core_channels_ros.py::RosCoreChannels` 默认发布 `/command/emergency_stop` 的 Empty。**不额外构造悬停 goal**；全局信号保持原语义；当前取消/保持意图由 WaypointExecution 经既有目标口编排，不再依赖新增 EGO 取消回调，修正版未复验。 |
| 旧版完整链 | `O/engine.py:1566` 同时发布急停信号并调用 `_publish_emergency_hold_position`（`:1485`）；后者取位姿、构造并限幅悬停目标、切 planner 模式，然后 `send_task_goal` 覆盖旧轨迹。 |
| 何时重新参考 | 接入飞行 skill、航点执行端口、下行执行缝、planner/飞控桥、租约丢失安全停或修改急停语义时，必须在端到端接线前读取。 |
| 本轮方案判断 | 保持“急停后悬停”的目标，不改成停桨、返航或自动降落。当前缺少速度、可用定位和控制模式等实机证据，不能判定另一种方案普遍更好。应由执行侧以可实现的制动轨迹进入悬停，core 只触发安全停止，不在 core 增加飞行动作算法。 |
| 已有下游线索 | 新版 `ros_packages/planner/ego_planner/plan_manage/src/ego_replan_fsm.cpp` 的 `mandatoryStopCallback`（约 1285 行）进入 EMERGENCY_STOP，相关分支调用 `callEmergencyStop(odom_pos_)`（约 361 行）；订阅名是 `mandatory_stop`（约 89 行）。bringup/launch/ego.launch 保留既有急停信号映射；新增取消回调和后端停止修改已撤回，当前修正版未重跑 cmd 验证。 |
| 接入/优化步骤 | 先验证急停主题到所用 planner 的链路、停止轨迹的生成与跟踪、制动后保持和恢复条件；再决定是否还需要旧版额外 hover goal。若已有停止链可靠完成悬停，避免同时发送相互覆盖的两类目标；若仍需 hover goal，将其放在执行缝/适配端口，按现行契约实现。 |
| 必须验证 | 运动中触发后速度收敛与位置保持、旧 goal 不再继续、重复触发、定位不可用、模式切换和重启时停止语义；取消/覆盖 False 不发布急停；硬停请求发出不等于实机已悬停。 |
| 何时可删除或改名 | 只有最终安全停止链已选定、无需独立 hover goal 的结论有运行证据时，才重新评审 publish_hold 的名称或拆分；若删除旧悬停路径，需记录替代路径和验证结果。当前不做仅按 Empty 发布行为的机械改名。 |

<a id="r04"></a>
## R04 — 返航快照、历史游标与任务文本回退

| 项 | 内容 |
|----|----|
| 对应审核 | B08、B10、B11 |
| 新版保留位置 | `N/core/state_ledger.py::StateLedger.last_state`；`N/core/prompt_queue.py::PromptQueue.replan_content`、`previous_return_record_cursor`，以及 `frame_state_get`、`last_state_set` 写入回调。 |
| 当前有效部分 | `pop_next_task` 复制当前 frame.current_state 写入 ledger.last_state，并把准备队首存入 replan_content 再放入 command_content；全局停止会清 replan_content 和游标。last_state 是位置状态快照，不是 FSM 上一状态。 |
| 旧版消费链 | `O/tools/flight/flight_skill.py:132` 调用 `recording._resolve_return_plan`；`O/recording.py:367` 读取历史回退游标、`:435` 更新游标、`:443` 在记录不足时读取 last_state；`:41` 读取 replan_content 作任务文本回退。 |
| 何时重新参考 | 接入 `flight.return`、返回上一位置/原点、过程轨迹记录、导航历史恢复，或把队列数据迁往服务时。 |
| 接入建议 | 先实现历史记录和目标解析服务，再让飞行技能通过服务解析返航目标；从现有快照/队首接口传入所需数据。旧版读 `host.last_state`，新版实际在 `host.ledger.last_state`；不能靠给 engine 增加同名属性桥接，也不能让技能绕过端口到处读内部对象。 |
| 仍未处理 | ReturnSkill 已通过 FlightSession 消费确认的起飞原点，不使用 last_state 冒充原点；旧历史集合/逐步回退未迁，游标仍不前移。旧快照字段继续保留待其真实消费者接入。 |
| 必须验证 | 连续两次返回上一位置确实逐步后退；无记录/无原点时的回退或明确失败；快照不是随帧原地更新的别名；重置、覆盖与新会话不读取过时位置；任务文本回退仍对应本次调用。 |
| 何时可删除 | 历史服务已独立拥有位置与游标，或产品明确取消逐步返航且调用方已清理时，删除旧字段及快照回调。replan_content 只有在记录服务不再使用该文本回退并有替代后才能改为纯局部变量。 |

<a id="r05"></a>
## R05 — 动作上下文、武装接口与 VLA 重规划

| 项 | 内容 |
|----|----|
| 对应审核 | C01–C03 |
| 新版保留位置 | `N/core/action_gate.py::PendingAction`、`ActionGate.pending_action`；`handle_post_action` 的 REPLAN 标记清理和 `clear_action_state` 的全量清理。 |
| 当前状态 | DispatcherFlightHost.start_goal 已接入飞行动作武装、实例归属、代次和当前批次反馈；取消/停止控制已改为 dispatcher 的目标覆盖方式，本次未复验。VLA 专属重规划和记录读取仍未接入，旧 arm_action 仅作历史线索。 |
| 旧版生产链 | `O/tools/vla/vla_skill.py:606`、`O/tools/flight/flight_skill.py:84` 和场景导航技能调用宿主 arm_action；`O/engine.py:1596` 武装，`:1623` 起写元数据。 |
| 旧版读取链 | VLA `on_action_result`（`:487`）读取 replan_cmd 决定 REPLAN；`O/engine.py:574` 用 prompt_raw 下发目标；`O/recording.py:35` 用它回退当前任务文本；动作准备日志（`O/engine.py:1643`）读取 action_name、instruction_type。 |
| 字段级区分 | replan_cmd、prompt_raw、action_name、instruction_type 有上述明确读点；replan_reason 见写入/清理；waypoint、look_forward、nav_yaw、yaw_source、is_far_push 在该上下文快照中未确认完整消费者，不能把 skill 中其他同名概念当成此对象读点。整类保留不等于每个字段永久保留。 |
| 何时重新参考 | 实现 SkillHost.arm_action、动作结果回调、VLA 临时动作后重规划、飞行/场景技能动作发布，或调整动作元数据模型时。 |
| 接入顺序 | 明确哪些是通用动作账务、哪些是技能内部语义；按端口接入动作武装、实例归属、代次、结果与清理；再迁 VLA 判据和记录消费。旧版 `host.pending_action` 当前已在 `ActionGate` 内，需设计显式读取/生命周期端口或技能自有状态，不复制宿主私有访问或造旧入口转接器。 |
| 必须验证 | 临时动作完成只进入 REPLAN 且不提前 done；重新武装后旧结果被代次拒绝；停止/覆盖后标记清理；动作归属不随名字重新注册漂移；对外调用终态唯一。 |
| 何时可删除 | 技能自有会话/通用动作记录已覆盖所有真实读点，并验证重规划、记录与发送文本后，逐字段裁剪或整体替换。保留清理生命周期，不能只搬数据而丢掉停止时的逆操作。 |

<a id="r06"></a>
## R06 — 运行会话标签与记录服务

| 项 | 内容 |
|----|----|
| 对应审核 | B14 |
| 新版保留位置 | `N/core/telemetry.py::RunTelemetry.log_session_tag`；engine.runlog 持有该对象。trace 当前确实使用同次构造生成的 session_tag。 |
| 旧版证据 | `O/recording.py:53` 写日志快照、`:67` 写上行记录信封时读取 engine.log_session_tag。 |
| 何时重新参考 | 迁入 RecordingService、日志快照/上行、重连补发，或设计跨进程会话关联时。 |
| 接入建议 | 从遥测对象显式传入会话标签或记录配置；不要在记录服务另造一个会话标签，也不要为了旧版属性名给 engine 加转接属性。用户日志契约若已采纳，应先据其明确字段含义。 |
| 仍未处理 | 上行记录与快照服务已退役待重建；当前标签格式的唯一性需求未做新的保证，不能等同 call_id。 |
| 必须验证 | 同次运行 trace 与记录服务使用相同会话标签；重启/并行实例是否满足实际关联要求；快照和补发记录不跨会话误归属。 |
| 何时可删除 | 新会话服务成为唯一来源、所有记录消费者已切换，或明确只保留 trace 且不需要向其他服务传出标签时，才删除重复属性。 |

<a id="r07"></a>
## R07 — VLA 多图思考调试目录

| 项 | 内容 |
|----|----|
| 对应审核 | B15 |
| 新版保留位置 | `N/core/telemetry.py::RunTelemetry.thinking_debug_dir`、`last_thinking_debug_dir` 及目录创建逻辑。 |
| 当前状态 | 启动时创建目录并输出开启日志；没有生产 VLA 消费者写入。普通 trace 独立工作。 |
| 旧版证据 | `O/tools/vla/vla_skill.py:886` 在搜索耗尽后的多图推理分支调用保存；`:1082` 清旧目录，`:1114` 创建本轮目录并保存视图与元数据，`:1190` 写 last_thinking_debug_dir。后者在核对快照中见赋值，不据此假定存在其他读取方。 |
| 何时重新参考 | 接入 VLA 搜索、多图推理、调试图保存或修改日志落盘管理时。 |
| 接入建议 | 决定目录归 VLA skill 还是共享记录服务；通过显式配置传路径，按资源生命周期管理写入与清理。旧版从 host 直接取字段，新版位于 RunTelemetry；不应把领域调试逻辑重新塞进 core。 |
| 必须验证 | 禁用时不创建/写入；启用时保存当前轮视图和元数据；清理不删除其他调用/会话产物；目录不可写时的失败处理不破坏任务终态；关闭或取消后不继续异步写旧目录。 |
| 何时可删除 | VLA 明确不需要该调试功能，或独立调试服务已接管路径与生命周期后，删除遥测对象上的旧字段、创建逻辑和日志，不影响 trace。 |

<a id="r08"></a>
## R08 — GRASP 抓取感知（已删除登记项，不自动恢复）

| 项 | 内容 |
|----|----|
| 状态 | **已删除，不自动恢复**。由 [grasp 退役登记方案](../iteration/design-dispatcher-grasp-retirement.md) 裁定为不迁移，按 migration-protocol §2-⑥（无调用方或调试残留 → 不迁移）登记。 |
| 平级裁决 | grasp **不是**与 vla/scene_nav/flight 平级的 tool：旧版注册面 14 项 ToolSpec 从未包含 grasp（`O/tools/registry.py:248-261`），旧版自己注释“registry 未放行（spec-gated）”（`O/tools/config.py:23-25`）。它是旧版 engine 持有的 latent 感知子工作流（`GraspWorker` + daemon 线程 + `_grasp_queue`），无 `SkillBase`/身份三声明/`_skills` 注册/`ToolSpec`/executor 分发任何契约点。 |
| 旧版链路（已删除） | `O/tools/grasp/workflow.py`（GraspWorker，`:27-34` 构造队列，`:57` 投递 `_eng._handle_grasp_task`）；`O/engine.py:292-293` 持 `_grasp_wf`、`:2138-2139` daemon 线程启动、`:395-396` 发布 `/agent/grasp_result_image`、`:1113/:1120` 把 `TASK_ID.GRASP=11` 并入 task-phase 聚合；`O/zenoh_rpc.py` 的 `grasp_result/*` queryable（`:122/:170`）、图像/结果 latch（`:37-38/:91-93/:475-501/:590-612/:626-632`）。旧版 spec 定位为 reserved plan/history label（`agent-station-tools.spec.md:495-497`；`agent-station-channels.spec.md §3.10`）。 |
| 不可运行证据 | `workflow.py:14-21` 缺 `cv2/np/CompressedImage/MISSION_TYPE` import；`:57/:132-140/:159/:348/:354` 经 `self._eng.*` 调用的 5 个方法实际都定义在 `GraspWorker` 自身（engine 无 `_handle_grasp_task`/`_serve_search` 等）；全仓 `_grasp_queue.put` 0 命中，任务队列零生产者。 |
| 新版已删除面 | `N/iteration/design-dispatcher-unmigrated-chain-removal.md:108`：资源主题 `grasp_result/*`、ROS 反馈 `/agent/grasp_result_image`、grasp 线程均已删除；`N/tests/tool-registry/test_rpc_plane.py:21-29` 空发现面锚定 22 个已删除名一律 `method_not_found`；新版 l3 代码与 specs 全树 grep “grasp” 0 命中。 |
| 何时重新参考 | 仅当出现**真实站端消费者**需求（如站端在飞行动作词汇上明确要求 GRASP 抓取感知结果）时，先读本条目与 [grasp 退役登记方案](../iteration/design-dispatcher-grasp-retirement.md)。不存在“顺手恢复”场景。 |
| 接入条件（技能化） | 先按 `l3-skill-contract.spec.md` 出契约（身份三声明、生命周期钩子、四裁决、语义端口）；实现与测试**同批**交付并通过 `N/tests/core-boundary/`、`N/tests/tool-registry/`；技能进入发现面时同步更新 `l3-tool-plane.spec.md` 的集合与 `revision`。感知入口（旧版为 vla 私有的 `_serve_search`）与几何能力（`GeometryService`）若复用须重新设计归属，不原样搬运、不造转接器、不引入任务编号。 |
| 必须验证 | 技能完成门/裁决与实例归属；感知结果与图像按现行端口契约出站；发现面 revision 与 spec 一致；站端读模型有真实消费者且非恒 404 的占位路由。 |
| 何时可删除 | 本条目唯一存在价值是留证与触发条件登记：若产品明确永久放弃 GRASP 感知、且上述接入条件不再需要被任何未来任务触发，可删除本条目与 [grasp 退役登记方案](../iteration/design-dispatcher-grasp-retirement.md)；删除前须在「后续关闭条目的记录格式」表中留一行处理记录。 |

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
| first_image、感知中的 first_frame/first_waypoint/first_depth 残留 | 用户明确暂不保留 first 系列首帧功能；后续 VLA 迁移不得因为旧版有 first_rgb/首帧发布器就默认恢复。若新方案确需首帧对比，重新明确需求和归属。点云去重的局部 first_indices 不是首帧缓存功能，保持不动。 |
| last_plan_time | 新旧核对未发现实际读取；删除无效计时缓存。若以后需要耗时测量，应设计真实的时间来源及消费者。 |
| ActionGate 四个未调用回调、PromptQueue 两个未调用 getter | 只删多余接线，不删实际宿主状态/帧/航点及 R04 的快照写入；未来技能需要读数据时按端口重新设计。 |
| pre_prompt、prompt_bf、content | 删除文本副本；保留结构化队列、prompt 与 replan_content，避免误伤记录服务待迁依赖。 |
| dispatch_plan 的 cmd 入参 | 调用只传 SkillCommand；不删原始调用名或日志文本。 |

## 后续关闭条目的记录格式

| 日期 | 条目 | 状态 | 接入/替代/删除实现位置 | 验收证据 | 尚需参考的触发条件 |
|----|----|----|----|----|----|
| 2026-09-16 | R01–R07 | 保留待接入 | 见各项新版位置，本轮不迁生产技能 | 本轮验证保留状态未被清理，不能替代未来生产能力验收 | 按各项“何时重新参考”触发 |
| 2026-09-16 | R03、R05 与 l4 对接前置 | 继续保留；设计中 | [RPC 对接方案](../iteration/design-dispatcher-l4-rpc-integration.md)、[基础飞行方案](../iteration/design-dispatcher-basic-flight-migration.md) | 只读检查发现 owner watch 未接 acquire；复现快速终态丢失、非法 JSON 顶层无回复和失效租约重放获准。未改生产代码，未完成物理停止验证 | 前置轮次先修协议与监听；飞行轮次接完整执行缝、动作账务与急停轨迹；VLA 专属重规划仍待其技能迁移 |
| 2026-09-16 | R04、R06 原点/历史边界 | 继续保留；仅原点子能力已出方案 | [基础飞行方案 §4.5](../iteration/design-dispatcher-basic-flight-migration.md#45-原点服务与-r04-范围) | 当前只读 l4 的 plan_tools.json 定义 return 空参返回起飞点；FlightSession 仅为设计，尚无实现/运行证据 | 起飞原点随基础飞行接入；previous、历史集合、游标和文本回退待真实消费者迁移，不因本轮无公开入口裁掉；日志 session_tag 不等于飞行会话 |

未来处理后在此追加记录并同步 README 索引。若仍不能接入，不只写“以后处理”，应说明缺少哪个端口/服务、下一次由哪种任务触发；若决定删除，应记录旧版消费者如何退役或被替代。

## dispatcher 直连 planner 的设计约束

2026-09-16 用户已确定不迁入 /mission/task 中间转换层；见
[直连架构决策](../../../specs/implemented/architecture/2026-09-16-dispatcher-direct-planner.md)
及[执行总纲](../iteration/design-dispatcher-migration-execution-order.md)。R03 的停止链和
R05 的动作发送/结果接线应直接面向 planner 端口，旧版 send_task_goal 仅是历史调用
证据，不要求恢复旧 action。R04 原点与历史的保留边界不变。当前仅更新设计约束，
代码未改、条目未关闭，仍需直连完成/取消/停止的实现和运行证据。

2026-09-17 执行进度：RPC 前置实现与 103 项回归已完成，飞行接线仍在 S3。已在
DiffAgent2 旧版找到 launch/remap、quadrotor_msgs 和 planner_backend 切换链。用户指定
当前 EGO、交付到 cmd；R03 本轮验证停止/保持命令与反馈，不扩展 cmd 后的物理处理；
R04/R05 继续等待对应飞行实现，不以 RPC 完成关闭。

## 2026-09-17 修正前接入验收（历史记录）

| 条目 | 当前处置 | 实现/证据 | 剩余触发条件 |
|---|---|---|---|
| R03 | 已接入至 cmd | planner_execution_ros.py、EGO cancel/mandatoryStop 回调、ego.launch；tests/ros/test_ego_cmd.py 验证实际保持命令 | 更换后端、停止/恢复机制变化时复核；cmd 下游不属本轮 |
| R04 | origin 子能力已接入，其余保留 | services/flight_session.py、ReturnSkill；无原点失败、会话/坐标重置及真实返航测试 | previous、历史集合、文本回退的真实消费者迁入时继续参考旧链 |
| R05 | 飞行动作账务已接入，VLA 部分保留 | execution/skill_host.py、WaypointExecution、ActionGate、生命周期锁；迟到结果/取消/覆盖/实例归属测试 | VLA REPLAN 判据、记录元数据消费迁入时继续核对 |

上述旧实现曾有 115 项完整测试通过；对应 EGO 专属取消/停止代码现已撤回，此结果不覆盖修正版。R01/R02/R06/R07 不被删除或标为已迁。

## 当前职责上行修正

依据[边界修正决策](../../../specs/implemented/architecture/2026-09-17-dispatcher-planner-boundary-correction.md)，
仅删除来源任务编号，恢复 yaw_low_speed、goal_to_follower。EGO 新取消入口、额外
停止清理及偏航修改已撤回，planner 保持原行为；旧 stopMotion 职责由 dispatcher
的 WaypointExecution 承接，通过同一个目标口发送新批次保持意图。

R03/R05 的取消待处理、旧结果失效和新动作准入守卫均位于 dispatcher；取消发送
失败时不假报停止。R04 及其他保留字段不因本次纠偏被裁剪。按用户要求本轮不新增
测试、不执行测试或构建；此前 115 项通过只作历史，当前修正版不得标为已复验。

共享依赖路径纠正：camera_fov 保持 DiffAgent2 旧版布局（include/vis_utils/camera_fov.h、
src/camera_fov.cpp），CMake 已同步；不再把公开头文件或实现文件移入额外的适配目录。
本项不改变能力状态，不运行测试或构建。

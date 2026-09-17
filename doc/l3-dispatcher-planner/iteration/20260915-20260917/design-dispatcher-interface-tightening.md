# dispatcher 函数收紧分类审核单

> 2026-09-16 用户已允许按旧版核对后的建议执行，并要求留下待迁依赖台账。以下保留审核历史；实际执行范围以 §5 的执行裁决为准。原审核阶段：上一轮未经逐项审核的收紧改动已全部撤回，源码、测试与 core 白名单恢复到该轮开始前。此前的核心拆分、工具工作流改名及未迁入链路删除不受影响。

## 0. 元信息

| 项    | 值                                                                                                 |
| ---- | ------------------------------------------------------------------------------------------------- |
| 日期   | 2026-09-15                                                                                        |
| 目标路径 | `l3-dispatcher-planner/ros_packages/dispatcher/dispatcher/`                                       |
| 状态 | done（已执行获批清理，待迁能力保留并登记到 rest） |
| 关联文档 | `specs/implemented/inner/l3-core-boundary.spec.md`、`l3-skill-contract.spec.md`；本目录 `_TEMPLATE.md` |
| 当前动作 | 已完成代码修改、rest 台账、AGENTS.md 入口及回归 |

文档补充与执行日期：2026-09-16。§4 保留逐项审核批注和执行前证据；实际变更和保留裁决见 §5，后续重看入口见 rest。

## 1. 背景与动机

用户要求先将建议收紧的函数分类成文档，由用户决定哪些删除、哪些保留，再进行处理。该审核阶段已结束；用户于 2026-09-16 明确允许执行，以下保留原审核证据与批注。

判断分为两个层次：函数职责是否应该保留，以及函数内部的参数、字段、分支是否值得收紧。DiffAgent2 新版没有当前读取方只是迁移状态的一部分，必须同时核对 DiffAgent2 旧版的 skill、任务注入、动作执行和记录服务调用链；声明在技能契约中的端口尤其不能因当前生产技能集合为空而直接裁掉。

## 2. 现状事实与证据

下表先记录 DiffAgent2 新版撤回后源码的现状，不能单独作为删除依据。路径相对于元信息中的目标路径；跨版本证据和修订建议见 §4 新增的旧版核对列。

| 证据                        | 当前事实                                                              | 判断边界                                 |
| ------------------------- | ----------------------------------------------------------------- | ------------------------------------ |
| `engine.py:112`           | `record_stop_event` 未在函数体使用；`emit_soft_stop_log` 控制日志，但现存调用均未选择关闭 | 前者是无实现参数，后者是有效但当前未被选择的开关，不能混为一项      |
| `core/action_gate.py:41`  | 构造接收的四个回调只存储、不调用                                                  | 仅能建议收窄入参，不是删除完成门                     |
| `core/action_gate.py:12`  | PendingAction 字段存在初始化、清理及测试人工设置；REPLAN 路径还会清理两个标记                 | 删除整个上下文需要用户确认是否保留给后续动作接口             |
| `core/prompt_queue.py:9`  | 文本副本、位置快照和结构化队列并存                                                 | 应分开审核队列机制和派生数据                       |
| `core/skill_router.py:28` | `cmd` 参数没有参与分发，实际命令来自 `skill_command`                             | 可以单独审核删参数，不必删函数                      |
| `core/telemetry.py:22`    | 每次构造创建思考调试目录，但目前无生产消费者                                            | trace 仍承载诊断；删除调试目录不能连带删 trace        |
| `engine.py:174`           | 推理循环无条件将状态设为 INIT                                                 | 若先收到硬停再启动循环，STOP 会被覆盖；属于行为修复，独立于精简审核 |

### 跨版本核对口径

| 项                 | 核对记录                                                                                                          |
| ----------------- | ------------------------------------------------------------------------------------------------------------- |
| DiffAgent2 旧版取证范围 | 编排仓库中的 `drone_projects/l3-dispatcher-planner/ros_packages/dispatcher/dispatcher/`；下文以 `O/` 表示这个相对目录，不保存主机绝对路径 |
| 取证版本              | 2026-09-16 本地只读核对，所属仓库 HEAD 为 `1b5fef5`；所核对 dispatcher 源码相对该 HEAD 无差异                                         |
| 实际读取对象            | engine、skill\_api、recording，以及 VLA、飞行、场景导航技能；同时检索整个 dispatcher Python 源码中的精确字段与动态 getattr 读取                  |
| 证据级别              | 区分有真实读写/调用链、仅定义或赋值、DiffAgent2 新版拆分后才产生的回调；“未找到”仅针对此快照，不代表所有历史版本或外部扩展                                          |
| 迁移边界              | 旧版依赖证明能力有用途，不表示旧版实现可以原样复制。任务编号、技能访问宿主私有状态、领域逻辑混入 core 等仍须按新版契约改造                                              |
| 本次处置              | 只修订审核文档；不恢复此前已删除的生产工具链，也不删除待迁 skill 所需的现有参数/字段                                                                |

## 3. 执行规则与范围

- 用户于 2026-09-16 明确允许执行；§4 保留用户逐项批注，最终处置见 §5。对“可以”的解释以同一行结合旧版后的建议为准：批准保留不等于批准删除。
- 仅清理确认冗余的参数、回调、首帧缓存和文本副本；旧版有真实消费者的项继续保留并登记到 `../rest/dispatcher-deferred-dependencies.md`。
- 首帧缓存暂不保留是用户明确选择；删除新版 engine.first_image 及感知中的 first_frame/first_waypoint/first_depth 残留，不改点云去重局部索引 first_indices。
- 保持目录架构、类名、六态和方法白名单；不增加兼容转接口，不改变主题、消息字段或已有结构化事件名称。
- AGENTS.md 本轮只增加台账读取入口与维护指引；rest 是迁移过程资料，不替代 specs 中的契约。

## 4. 函数分类与逐项审核

B–E 类采用与 A 类一致的逐行审核表格；在职责和调用关系之外，单列参数/字段的具体作用、DiffAgent2 旧版证据以及修订后的审核建议，便于比较和填写决定。以下调用关系描述代码中的现有接线；默认生产工具集合仍为空，不代表已有生产技能在执行这些流程。

### A 类：建议保留职责，不因缩短 engine 而搬迁或删除

| 编号  | 函数与位置                                                                 | 当前职责和调用关系                                 | 建议                          | 用户决定 |
| --- | --------------------------------------------------------------------- | ----------------------------------------- | --------------------------- | ---- |
| A01 | `DispatcherEngine._fail_unregistered_dispatch`，`engine.py:152`        | DISPATCH 失败路径调用；统一发布 fail、标记序列失败、停止规划并回空闲 | 保留原样，属于跨对象协调                | 可行   |
| A02 | `DispatcherEngine._enter_global_stop`，`engine.py:112`                 | 主循环、工具覆盖/取消及控制面租约安全停调用；协调队列、动作和状态清理       | 保留函数在 engine；参数改动另审 B01–B04 | 可行   |
| A03 | `ActionGate.action_done`，`core/action_gate.py:66`                     | WAIT\_ACTION\_FINISH 调用；技能完成门、动作代次与最小等待判定 | 保留，不能随 PendingAction 候选一起删除 | 可行   |
| A04 | `PromptQueue.load_next_prompt`，`core/prompt_queue.py:77`              | 动作 ADVANCE 和队列推进调用；装下一条或结束序列              | 保留，维护实际队列生命周期               | 可行   |
| A05 | `DispatcherEngine._recover_inference_after_exception`，`engine.py:326` | run\_inference 异常路径调用；失败终态、代次失效与多域清理      | 保留原样，本轮不扩展异常恢复重构            | 可行   |
| A06 | `DispatcherEngine.run_inference`，`engine.py:348`                      | 装配根启动线程的入口；守护主循环                          | 保留原样                        | 可行   |

### B 类：建议保留函数，仅审核参数、字段或内部片段

| 编号 | 函数与位置 | 当前职责和调用关系 | 本项内容的具体作用（执行前） | DiffAgent2 旧版证据与迁移判断 | 审核范围与建议 | 用户决定 |
| :----- | ----------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------- |
| B01    | `_enter_global_stop`，`engine.py:112`                                                                        | **职责与作用**：统一中断当前任务：推进任务代次使旧结果失效，清准备/执行队列与动作状态，停止继续规划，再按开关发布急停、进入 STOP 或返回空闲。函数属于 engine 的跨对象协调入口。**调用方与时机**：主循环检测到 STOP 命令时调用；ToolWorkflowHost.start\_tool\_workflow 接收新调用时、cancel\_tool\_call 取消当前调用时也调用；租约丢失由 ToolControlPlane 注入的安全停止回调调用。                                                              | record\_stop\_event 从名称看意图是控制停止事件记录，但当前函数体完全不读取它；传 True 或 False 不影响任何日志、状态或发布。不要把“参数存在”当成“已有事件记录功能”。                                                                                                 | **待迁能力依赖**：`O/engine.py:1546` 按 record\_stop\_event 调用记录服务；`:1073` 的任务覆盖入口传 False，避免把任务替换记为停止。**为何新版缺逻辑**：`design-dispatcher-core-inference-migration.md` §4 的摘除表将 recording 相关调用排除在 core-only 迁移范围之外；新版提交 `7fc6827` 已保留 record\_stop\_event 参数而没有对应记录调用，早于本次收紧。结构稳定化方案 §3/后续轮次又明确把 recording 留待迁移。 | 建议保留/暂缓删除。其用途是停止事件记录开关，随记录服务和任务覆盖生命周期一起设计；不能依据 DiffAgent2 新版未读取就判作死参数。                                  | 先不要删除，我需要你说明旧库的if record\_stop\_event 逻辑怎么被删除或者没有迁移过来？      |
| B02    | `_enter_global_stop`，`engine.py:112`                                                                        | **职责与作用**：统一中断当前任务：推进任务代次使旧结果失效，清准备/执行队列与动作状态，停止继续规划，再按开关发布急停、进入 STOP 或返回空闲。函数属于 engine 的跨对象协调入口。**调用方与时机**：主循环检测到 STOP 命令时调用；ToolWorkflowHost.start\_tool\_workflow 接收新调用时、cancel\_tool\_call 取消当前调用时也调用；租约丢失由 ToolControlPlane 注入的安全停止回调调用。                                                              | emit\_soft\_stop\_log 只在 shutdown\_program=False 时决定是否输出那条软停警告日志。它不控制任务清理、不控制急停发布，也不改变最终状态；硬停日志不受它控制。现存调用均未主动关闭它。                                                                                    | **待迁生命周期依赖**：`O/engine.py:1540` 控制 emergency\_stop\_soft 事件；重置入口 `:814` 和任务覆盖入口 `:1073` 显式传 False。**新版并未完全缺失逻辑**：当前 `engine.py:135` 仍有 if emit\_soft\_stop\_log 分支，只是输出 runlog.warn；缺的是旧版那些传 False 的重置/覆盖调用接线，以及旧版结构化事件 emergency\_stop\_soft 的同形上报。新版提交 `7fc6827` 也保留该条件分支。不能将这几件事合称“参数逻辑没迁”。      | 建议保留。DiffAgent2 旧版确有关闭日志的调用方；后续迁入重置/覆盖流程时仍需决定哪些停止应记录，不能因新版当前调用只用默认值而裁掉。                                 | 旧库中有`emit_soft_stop_log的相关逻辑，我需要你说明为什么没有迁移过来，是还没有到步骤还是怎么回事` |
| B03    | `_enter_global_stop`，`engine.py:112`                                                                        | **职责与作用**：统一中断当前任务：推进任务代次使旧结果失效，清准备/执行队列与动作状态，停止继续规划，再按开关发布急停、进入 STOP 或返回空闲。函数属于 engine 的跨对象协调入口。**调用方与时机**：主循环检测到 STOP 命令时调用；ToolWorkflowHost.start\_tool\_workflow 接收新调用时、cancel\_tool\_call 取消当前调用时也调用；租约丢失由 ToolControlPlane 注入的安全停止回调调用。                                                              | publish\_hold=True 实际调用 channels.publish\_emergency\_stop()；False 只跳过这次发布，本地队列与动作仍会清理。它不生成当前位置航点。新任务覆盖和取消显式传 False；租约安全停使用默认 True。这里只审核名称是否改得与实际作用一致。                                                | **新旧语义差异**：`O/engine.py:1566` 同时发布急停并调用 `_publish_emergency_hold_position`；`:1485` 实际构造悬停目标、切规划模式并发送目标。                                                                                                                                                                                             | 暂缓单纯改名。publish\_hold 在 DiffAgent2 旧版确实包含悬停动作；先明确后续执行缝是否恢复悬停语义、应归哪个端口，再决定保留、改名或拆分开关。不得把新版当前“只发急停”当作完整设计。 | 原本设计的急停方案是悬停，我需要你确认是否有其他的更好的急停方案，否则沿用当前方案，但是可以标注“急停悬停”      |
| B04    | `_enter_global_stop`，`engine.py:112`                                                                        | **职责与作用**：统一中断当前任务：推进任务代次使旧结果失效，清准备/执行队列与动作状态，停止继续规划，再按开关发布急停、进入 STOP 或返回空闲。函数属于 engine 的跨对象协调入口。**调用方与时机**：主循环检测到 STOP 命令时调用；ToolWorkflowHost.start\_tool\_workflow 接收新调用时、cancel\_tool\_call 取消当前调用时也调用；租约丢失由 ToolControlPlane 注入的安全停止回调调用。                                                              | shutdown\_program 选择“STOP 并请求程序退出”还是“回到空闲”；publish\_hold 选择是否发布急停，两者控制不同事情。关键字限制是调用写法约束，让调用者明确写出开关名称，不新增或删除运行行为；B01/B02 的决定仍独立。                                                                      | **签名写法候选**：`O/engine.py:814`、`:980` 附近取消入口、`:1073` 任务覆盖都按关键字选择停止行为；旧版同时使用日志与记录开关。                                                                                                                                                                                                                   | 可独立审核关键字约束，但不再预设“最终只剩两个开关”。B01/B02 未决定删除前，仍按完整接口评审，不改变行为。                                               | 可以                                                          |
| B05    | `DispatcherEngine.__init__`，`engine.py:25`                                                                  | **职责与作用**：装配调度核心：初始化 FSM 和共享状态，创建日志、队列、状态账本、动作完成门、技能路由与工作流宿主，并把它们需要的读写回调接好。**调用方与时机**：dispatcher\_node.create\_dispatcher\_engine 构造 DispatcherEngine 时执行，属于节点启动期；不是每次任务都重新构造。                                                                                                                             | first\_image 在构造时置 None，主循环启动时从已有帧保存 RGB 图像；last\_plan\_time 当前只被置为 None，没有更新为实际规划时间。当前没有代码读取二者，因此前者是未消费的首帧缓存，后者也未形成有效计时功能。                                                                          | **未找到旧版技能读取**：`O/engine.py:133`、`:1856`、`:1875` 仅初始化/写入这两个精确字段；VLA 实际使用的是 `first_rgb` 和 `first_image_pub`（`O/tools/vla/vla_skill.py:236`），不是 first\_image。                                                                                                                                          | 仍可作为删除候选，等待审核；证据只表明核对快照内未发现读取，不能保证外部部署无扩展。不要连带删除 VLA 实际使用的 first\_rgb 或首帧发布能力。                          | first系列现在可以删除，后续辛苦暂时不保留first系列功能                            |
| B06    | `ActionGate.__init__`，`core/action_gate.py:41`                                                              | **职责与作用**：创建动作完成判定对象，保存动作结果和代次，接入技能完成门、队列推进与宿主动作状态。它服务于“动作是否结束”和“结束后下一步做什么”。**调用方与时机**：DispatcherEngine.__init__ 构造 ActionGate 时注入回调；主循环随后调用 action\_done 和 handle\_post\_action，停止/恢复时调用 clear\_action\_state。                                                                                            | host\_state\_get/set 原本提供读取/修改 engine.dispatcher\_state 的能力；waypoint\_get 读取 engine.waypoint；frame\_get 读取 engine.frame。当前 ActionGate 只是存储这四个回调，未调用它们。实际状态跳转使用 ledger.set\_state，动作完成使用动作标志、代次与时间回调。 | **新拆分回调候选，需区分状态本体**：DiffAgent2 旧版无 ActionGate 同名构造回调；`O/engine.py:1668` 直接读取动作/帧/航点状态，距离限制分支已注释；VLA 与飞行技能实际通过宿主进行动作发布。                                                                                                                                                                              | 可审核删“新版 ActionGate 不调用的四个回调”，但不能据此删除宿主状态、帧、航点能力。若恢复某种完成判定，再按技能完成门契约设计读取口。                               | 可以                                                          |
| B07    | `PromptQueue.__init__`，`core/prompt_queue.py:9`                                                             | **职责与作用**：建立任务队列对象及其依赖。prepare\_content 保存后续待执行条目，command\_content 保存当前要交给技能处理的条目；每条是 (prompt, SkillCommand)。**调用方与时机**：DispatcherEngine.__init__ 构造 PromptQueue 时调用。随后装配根同步配置任务，start\_tool\_workflow 同步新调用任务，再由 pop\_next\_task 装入当前执行队列。                                                                | if\_plan\_get 可以读取 engine.if\_plan，last\_state\_get 可以读取 ledger.last\_state，但当前队列函数不调用这两个读取口。if\_plan\_set 则确实用于装载任务后请求规划、队列耗尽后关闭规划，应与这两个候选读取口区分。                                                    | **新拆分读取口候选**：旧版无这两个同名构造回调；但 `O/recording.py:443` 确实读取 last\_state，VLA 等技能也有状态推进需求。                                                                                                                                                                                                                  | 仅考虑删除 PromptQueue 内未使用的 getter 参数；不能扩大为删除 last\_state 或 if\_plan。B08/B11 涉及真实待迁返航数据，需保留/暂缓。             | 可以                                                          |
| B08    | `PromptQueue.__init__`、`pop_next_task`，`core/prompt_queue.py:9`、`:54`                                       | **职责与作用**：PromptQueue.__init__ 保存队列依赖；pop\_next\_task 推进任务代次，从准备队列取下一条，放入当前执行队列并打开规划标志。位置快照是该装载动作中的附加步骤。**调用方与时机**：构造由 engine 完成；首次任务由 start\_tool\_workflow 调用 pop\_next\_task，后续条目由 load\_next\_prompt 调用。每次装载时会通过 frame\_state\_get 读取 frame.current\_state，再通过 last\_state\_set 写入 ledger.last\_state。 | 快照对读取到的状态执行 copy，保留任务切换时的状态，避免随输入变化。当前写入确实发生，不能称为“回调未使用”；待审的是快照没有后续消费者，是否仍需保留这一能力。                                                                                                                   | **返航依赖链已确认**：`O/engine.py:1325` 保存 current\_state → `O/recording.py:443` 作为历史记录不足时的返航位置回退 → `O/tools/flight/flight_skill.py:132` 调用 `_resolve_return_plan`。                                                                                                                                         | 建议保留/暂缓。记录快照不是无意义写入；它支撑旧版 flight.return。若后续把位置历史迁到记录服务，须在返航迁移方案中明确替代，不在当前清理中整段删除。                       | 可以                                                          |
| B09    | `PromptQueue.__init__`、`sync_task_buffers_from_prepare`、`pop_next_task`、`clear_all`，`:9`、`:29`、`:54`、`:127` | **职责与作用**：四个函数共同维护任务缓存：构造时初始化；sync\_task\_buffers\_from\_prepare 过滤配置并建立准备队列；pop\_next\_task 装载下一条；clear\_all 在停止/恢复时清空队列。**调用方与时机**：构造由 engine 调用；同步由 engine 构造、装配根配置加载和 start\_tool\_workflow 调用；推进由工作流及 load\_next\_prompt 调用；清空由 engine 的全局停止与异常恢复调用。                                                  | content 是准备条目的纯文本列表；pre\_prompt 是文本列表加“Finish the mission”尾项，装载时会 pop 一个文本但不使用返回值；prompt\_bf 是 pre\_prompt 的副本。真正分发依据来自 command\_content 中的 SkillCommand，不是这三份文本缓存。                                  | **旧版同样主要是派生缓存**：`O/engine.py:499`、`:1296` 构建 content/pre\_prompt/prompt\_bf；`:1321` pop 文本，实际分发仍取结构化队列，未发现技能读取这些文本副本。                                                                                                                                                                               | 可继续作为精简候选；需保持任务注入与队列推进语义。与真实返航快照、记录服务 fallback 分开审核，不能一并当作“无消费者字段”。                                     | 可以                                                          |
| B10    | `PromptQueue.__init__`、`pop_next_task`、`clear_all`，`:9`、`:54`、`:127`                                        | **职责与作用**：构造初始化队列状态，pop\_next\_task 把准备队首转入执行队列并发布命令监控，clear\_all 撤销这些执行数据。**调用方与时机**：engine 构造队列；工作流或 load\_next\_prompt 推进队首；engine 停止/异常恢复清空。                                                                                                                                                           | replan\_content 暂存刚取出的 (prompt, SkillCommand)，本函数随后把同一个条目放入 command\_content，并用其中的文本打印日志；它在函数内确实被读取，但没有后续独立重规划消费者。previous\_return\_record\_cursor 名称指向返航记录游标，目前只有初始化和清空，并未实现游标读取/推进。                | **记录与返航双重依赖**：`O/recording.py:41` 读取 replan\_content 作当前任务文本回退；`:367` 读取 previous\_return\_record\_cursor，`:435` 更新它，支持连续多次“返回上一位置”；飞行入口见 `O/tools/flight/flight_skill.py:132`。                                                                                                                     | 撤回“直接局部变量替代并删游标”的建议，改为保留/暂缓。未来可把这两项放入记录/返航服务，但须一起设计文本回退和历史游标，不应仅按新版队列中的局部用途裁剪。                          | 可以，但是需要你说明下新版队列是怎么执行的                                       |
| B11    | `StateLedger.__init__`，`core/state_ledger.py:7`                                                             | **职责与作用**：创建状态与代次账本，保存 command\_type、command\_status、task\_generation 和失败标志，并接入真实宿主 FSM 状态的读写回调。**调用方与时机**：DispatcherEngine.__init__ 创建 StateLedger；之后 PromptQueue.pop\_next\_task 经 engine 注入的 last\_state\_set 回调写入其中的 last\_state。                                                                      | last\_state 是每次装载任务时复制的 frame.current\_state。它不是 FSM 的“上一个状态”；FSM 迁移的来源状态是 set\_state 内通过 host\_state\_get 即时读取的。删除该位置快照不会删除 FSM 迁移日志，但必须与 B08 的写入流程一起决定。                                            | **返航状态，不是 FSM 历史**：`O/recording.py:443` 在缺少可用历史/原点记录时读取 last\_state；由 `O/engine.py:1325` 写入，FlightSkill 在 `:132` 间接消费。                                                                                                                                                                              | 建议保留/暂缓，与 B08 一起处理。当前字段放在 ledger 是否合适可另行讨论，但已有旧版业务用途，不能定为无消费者。                                          | 可以                                                          |
| B12    | `StateLedger.set_state`，`core/state_ledger.py:18`                                                           | **职责与作用**：统一切换 dispatcher 状态，并在状态确实变化时记录来源状态、目标状态、原因、任务代次和动作信息，为外部诊断提供迁移轨迹。**调用方与时机**：engine 在初始化、分发、动作完成、失败、停止与恢复时调用；ActionGate.handle\_post\_action 执行 REPLAN、ADVANCE、IDLE 裁决时也调用。                                                                                                                       | 待审尾部分支位于状态写入及日志之后：新状态不是 WAIT\_FOR\_MISSION 就显式 return，否则走到函数末尾隐式返回。两种路径目前都没有后续工作，不承担特殊的空闲态处理；建议只考虑这段尾分支和不准确注释，不动状态切换功能。                                                                              | **局部空分支候选**：`O/engine.py:766` 的 `_set_dispatcher_state` 同样在记录迁移之后以 return 结束；后面只有被注释的日志，没有额外状态处理。                                                                                                                                                                                                   | 仍可审核删尾部空分支、修正说明；保留状态写入和迁移事件。旧版技能调用 FSM 的事实不要求保留这个无后续代码的 return 分支。                                      | 可以                                                          |
| B13    | `SkillRouter.dispatch_plan`，`core/skill_router.py:28`                                                       | **职责与作用**：按 skill\_command.call.name 查找技能，记录本轮命中的技能实例，调用异步技能 plan\_tick，并把处理结果交还 engine。未命中或同步技能返回 False，由 engine 决定失败收敛。**调用方与时机**：DispatcherEngine.\_run\_inference\_loop 的 DISPATCH 分支从队首解包 cmd、skill\_command 后调用；核心测试也直接调用，用于验证分发与动作归属快照。                                                             | cmd 是队首中的纯文本说明；skill\_command 是含原始 ToolCall 的结构化命令。函数内部只使用后者。删除 cmd 只减少这个函数的冗余入参，不代表删除队列文本或 prompt\_parsed 日志。                                                                                       | **冗余入参候选**：`O/engine.py:1400` 的 `_handle_plan_tool(cmd, skill_command)` 也不读取 cmd，实际向技能 plan\_tick 传 skill\_command。                                                                                                                                                                                 | 可继续审核删除 router 的 cmd 入参；不删除队列文本，不改变技能接收的 SkillCommand，也不照搬旧版未注册后推进的行为。                                  | 可以                                                          |
| B14    | `RunTelemetry.__init__`，`core/telemetry.py:22`                                                              | **职责与作用**：建立运行日志出口、结构化事件记录和 trace 文件，并发布启动事件；后续 emit、命令内容监控、等待诊断都使用这个对象。**调用方与时机**：DispatcherEngine.__init__ 创建 RunTelemetry 时执行一次；输入是日志端口、core 通道、日志目录和遥测配置。                                                                                                                                              | 局部变量 session\_tag 根据启动时间生成本次运行标签，用来命名 trace 文件，并作为 attach\_trace 参数写入记录。self.log\_session\_tag 只是再把它存成实例属性，目前无读取方；候选只涉及这份额外保存，不涉及真正使用的标签。                                                            | **记录服务依赖**：`O/recording.py:53` 用宿主 log\_session\_tag 写日志快照，`:67` 写上行记录信封；这些都不是 trace 局部变量的读取。                                                                                                                                                                                                       | 建议保留/暂缓。后续恢复记录服务时需共享运行会话标签；若改为显式注入，也应在记录服务接线方案中处理，不因新版只剩 trace 就删除实例属性。                                 | 可以                                                          |
| B15    | `RunTelemetry.__init__`，`core/telemetry.py:22`                                                              | **职责与作用**：建立运行日志出口、结构化事件记录和 trace 文件，并发布启动事件；后续 emit、命令内容监控、等待诊断都使用这个对象。**调用方与时机**：DispatcherEngine.__init__ 创建 RunTelemetry 时执行一次；输入是日志端口、core 通道、日志目录和遥测配置。                                                                                                                                              | thinking\_debug\_dir 指向日志根下的 debug/thinking\_multi；当前构造函数确实创建该目录并打印开启日志。last\_thinking\_debug\_dir 初始化为 None，未用于后续清理。当前没有写入思考图片/结果的消费者；这与持续记录结构化事件的 trace 是两条不同路径。                                   | **VLA 调试依赖**：`O/tools/vla/vla_skill.py:886` 在搜索耗尽的多图推理流程调用调试保存；`:1082` 清理上一轮目录，`:1114` 创建本轮目录，`:1190` 更新 last\_thinking\_debug\_dir。                                                                                                                                                                | 建议保留/暂缓，交由 VLA skill 迁移时决定是否迁到技能内部或专属记录服务。不是无来源目录；当前只是消费者尚未进入 DiffAgent2 新版。                            | 可以                                                          |
| B16    | `DispatcherEngine._run_inference_loop`，`engine.py:174`                                                      | **职责与作用**：运行六态 FSM：等待输入或任务，取队首交给技能，等待动作完成，执行技能裁决，最后处理停止；任务发生异常时由外层守护入口负责恢复。**调用方与时机**：dispatcher\_node.start\_dispatcher\_workers 启动 run\_inference 线程；run\_inference 调用此循环，发生异常并完成恢复后会再次调用。                                                                                                               | 循环启动时再次把 last\_plan\_time 置为 None，并将当前已有帧的 rgb\_image 保存到 first\_image；当前循环不读取它们来推进状态。只有 B05 确认不再保留两字段后，才考虑同步去掉这些写入；输入帧刷新和感知就绪检查仍保留。                                                                 | **与 B05 相同的精确字段核对**：`O/engine.py:1856`、`:1875` 是主循环写入点；VLA 首帧处理使用 first\_rgb（`O/tools/vla/vla_skill.py:236`），未发现读取 first\_image/last\_plan\_time。                                                                                                                                                   | 仅在 B05 获批后同步清理对应写入；其他感知与 VLA 首帧数据不属于这一项。                                                                | 可以                                                          |

B05/B06/B07/B08 的构造接线统一位于 `DispatcherEngine.__init__`。批准某项只同步必要的接线，不授权重写整个构造函数。

### C 类：原整项删除候选，结合旧版依赖重新审核

| 编号 | 函数与位置 | 当前职责和调用关系 | 本项内容的具体作用（执行前） | DiffAgent2 旧版证据与迁移判断 | 审核范围与建议 | 用户决定 |
| :----- | ---------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------- | ---- |
| C01    | `PendingAction.clear`，`core/action_gate.py:26`；所属类位于 `:12` | **职责与作用**：PendingAction 表示“准备发布的动作上下文”；clear 将其中的数据恢复默认值，避免上一次动作信息残留。该方法不发布动作，也不判定动作是否完成。**调用方与时机**：ActionGate.__init__ 创建 PendingAction 实例；engine 的全局停止/异常恢复调用 ActionGate.clear\_action\_state，再调用 pending\_action.clear。handle\_post\_action 的 REPLAN 分支另外清除两个重规划标记；测试会人工填入字段再检查清空。 | 字段含航点 waypoint、前向朝向 look\_forward、重规划命令/原因 replan\_cmd/replan\_reason、动作名和原始文本、指令类型、末端偏航及来源、远目标推进标记。以上是字段表达的数据含义；当前并无完整生产动作发布方读取这份对象。待决定的是是否保留整套上下文给后续动作接口，而不是是否删除动作完成判定。 | **动作上下文真实依赖**：VLA `_dispatch_waypoint`（`O/tools/vla/vla_skill.py:606`）和 FlightSkill（`O/tools/flight/flight_skill.py:84`）调用 arm\_action；`O/engine.py:1623` 写上下文；VLA `:487` 读 replan\_cmd 决定 REPLAN；`O/engine.py:574` 用 prompt\_raw 下发目标，`O/recording.py:35` 用它补任务文本。 | 不再建议整类删除，改为保留并等待字段级迁移审核。至少 replan\_cmd、prompt\_raw、action\_name、instruction\_type 存在旧版读取；部分其他字段只见定义/赋值/清理，不应因此把整个上下文一并删掉。技能领域内容最终归属仍按新版契约设计。 | 可以   |
| C02    | `ActionGate.handle_post_action`，`core/action_gate.py:98`   | **职责与作用**：根据动作所属技能返回的裁决执行后续调度：REPLAN 回分发并继续当前条目；ADVANCE 装载下一条、队空结束；IDLE 上报完成并回空闲；NEW\_ACTION 由技能已武装的新动作继续，核心不额外推进。**调用方与时机**：主循环确认动作完成后进入 POST\_ACTION，在该状态调用本函数；本函数先取得动作所属技能，调用其 on\_action\_result，再使用 ledger、queue 和 task\_phase 执行结果。                                             | 这里与 C01 相关的内容只有 REPLAN 分支对 pending\_action.replan\_cmd/replan\_reason 的清空。函数的四裁决执行和结果上报都有实际职责；即使决定删除 PendingAction，也不应连带删除本函数。                                            | **VLA 重规划收敛链**：`O/tools/vla/vla_skill.py:487` 读取 replan\_cmd 返回 REPLAN；`O/engine.py:1783` 在执行裁决后清标记，避免旧标记干扰下一动作。                                                                                                                                                    | 建议保留四裁决和当前清理步骤，等 VLA 动作上下文迁移设计完成再决定重规划标记归属。此处不是可以随手删掉的无效写入。                                                                                  | 可以   |
| C03    | `ActionGate.clear_action_state`，`core/action_gate.py:134`  | **职责与作用**：使当前动作失效：清待发布上下文，关闭进行中和完成标志，递增动作代次，清结果代次与结果数据，避免已停止动作的旧结果被当作新动作完成。**调用方与时机**：DispatcherEngine.\_enter\_global\_stop 在任务覆盖、取消、安全停/硬停时调用；\_recover\_inference\_after\_exception 在异常恢复时也调用。                                                                                     | pending\_action.clear 只是清理步骤之一。动作标志和代次/结果清理仍支撑停止与恢复；本项待审仅是 C01 获批后是否删除那一步上下文清空，不能把整个动作失效流程删掉。                                                                             | **动作生命周期清理链**：`O/engine.py:1596` 的 arm\_action 填充动作元数据；`:1561` 全局停止和 `:2067` 异常恢复清 pending\_action；VLA/飞行是其生产方。                                                                                                                                                     | 建议保留动作失效和上下文清理；C01 暂缓时本项不删除任何清理。后续若改数据归属，必须让新动作状态拥有对应的清理路径。                                                                                  | 可以   |

### D 类：连带调用点，不单独视作删除候选

| 编号 | 函数与位置 | 当前职责和调用关系 | 本项内容的具体作用（执行前） | DiffAgent2 旧版证据与迁移判断 | 审核范围与建议 | 用户决定 |
| :----- | ----------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------- | ---- |
| D01    | `ToolWorkflowHost.start_tool_workflow`，`core/tool_workflow.py:39` | **职责与作用**：接收执行侧的工具调用：检查技能是否注册、所需感知是否就绪；清理上一任务状态，激活当前调用并通知技能。同步技能直接执行，异步技能发布 planning 相位并装入任务队列。**调用方与时机**：ToolControlPlane.\_consume 消费 call 命令后经 ToolExecutor.execute 调用；接收 call 和 SkillCommand。通过 enter\_global\_stop 回调连接 engine 的停止入口。 | 接入新任务前调用 enter\_global\_stop("new\_tool\_call", shutdown\_program=False, publish\_hold=False)，作用是清本地执行状态，不退出程序、不发布急停。若 B03 批准，仅将这一个调用的参数名改正，行为与入队流程不变。 | **任务覆盖依赖**：`O/engine.py:1248` 的任务注入流程与 `:1073` 的覆盖入口相接；覆盖时同时关闭日志、停止事件记录与悬停发布。这些接线在新版被简化。            | 只作为依赖接线项保留；B03 暂缓则不改关键字。未来迁入 skill/记录服务时，还需联合 B01/B02 审核覆盖语义，不视为机械改名就能完成迁移。 | 可以   |
| D02    | `ToolWorkflowHost.cancel_tool_call`，`core/tool_workflow.py:67`    | **职责与作用**：取消指定调用：若它正是当前激活调用，通知技能 on\_cancel，清理本地执行状态并解除激活；绑定中间件时再让 runtime 记录取消结果。**调用方与时机**：ToolControlPlane.\_consume 消费 cancel 命令时直接调用；ToolExecutor.cancel 也定义了转调用入口，但当前控制面使用前者。调用关联依据是 call\_id。                                       | 当前停止调用显式传 shutdown\_program=False、publish\_hold=False，所以取消不会自动发急停。B03 批准后这里只同步关键字名，不能改成默认发布，也不改变 runtime 的取消收敛。                                        | **取消不隐含悬停发布**：`O/engine.py:991` 的取消路径显式传 publish\_hold=False；旧版停止函数在 True 时会实际发布悬停目标（`:1566`）。      | 保持现有取消行为；待 B03 的完整停止语义决定后才同步调用名，不把“未迁入悬停”理解为取消可以改用默认发布。                     | 可以   |
| D03    | `DispatcherEngine._run_inference_loop`，`engine.py:174`            | **职责与作用**：运行六态 FSM：等待输入或任务，取队首交给技能，等待动作完成，执行技能裁决，最后处理停止；任务发生异常时由外层守护入口负责恢复。**调用方与时机**：dispatcher\_node.start\_dispatcher\_workers 启动 run\_inference 线程；run\_inference 调用此循环，发生异常并完成恢复后会再次调用。                                               | DISPATCH 分支调用 skills.dispatch\_plan(cmd, skill\_command)，把队首交给路由器。若 B13 批准，只改成传 skill\_command；本地 cmd 仍用于 prompt\_parsed 等日志，不随调用参数删除。                 | **分发数据面可对照**：旧版 `_handle_plan_tool`（`O/engine.py:1400`）向技能 plan\_tick 传递 SkillCommand，cmd 没有参与技能解析。 | 仅随 B13 的审核结果同步调用签名；不影响未来技能接收 SkillCommand，也不删除记录/日志使用的任务文本。                 | 可以   |

控制面租约安全停当前使用 `shutdown_program=False`，不显式传 `publish_hold`，B03 不需要修改该调用。测试调整只随对应获批行为进行。

### E 类：独立行为修复，不捆绑到精简中

| 编号 | 函数与位置 | 当前职责和调用关系 | 本项内容的具体作用（执行前） | DiffAgent2 旧版证据与迁移判断 | 审核范围与建议 | 用户决定 |
| :----- | ------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------- | ---------------------------------- | ---- |
| E01    | `_run_inference_loop`，`engine.py:174` | **职责与作用**：运行六态 FSM：等待输入或任务，取队首交给技能，等待动作完成，执行技能裁决，最后处理停止；任务发生异常时由外层守护入口负责恢复。**调用方与时机**：dispatcher\_node.start\_dispatcher\_workers 启动 run\_inference 线程；run\_inference 调用此循环，发生异常并完成恢复后会再次调用。 | 循环最开始无条件设置 INIT。如果 \_enter\_global\_stop 已先设 STOP 并置 global\_stop\_active=True，循环又覆盖成 INIT，下一次尝试硬停可能被幂等守卫直接返回，无法走到 STOP 分支的 request\_shutdown。这是初始化与停止的时序冲突，不是某字段没有作用。 | **初始化/停止问题独立于技能迁移**：`O/engine.py:1855` 附近同样初始化 INIT，`:1533` 的硬停幂等守卫会提前返回；这是源码时序分析，不是本次运行旧版得出的端到端结论。 | 保留为独立待审修复，不因存在旧版而忽略，也不在本次文档核对中修代码。 | 可以   |

## 5. 本轮执行裁决与映射

| 条目 | 处置 | 说明 |
|----|----|----|
| A01–A06 | 保留 | 不搬迁协调函数 |
| B01/B02 | 保留 | 记录事件调用尚未接入，日志开关仍有效；在台账说明未迁原因、接入时机 |
| B03、D01/D02 | 保留 | 保留 publish_hold 名称并注明“急停悬停”；记录新版当前仅发布急停信号的缺口，不伪称完成悬停能力 |
| B04 | 执行 | 停止开关改为关键字专用，所有现有开关保留 |
| B05/B16 | 执行 | 删 first_image、last_plan_time 及对应写入；按用户批注删感知函数的首帧元数据残留，未迁入的 first_rgb/first_image_pub 不补造 |
| B06 | 执行 | 只删 ActionGate 未使用的四个回调，不删宿主状态/航点/帧 |
| B07 | 执行 | 只删队列两个未使用 getter，保留快照读取/写入回调 |
| B08/B10/B11 | 保留 | 保留 last_state、replan_content、previous_return_record_cursor 和实际写入；台账说明队列流转及返航恢复方式 |
| B09 | 执行 | 删 pre_prompt、prompt_bf、content 三份文本副本，保留两份结构化队列 |
| B12 | 执行 | 删 set_state 尾部无效 return 分支、纠正说明 |
| B13/D03 | 执行 | dispatch_plan 只传 SkillCommand，调用处同步 |
| B14/B15 | 保留 | 会话标签和 VLA 调试目录等待记录服务/VLA 迁移时重新决定归属 |
| C01–C03 | 保留 | 保留 PendingAction 及重规划标记清理、全局动作清理 |
| E01 | 执行 | 启动循环保留已经到达的 STOP；不扩展到其他时序重构 |

## 6. 本轮删除清单

- `engine.first_image`、`engine.last_plan_time` 及赋值；`perception/base_policy.py` 末端几何结果中的首帧元数据赋值块（原约 1769 行），不改计算与返回值。
- ActionGate 的 `host_state_get`、`host_state_set`、`waypoint_get`、`frame_get` 四组未使用入参与属性，以及 engine 对应接线。
- PromptQueue 的 `if_plan_get`、`last_state_get` 两组入参与属性；`pre_prompt`、`prompt_bf`、`content` 三份副本及维护代码。
- SkillRouter.dispatch_plan 的 `cmd` 参数；StateLedger.set_state 尾部不产生效果的 return 分支。

## 7. 实施步骤

### P0 — 按审核结论收紧

- 范围：§5/§6 代码与对应测试。
- 不变式：任务文本和 SkillCommand 同队列保留、返航快照仍写入、PendingAction 仍清理；取消不发急停，硬停不被 INIT 覆盖。
- 验收：核心与工具面测试、真实队列连续推进、位置快照、停止开关回归。
- 回退：仅恢复本轮差异，保留此前交付及用户文档。

### P1 — 保留项登记与读取入口

- 范围：rest 台账、AGENTS.md 入口、架构决策记录与本方案结果。
- 每项登记：当前所在对象、旧版生产/消费链、当前未完成部分、未来触发条件、建议接入点、验收、可删除条件、关联审核编号。
- 验收：链接有效、无主机特定信息、spec 基础检查；用户新增 log.spec.md 不改动。
- 回退：恢复本轮文档差异；不改写历史架构记录。

## 8. 验收标准

- [x] 核心与工具面测试通过，硬停启动时序、软停、快照写入及已保留动作上下文得到验证。
- [x] 删除项零残留、语法与 core 方法白名单通过。
- [x] rest 中每个保留项明确“何时重看、怎么接入、怎样验收、何时可删”。
- [x] AGENTS.md 入口与文档链接有效，文档只引用角色路径与仓库相对路径。
- [x] diff 空白检查与 spec 基础结构检查通过。

当前生产工具集合仍为空，本轮结束时飞行端到端不可运行；以后在真实 skill 和执行端口接入轮次恢复运行验收。本轮用真实核心和测试技能回归，不把保留字段当作已实现能力。

## 9. 风险与边界

| 风险                   | 处理方式                                   |
| -------------------- | -------------------------------------- |
| 把“新版无当前读取方”误判为“应该删除” | 必须补查旧版 skill 和共享服务；存在调用链时标记待迁依赖，再由用户决定 |
| 局部参数审批扩展成整函数删除       | 每项明确函数保留与内部调整范围                        |
| 将硬停修复夹带在清理中          | E01 单列，恢复原行为后等待单独决定                    |
| 删除上下文影响未来技能接线        | C01 明确列关联和契约影响，不预先删除                   |

## 10. 修改点清单

| 文件 | 动作 | 说明 |
|----|----|----|
| dispatcher/engine.py、core/action_gate.py、core/prompt_queue.py、core/state_ledger.py、core/skill_router.py | 修改 | 按审核编号收紧与 STOP 修复 |
| dispatcher/perception/base_policy.py | 修改 | 仅删首帧元数据残留块 |
| tests/core-boundary/test_core_boundary.py | 修改 | 接口与行为回归 |
| doc/l3-dispatcher-planner/rest/README.md | 新增 | 触发入口、状态索引与维护方式 |
| doc/l3-dispatcher-planner/rest/dispatcher-deferred-dependencies.md | 新增 | 保留项接入/删除台账和队列解释 |
| AGENTS.md | 修改 | 明确哪些任务必须读取 rest |
| 本方案及架构决策记录 | 更新/新增 | 执行证据与结构理由 |


执行结果：核心与工具面 **83 项测试通过**。运行命令：`uv run --isolated --no-project --python python3 --with pytest --with eclipse-zenoh --with pyyaml python -m pytest -q l3-dispatcher-planner/tests/core-boundary l3-dispatcher-planner/tests/tool-registry`。源码语法、删除/保留项、core 方法白名单、rest 链接/锚点及 `git diff --check` 检查通过。没有进行 ROS/实机悬停端到端验收。

交付入口：[rest 索引](../rest/README.md)、[保留项台账](../rest/dispatcher-deferred-dependencies.md)。结构理由归档至 `specs/implemented/architecture/2026-09-16-dispatcher-reviewed-tightening.md`。既有 `specs/implemented/inner/log.spec.md` 草稿未改动。工作区未提交或推送。

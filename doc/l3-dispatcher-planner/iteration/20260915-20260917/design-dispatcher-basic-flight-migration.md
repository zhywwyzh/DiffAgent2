# dispatcher 基础飞行迁移方案

> 摘要：以工作区 `l4-agent/` 的现有 RPC 调用为只读上游依据，在 DiffAgent2 新版
> 重建六个基础飞行技能。先完成通用 l4 对接闭环，再完成原点服务、执行缝和 ROS 接线，
> 最后将完整实现与测试一起纳入生产注册表。全过程不修改 l4，不恢复别名或任务编号。

## 0. 元信息

| 项 | 值 |
|---|---|
| 日期 | 2026-09-16 |
| 目标路径 | `l3-dispatcher-planner/ros_packages/dispatcher/`、对应测试与统一 `specs/` |
| 状态 | in-progress（职责上行修正，按用户要求不重跑测试） |
| 当前交付 | 六工具与 RPC 已迁入；正在撤回额外 planner 改动，修正后的控制链未重跑验证 |
| 执行总纲 | [执行顺序与文档导航](design-dispatcher-migration-execution-order.md)，统一阶段顺序与编辑入口 |
| 前置方案 | [l4 RPC 对接闭环](design-dispatcher-l4-rpc-integration.md)，实施验收先于生产飞行接入 |
| 目标契约 | [基础飞行动作提案](../../../specs/implemented/inner/flight-actions.spec.md)、[RPC 提案](../../../specs/implemented/inner/l3-l4-rpc.spec.md) |
| 现行依据 | [l3 根与全部叶契约](../../../specs/implemented/l3-dispatcher.spec.md)、[裁剪决策](../../../specs/implemented/architecture/2026-09-15-dispatcher-core-and-capability-pruning.md)、[保留项台账](../rest/dispatcher-deferred-dependencies.md) |
| 上游边界 | 工作区 `l4-agent/` 仅展示现有上层接口；所有阶段禁止修改其代码、配置、测试和文档 |
| 路径约定 | `L3/` = `l3-dispatcher-planner/ros_packages/dispatcher/`；`L4/` = `l4-agent/src/copaw/`；`O/` = DiffAgent2 旧版的 `drone_projects/l3-dispatcher-planner/ros_packages/dispatcher/dispatcher/`；spec/doc/tests 从仓库根起算 |

## 1. 背景与动机

DiffAgent2 新版已保留六态分发、调用账本、租约和 RPC，但生产工具集合为空。
迁移应利用骨架，以当前 l4 的真实调用为准恢复完整能力，不能重新引入 DiffAgent2 旧版
的编号、别名、engine 领域分支或 recording 私有调用链。

前次方案将“执行缝未接”解释为可生产注册占位工具，并假设现有快照可支持逐步返航，
不满足现行契约。本版改为明确的能力交付门：缺出口不注册，缺原点不返航，缺终态回传
先修对接。l4 对接的调查与修复范围归姊妹篇，本篇不重复建设协议层。

## 2. 现状事实（问题清单）

### 2.1 当前 l4 是上层接口依据

| 证据 | 事实与迁移影响 |
|---|---|
| `L4/agents/tools/plan_tools.json:4,16,28,51,68,80` | 六个基础动作均使用 basic_flight.*；直接成为新版唯一注册名 |
| `L4/agents/tools/plan_tools.json:28` | translate 的 direction 为四个水平机体方向，distance_m > 0，未知参数禁止 |
| `L4/agents/tools/plan_tools.json:51` | rotate 的 yaw_delta_deg 为数值，左正右负，没有旧版 ±360 schema 范围 |
| `L4/agents/tools/plan_tools.json:68` | return 明确为空参“返回起飞点”，没有 target/previous |
| `L4/station_sidecar/rpc_plane.py:166` | 调用参数平铺，只有 call_id/context 是传输字段；不发送任务编号 |
| `L4/station_sidecar/flight/rpc_bridge.py:227,246,319` | accepted 仅为准入；rpc_outcome.outcome 才驱动调用账本完成 |
| `L4/station_sidecar/flight/service.py:315` | 批次取消会另发空参 emergency_stop，飞行交付必须包含真实急停能力 |

这里只迁入上述六个公开能力。l4 中的 navigation 工具继续被新版拒绝；respond.answer
由站端处理，不迁入 dispatcher。保持方法名并不自动证明整体兼容，还须通过前置方案的
真实消费者与后续本方案的参数/物理语义验收。

### 2.2 新版事实与待接依赖

| 证据 | 事实与缺口 |
|---|---|
| `L3/dispatcher/tools/registry.py:35` | default() 为空；当前无生产飞行能力 |
| `l3-dispatcher-planner/tests/tool-registry/test_rpc_plane.py:21` | 22 个已删除名拒绝；本轮最终只解除其中六个 basic_flight 名的拒绝 |
| `L3/dispatcher/tools/skill_api.py:73` | SkillHost 仅声明飞行动作端口；声明不等于生产接线 |
| `L3/dispatcher/core/skill_router.py:20,49` | register 目前不返回 disposer；snapshot_owner 接线待动作发布轮次完成 |
| `L3/dispatcher/core/tool_workflow.py:43` | on_start 后按 synchronous 分流；不能用一个异步 flight 实例模糊承接同步起降 |
| `L3/dispatcher_node.py:54` | 组合根在包根目录负责构造；不在 dispatcher/ Python 模块目录内 |
| `L3/dispatcher/ros_adapter/core_channels_ros.py:23` | 仅有急停信号发布；没有实机悬停保证 |
| `l3-dispatcher-planner/ros_packages/planner/ego_planner/plan_manage/src/ego_replan_fsm.cpp:90,1285` | 存在 mandatory_stop 入口，但未证明与 dispatcher 默认急停主题相连 |
| `L3/dispatcher/core/prompt_queue.py:21`、台账 R04 | 游标与 last_state 等保留，但没有原点/历史集合消费者；单个快照不能替代返航服务 |
| `L3/dispatcher/core/action_gate.py:11`、台账 R05 | PendingAction 保留通用账务与待迁读取线索，不能整类删除或视为已接入 |
| `L3/dispatcher/utils/rpc_plane.py:250` | 快速终态关联窗口、owner watch 与重放缺口见前置方案，必须先修 |

本轮全 l3 检索 `/mission/task`、`takeoff_land` 没有执行实现命中；这说明不能假定
旧出口已迁入，旧 action 明确不再迁入。实际发送、完成、取消和 planner/飞控
直连链路由 S3 核验并确定接线。

### 2.3 DiffAgent2 旧版的借鉴与不迁项

旧版链路与行号沿用台账登记的 `1b5fef5` 快照，实施前按符号再次核对，不宣称本轮
重新检出了旧版全部文件：`O/tools/flight/flight_skill.py:84,132` 调动作武装和返航
目标解析；`O/recording.py:367,435,443` 消费历史、游标和位置快照；
`O/engine.py:1485,1566,1596` 包含悬停、停止与动作账务。

六动作领域语义可以重写使用；编号常量、wire→flight 别名、core 的 forward_* 分支、
技能直接读 host/recording 内部对象不迁入。历史/原点功能有真实旧版消费者，不能写成
“无调用方删除”；本轮只实现当前 l4 所需原点，逐步历史返航继续明确保留。

## 3. 目标与约束

- 目标：六个 basic_flight 调用经现有 l4 信封到技能、执行侧和唯一终态，具备可验证的
  起飞、降落、平移、旋转、返回起飞点、急停能力。
- 非目标：不修改 l4；不迁 navigation/VLA/grasp；不迁完整 RecordingService、停止
  持久记录、日志上行、多图调试；不开放 previous 返航；不重写 planner 算法。
- 硬边界：按原名分发，无编号、别名、转接器、旧入口垫片；core 无技能 import、无
  领域端点；ROS 收发只在适配文件；领域状态推进不能藏入 ros_adapter 或组合根。
- 生产注册必须有完整实现和测试。下游尚未接入不是 migration-protocol §2-⑦ 的
  “上游未实现”；不得借技能占位例外开放生产工具。
- 现行空集合与 revision 保持到最终交付；目标契约先为 proposed，采纳与实现同步。
- 所有保留项只按真实消费者处置，不因本轮缩小能力范围删除 R01–R07。

## 4. 方案决策

### 4.1 唯一名字与参数

固定采用 `basic_flight.*`，删除原方案 A/B 选择，不设 `flight.*` 别名。
业务 schema 逐项对应当前 l4；return 只接受 `{}` 并在技能内部表达 origin 语义，
RPC 不补 target；rotate 不照搬旧范围，不把请求角度取模成另一个动作。

| 注册名 | 技能类型 | synchronous | requires_perception | completion |
|---|---|---|---|---|
| basic_flight.takeoff | TakeoffSkill | true | false | forwarded |
| basic_flight.land | LandSkill | true | false | forwarded |
| basic_flight.translate | TranslateSkill | false | false | action_result |
| basic_flight.rotate | RotateSkill | false | false | action_result |
| basic_flight.return | ReturnSkill | false | false | action_result |
| basic_flight.emergency_stop | EmergencyStopSkill | true | false | forwarded |

每个类型声明自己的完整 name；六个独立实例，共用服务不互相调用。
同步能力在 on_start 通过端口完成出站或报告失败；异步能力进入队列和动作完成门。
未覆写钩子使用 SkillBase 默认实现，不为凑九个钩子复制空方法。

### 4.2 确定的目标目录与命名

```text
l3-dispatcher-planner/ros_packages/dispatcher/
  dispatcher_node.py                # 仅装配与进程生命周期
  dispatcher/
    tools/
      registry.py
      skill_api.py
      flight/
        __init__.py
        ports.py                   # 能力端口和自有数据结构
        takeoff_skill.py
        land_skill.py
        translate_skill.py
        rotate_skill.py
        return_skill.py
        emergency_stop_skill.py
    services/
      flight_session.py            # 起飞原点与物理会话的唯一所有者
    execution/
      skill_host.py                # 通用宿主端口实现，不桥接旧 host 属性
      waypoint_execution.py        # 共享执行状态推进、完成与取消
      ports.py                     # planner/飞控出入站抽象
    ros_adapter/
      flight_commands_ros.py       # 起降命令翻译与发布
      flight_state_ros.py          # 新鲜的位姿/飞控状态快照
      # 不建立 mission action 客户端、服务端或兼容入口
      planner_execution_ros.py     # planner 通信与结果翻译
    core/skill_router.py            # 按名注册和资源释放，不感知 flight
```

| 类型 | 规范 | 示例 |
|---|---|---|
| Python 文件、函数 | snake_case；一个动作一个 *_skill.py | translate_skill.py |
| 类型 | PascalCase | FlightSession、WaypointExecution |
| 注册名 | 与 l4 的完整方法名一致 | basic_flight.return |
| ROS 文件 | *_ros.py，集中通信 | flight_commands_ros.py |
| 测试 | test_行为，放对应 tests 子目录 | test_return_without_origin_fails |
| 单位/协议字段 | 保持 l4 字段名；内部值注释明确坐标与单位 | distance_m、yaw_delta_deg |

不另建 skills/flight 平行树。低密度执行编排使用 Python；本轮无新增 C++/pybind，
如后来确需几何计算迁移，先另补归属与门禁，不能顺带改 planner。

### 4.3 宿主与能力端口

组合根只创建并注入 SkillHost 实现、FlightSession、执行缝和 ROS 端口；不在
create_dispatcher_engine 中实现 arm_action 的流程或飞行判断。
通用账务归 execution/skill_host.py，复用现有 ActionGate/StateLedger 的唯一状态，
不新增 engine 的旧属性转接器、property 别名或第二份 action 状态。

| 接口 | 归属与行为 |
|---|---|
| arm_action / snapshot_owner / 代次守卫 | 通用账务绑定实际技能实例并进入等待态；武装失败不发送目标 |
| send_task_goal / publish_mode_burst | SkillHost 通用出站；技能负责限幅、偏航和模式脉冲意图，适配层仅翻译 |
| flight_state_snapshot() | 能力端口返回完整的位姿、坐标系、飞控状态和时间戳；无 ROS 类型 |
| request_takeoff() / request_land() | 能力端口发送真实起降命令，明确转交失败，不使用 core 发布器 |
| cancel_execution() / request_safety_stop() | 通用下游取消与安全停止；前者不隐含急停，后者供技能和租约安全流程共享 |
| origin_snapshot() | FlightSession 经只读端口提供已确认原点，缺失则失败 |
| 相位、失败终止、结果暂存、队列操作 | 沿用 SkillHost 生命周期接口，禁止技能直接操作 ledger/queue |

上述新增能力端口的分组、签名和白名单须在 P0 对 l3-skill-contract 的修订中先采纳，
并同步 SkillHost/能力 Protocol 的参考实现；不是只加一个 Python 方法就视为契约齐备。
frame/图像读取等现有端口按真实宿主来源注入，不为本轮制造无消费者的模拟数据。

core 六态和领域禁令不变。register 返回 disposer 需要实改 skill_router，并明确
register.dispose 的通用释放闭包；若 G2 当前禁止该 def，先把该闭包加入方法白名单，
同时更新门禁。不得承诺“白名单一行不改”后通过动态挂方法规避检查。
其他新增 core 方法必须逐项论证并先改契约，不借迁移放宽整体白名单。

### 4.4 dispatcher 直连 planner 与动作结果

架构已由用户确定并写入现行执行缝契约：dispatcher 持有任务 FSM，经通用执行端口
和 ROS 适配层直接向 planner 下发动作；不迁入 `/mission/task`、mission_executive
包、旧 mission FSM 或其客户端/服务端。S3 不再评审是否保留这个中间转换层。

S3 只核实直连的具体接口：planner 输入与反馈消息、坐标系、单位、完成与失败判据、
取消/覆盖/急停机制、起降与飞控状态来源、构建依赖和 launch/remap。将每项的生产方、
消费方、失败行为和测试证据写成接线矩阵；缺少反馈/取消机制时明确补设计，不借道
旧 mission action。未解析消息符号或缺部署来源时不得进入对应代码实现。

任务 FSM 仍归 core；目标构造和专属完成门归技能；通用动作账务、代次与反馈关联归
execution 模块；ROS 发布/订阅归 ros_adapter。dispatcher 直连不等于 engine 直接
发布领域主题，也不新增第二套任务状态机。`action_result` 是动作完成语义，不要求
ROS action 服务；真实 planner/飞控反馈经端口形成执行结果，不能将发布成功当作完成。

共享执行只识别航点/动作意图，不分支识别 basic_flight 名字。成功/失败结果带动作
代次回到宿主，晚到结果被拒绝；技能完成门处理能力专属条件，再由四裁决推进。
取消必须实际取消旧 goal 并阻止旧轨迹继续，不能只清队列。ROS 回调不推进业务 FSM。

平移采用新鲜机体水平朝向转换到目标坐标系；旋转保留累计角，分段目标不大于 90 度，
通过方向一致的解缠偏航累计验证，不用单个归一化 yaw 目标把整圈旋转消掉。
可执行预算在部署配置和测试中冻结，超预算明确失败，不静默截断。位姿过期、控制模式
不符、下游不可用、结果超时均失败；requires_perception=false 不豁免这些条件。

### 4.4.1 S3 旧版接线取证（2026-09-17）

用户确定：当前实际后端为 EGO；本轮交付到 cmd 输出，cmd 之后的飞控/实机处理不属于
任务范围。DiffAgent2 旧版只读编排快照为 `7192811`；以下路径均相对旧版编排仓库。

| 项目 | 旧版来源与事实 | 新版迁移裁决 |
|---|---|---|
| 后端切换 | drone_projects/l3-dispatcher-planner/bringup/launch/bringup_base.launch：planner_backend 条件包含 ego/super/diff；外层 bringup.launch 默认 super，内层默认 ego | 以用户指定 ego 为当前验收后端，不把旧文件默认值当现场事实；保留配置选择职责，其他后端逐项验收，不宣传能力完全等价 |
| EGO 接线 | 同目录 includes/ego_planner.launch.xml：~local_goal → /drone_<id>_mission_executive/local_goal；~mandatory_stop → /mandatory_stop_to_planner；/position_cmd → /setpoint_cmd | 改为 dispatcher 直连；旧主题命名不构成保留 mission 节点的理由；新 remap 作为有意变更登记 |
| waypoint 消息 | ros_packages/utils/quadrotor_msgs/msg/LocalGoalSet.msg：drone_id、batch_id、扁平 xyz、yaw、look_forward、yaw_mode/yaw_path_mode 等 | batch_id 仅关联下游动作代次，不映射工具名；旧 source_task_id 与来源编号常量须单独按无编号契约清理，不能原样复制 |
| 完成关联 | 同包 WaypointProgress.msg：batch_id、consumed_count、active_idx、skipped_mask、all_consumed | 只接受当前动作批次的反馈；不能用无关联编号的 Bool 完成脉冲结束新调用 |
| 规划结果 | 同包 PlannerResult.msg 只有 planner_goal、plan_times、plan_status、modify_status；没有 exec_finished 字段 | 不依据陈旧注释臆造字段；无批次关联结果不能单独作为唯一终态依据 |
| cmd 输出 | 同包 PositionCommand.msg；新版 EGO traj_server.cpp:274 构造 position/velocity/acceleration/jerk/yaw/yaw_dot；旧 launch remap 为 /setpoint_cmd | 保持 cmd 消息字段；验收观察此输出，不运行 cmd 后的消费者 |
| 起降出口 | 同包 TakeoffLand.msg：TAKEOFF=1、LAND=2，takeoff_land_cmd | 转交出口单独验证，不把下游起降物理完成纳入本轮范围 |
| 第二层旧转接 | includes/mission_backend.xml 还启动 quadrotor_msgs/scripts/planner_waypoint_action.py，转发 /planner/waypoints | 不迁入此转发节点、TaskAction/Waypoint action 或 mission_backend；只迁真实消息/公共依赖 |
| 后端差异 | 新版 DIFF waypointCallback 明确不使用 yaw；SUPER 的部分完成主题仍含旧 mission 命名 | 配置能切换不等于六能力一致；EGO 为本轮完整六动作目标，其他后端能力差异明确拒绝，不通过兼容转发补齐 |

后续实现验收的输入可用受控 odometry/cloud 与反馈；输出边界为 `/setpoint_cmd` 和起降
命令转交。需要验证命令生成、当前批次结果、取消覆盖和急停后的保持命令，不要求验证
cmd 下游的电机、PX4 跟踪或实机速度收敛。原点的状态输入仍要真实可判定，不能把发布
起飞命令伪报为实际升空；状态变化可由受控输入驱动。

### 4.4.2 职责上行修正（取代先前的 EGO 专属取消设计）

用户明确：仅删除 source_task_id 与 SOURCE_TASK_*；yaw_low_speed 和 goal_to_follower
保留。取消 mission_executive 是把其控制职责上行迁入 dispatcher，不是给 planner
增加新控制协议。此前删除另外两个字段以及增加 EGO cancelCallback 的决定撤回。

修正先于代码执行落盘，范围如下：

| 单元 | 修正动作 | 理由 |
|---|---|---|
| LocalGoalSet.msg | 恢复 yaw_low_speed、goal_to_follower 原字段位置；不恢复来源编号 | 不把 task-id 清理扩大成其他接口裁剪 |
| EGO/SUPER | 恢复 yaw_low_speed 的原读取；仅保留来源编号相关差异 | 后端行为保持原有边界 |
| EGO 取消/停止 | 撤销 cancel 订阅/回调、额外清窗口和偏航重置 | 取消覆盖与生命周期由 dispatcher 承担 |
| vis_utils | 保持旧目录布局：include/vis_utils/camera_fov.h 和 src/camera_fov.cpp，CMake 引用原 src 路径 | 不移动既有文件、不改 planner include、不加转接头 |
| WaypointExecution | 上行承接旧 MissionCore.stopMotion：新批次下发当前位置、当前 yaw、look_forward=false | 使用既有统一目标消息覆盖旧动作，不要求新增 planner/cancel |
| ROS 端口与 launch | 删除 UInt32 cancel 发布器、协议方法和 remap | 只保留既有目标/反馈/全局停止语义 |
| 现有测试文件 | 仅同步已变更接口的已有断言，不新增/执行测试 | 不让测试继续要求已撤销的 EGO 专属端口 |

旧版依据：MissionCore::stopMotion（mission_core.cpp:277）调用 publishLocalGoal，
handlers/mission_core_shared.cpp:9–18 将其作为新批次单点窗口下发。这里只迁入职责，
不恢复旧包、旧 action 或任务编号。

dispatcher 的取消序列：标记取消处理中 → 校验新鲜位姿 → 推进执行批次 → 经同一个
目标发布口发送保持意图 → 清除旧活动动作。保持批次不参与被取消调用的成功判定，
旧批次结果不能推进新调用。位姿缺失/过期或发送失败时保留取消待处理状态、阻止新
动作，不假装已经停止；恢复连接/位姿后可重试。批次不映射工具身份。

显式急停保留既有全局停止信号，并由 dispatcher 通过同一目标接口下发保持意图，
不再通过修改 planner 的急停函数实现。转交成功不等于已验证实际停止。

此修正不证明三个后端行为完全等价，也不增加 EGO 专属要求。原来的 115 项通过记录
属于修正前实现，不能当作当前版本证据；本轮按用户要求不运行测试或构建。

### 4.5 原点服务与 R04 范围

本轮实现 FlightSession 的有效原点，不迁完整 recording，不实现 previous 游标消费。
原点来自起飞前确认在地面的完整快照；起飞命令成功转交后仍仅是候选值，收到真实
起飞确认才提交。飞行中重复起飞不得覆盖原点；着陆结束会话，新起飞重新采样。
覆盖、取消、急停不清同次飞行原点；重启、仿真重置或坐标重置使其失效。

return 无原点明确失败；不读 last_state 当原点、不用当前点补造、不访问
host.ledger/host.prompt_queue。不自动降落；返回原点水平位置的飞行高度经配置约束
校验。会话状态由服务单点写入，快照不可变且有新鲜度/连续性证据。

R04 只能标为“原点子能力接入，历史/文本部分继续保留”；连续两次 previous 的验收
移出本轮，但其触发条件不删除。R06 运行日志 session_tag 不等于飞行会话身份。

### 4.6 急停 R03 与动作账务 R05

R03 按实际所用 planner 验证 `/command/emergency_stop`→停止入口→制动轨迹→飞控
跟踪→位置保持。先验证再决定是否需要独立 hover goal；不同时发送互相覆盖的目标。
forwarded 表示请求已转交，完整能力交付另须运动中制动和保持证据。覆盖/普通取消
publish_hold=false 不发布急停；租约丢失通过核心安全端口调用同一执行能力。

R05 激活动作武装、发布实例归属、代次、结果和清理。保留字段逐项核对：本轮只接
真实飞行消费者，不因 VLA 尚未迁入删除 replan_cmd 等待迁依赖，不虚称 VLA 重规划
已验证。通用 REPLAN 机制可由测试技能回归，生产 VLA 判据继续登记待迁。

### 4.7 注册、终态与资源逆操作

六项完整交付后统一加入 ToolRegistry.default()；若出口不齐，继续为空，不停在
“生产占位”状态。测试使用私有注册表，从不改生产开关。元数据与 schema 单源，
revision 由最终元数据的 canonical JSON 计算，不在纯 spec 阶段预填未来值。

同步起降与急停只有真实转交后才 done；异步三动作以真实 action_result 和完成门
判定。l4 会在 forwarded 后推进下一步，后续技能必须检查飞行状态，不能假设已飞稳。
不能为保持批次顺畅把等待、超时或不可执行冒充成功。

每次 register 返回 disposer，宿主保管并在反注册/停止调用；释放顺序与获取相反。
活动动作先取消并使代次失效，再释放相关资源；异步清理等待完成。共享服务的 disposer
由装配根持有，不能被一个技能反注册时连带关闭其他技能。

## 5. 迁移映射表

| 旧/现有单元 | 新归属 | 裁决与动作 |
|---|---|---|
| 旧版六 flight ToolSpec 和 wire 别名 | tools/registry.py 六 basic_flight ToolSpec | rewrite；直接原名，编号/别名不迁 |
| 旧 FlightSkill 多动作实例 | tools/flight/ 六技能 | rewrite；逐名身份与同步性，共享能力由服务持有 |
| 旧 engine 起降分支 | takeoff/land 技能 + flight_commands_ros | rewrite；领域判断离开 core，收发隔离 |
| 旧返航解析依赖 | services/flight_session.py + ReturnSkill | rewrite origin 子能力；历史依赖继续保留 |
| 旧 arm_action 和动作结果接线 | execution/skill_host.py + 现有 ActionGate | merge/rewrite 通用账务，禁止旧属性桥接 |
| 原 mission_executive 共享执行 | execution/ + 经 S3 核实的 planner 直连端口 | rewrite；不恢复旧包或 mission action 中间层 |
| 旧悬停辅助与现有急停信号 | 执行缝停止能力 + ROS 端口 | 按 R03 验证后 rewrite，不机械双发 |
| 现有 SkillRouter.register | 原通用模块 | rewrite 返回 disposer，不导入任何技能 |
| REMOVED_NAMES 中 basic_flight 六项 | 正向能力与错误参数测试 | 替换；flight.* 六项仍拒绝 |
| l4 RPC 与工具文件 | 原地只读 | 不迁移、不修改；用于接口核对 |

每个迁入符号在实施时补“真实调用方→归属→测试”证据。未获得调用方证据的旧模块不搬；
当前登记明确保留的依赖按台账逐项处理，不以新版无引用裁掉。

## 6. 删除清单

| 项 | 处置与理由 |
|---|---|
| 旧 task_id 常量、编号解析和映射 | 不迁入新版；不删除 call_id 关联能力 |
| _WIRE_ALIASES、return 默认字段注入 | 不迁入；原始 basic_flight 名与空参语义直达技能 |
| core 的旧 forward_* / FlightSkill 领域分支 | 不迁入，按名技能化替代 |
| 旧技能访问 host 私有状态/recording 的链路 | 不迁入，显式端口和原点服务替代本轮所需部分 |
| 六 basic_flight 已删除名拒绝测试 | 最终交付时替换成正向/负向参数用例；其余 16 个拒绝锚定保留 |
| 被新实现实际替代的新版片段 | 同批删除，不留空方法、注释桩、旧接口开关 |

不删除 DiffAgent2 旧版/l4 内容，不删除 R04 的历史游标和文本回退，不因本轮不迁 VLA
而删除 R05 标记，不修改既有冻结架构决策。RPC 重复关联的处置归前置方案。

## 7. 实施步骤

### P0 — 契约与执行接口取证

- 范围：当前两份提案；按总纲 S3 核实 planner 直连接口，补全 planner/飞控字段与部署接线矩阵，采纳必要
  的技能端口及 core disposer 白名单修订。l4 前置方案按其顺序独立完成。
- 不变式：生产仍为空；未交付行为保留 proposed；不预填未来 revision。
- 验收：根/叶归属、schema 对比、真实下游字段和取消语义可核对；没有未解析消息类型。
- 回退：撤销本轮提案增量，不动现行生产事实。

### P1 — 宿主、原点服务和资源生命周期

- 范围：SkillHost 实现、能力端口、FlightSession、register disposer，测试能力验证接线。
- 不变式：无生产注册；状态单一所有者、core 无领域依赖；没有旧接口转接器。
- 验收：原点候选/确认/失效，代次与实例归属，四裁决、资源逆操作、G1–G9/G13–G17。
- 回退：整批撤销服务/端口接线和对应契约修订，不能留下空端口冒充实现。

### P2 — 执行缝与六技能实现（测试注册表）

- 范围：dispatcher 直连 planner 的执行端口、planner/飞控端口、六技能、真实取消和停止链。
- 不变式：生产 default 仍为空；技能就绪或出口缺失明确失败；共享执行不识别工具名。
- 验收：领域单测与模拟下游成功/失败/超时；六技能参数一致；G10/G11；没有新增 pybind
  时 G12 不适用并注明，不声称做了 C++ 新能力验收。
- 回退：撤销未完整交付的新实现；不开放占位工具。

### P3 — l4 消费者与受控飞行链验收

- 前置：l4 RPC 对接方案已通过；直连端口和消息定义、launch/remap、执行配置已冻结。
- 范围：用测试注册表连接真实站端消费者进行隔离测试；受控 odometry/cloud/反馈驱动真实 planner，验证
  出站、结果与急停 cmd，交付止于 /setpoint_cmd，不测试后续处理。
- 不变式：不修改 l4；只在受控环境使测试能力可达，不形成生产开关；forwarded 不是飞稳。
- 验收：§8 全矩阵；R03/R04/R05 对应能力的运行证据；不能以 mock planner 替代真实 planner 的 cmd 输出验证。
- 回退：保持生产空集；解除测试会话并完成下游安全清理。

### P4 — 生产注册、契约采纳与归档（同一交付）

- 范围：六 ToolSpec 默认注册、完整实现与测试、最终 revision；flight 提案整叶晋升，
  l3 根表追加条目，tool-plane §1/§9/G24 更新；同步 rest 台账和索引。
- 不变式：已实现、已测试的集合恰等于生产集合；旧 flight 名仍拒绝；恰一个终态。
- 验收：全部适用门禁及 §8 全绿，补新架构决策记录，方案方可置 done。
- 回退：注册表/测试/spec/revision 整体回到空集基线，保留归档证据，不保留占位入口。

P1/P2 中间状态明确“真实生产飞行不可运行”，预期 P3 验证并由 P4 正式交付。
2026-09-17：本方案 P0–P4 已完成，执行证据见 §11；下述测试矩阵为本轮交付判据。

## 8. 验收标准

| 范围 | 明确用例与判据 |
|---|---|
| 前置协议 | RPC1–RPC7 通过；真实 l4 消费 admission/outcome；租约重放与即时终态回归 |
| 名字与参数 | 六 basic_flight 名正向通过；六 flight 名及其余已删名拒绝；return 的 target 参数拒绝 |
| schema | direction 四值、距离正数、未知键/缺键/布尔/NaN/Infinity 负例；rotate 零值、负值、跨圈及超预算明确结果 |
| 同步动作 | 起降/急停真实转交才 forwarded；端口缺失、下游不就绪/抛错不假成功 |
| 位姿 | 缺失、过期、坐标系变化拒绝；平移四方向、单位、限幅与目标一致；旋转不丢圈数 |
| action 结果 | 成功门、失败、超时、重复、旧代次、取消后迟到；同名技能重注册不改变归属 |
| R03 | 急停 remap 连通、运动输入下的制动/保持 cmd 输出、旧 goal 停止、重复急停、定位不可用、模式切换/恢复 |
| R04 原点 | 起飞候选与真实确认、无原点失败、空中重复起飞不覆盖、着陆/重置/重启/坐标变更失效、任务覆盖不清同会话原点 |
| R05 | 武装后结果接线、覆盖/停止清理、实例快照与代次；REPLAN 机制用测试技能验证，VLA 生产判据仍未交付 |
| 生命周期 | 取消/覆盖不误发急停，旧目标确实取消；技能/共享服务资源归属正确、disposer 逆序且等待异步完成 |
| 控制面 | 同源抢占、非 owner 含急停拒绝、失租约端口失败 fail-closed；终态唯一与 completion 元数据一致 |
| 集成 | takeoff → 实际飞行就绪 → translate/rotate/return → emergency_stop → land；分别记录协议、执行反馈和 cmd 输出证据 |
| 交付 | default 六项与 spec 一致、revision 可复算；rest 索引同步；旧代码零遗留；G18–G28 与行为字符串差异登记一致 |

代码轮次在已安装测试依赖的环境、仓库根执行：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider l3-dispatcher-planner/tests/tool-registry l3-dispatcher-planner/tests/core-boundary l3-dispatcher-planner/tests/basic-flight
```

`tests/basic-flight/` 已交付；真实 ROS 集成另见 tests/ros/test_ego_cmd.py。planner 直连接口/launch 集成与 cmd 输出验证另附运行记录；spec 工具未迁入前用现有
pytest 与 header/Parent/引用闭包等价检查。当前文档轮次的测试限制见前置方案 §8。

## 9. 风险与对策

| 风险 | 影响 | 对策 |
|---|---|---|
| 预设旧 mission action，或直连却缺完成/取消机制 | 多余层级或执行链不完整 | S3 核实直连接口的完整执行语义；禁止恢复旧转换层 |
| 起飞 forwarded 被当成已升空 | 紧接平移不可执行 | 检查真实飞行状态；明确失败，不能靠 ack 推断飞稳 |
| 空参 return 被扩大为 previous | 上游与历史服务范围失控 | 本轮只做 origin；R04 剩余条目继续保留 |
| 原点从 last_state/当前点补造 | 飞往错误位置 | 独立 FlightSession，确认起飞才生效、无记录明确失败 |
| rotate 套用旧角度范围或直接取模 | 上层合法意图被改变 | 有符号累计角、分段与解缠判定；超预算失败 |
| 停止信号与 planner 入口未接 | 急停没有生成正确 cmd | 实际 remap、制动轨迹/保持 cmd 证据；不盲目双发 hover |
| 为保持 core 白名单把业务塞入组合根 | 结构形式合规但职责失控 | 通用宿主/执行领域模块明确归属，必要白名单先修订 |
| 非本轮消费者被误删 | 后续 VLA/记录迁移受损 | R01–R07 逐项保留，关闭必须附替代与验收证据 |
| 只跑 fake 单测就注册生产 | 假能力重新进入发现面 | P3 验收是 P4 硬前置，不提供生产占位路线 |

## 10. 修改点清单汇总

| 文件 | 动作 | 时机 |
|---|---|---|
| 本方案、l4 RPC 姊妹方案 | 重写/新增 | 当前文档轮次 |
| specs/implemented/inner/flight-actions.spec.md、l3-l4-rpc.spec.md | 新增目标契约，不改现行空集 | 当前文档轮次 |
| rest/dispatcher-deferred-dependencies.md、rest/README.md | 登记两方案与剩余触发条件 | 当前文档轮次；实现后再更新证据 |
| specs/implemented/inner/l3-execution-seam.spec.md、对应直连架构决策 | 本轮已明确退役 mission/task；后续只细化直连接口 | 当前文档轮次 |
| specs/implemented/inner/l3-skill-contract.spec.md | 先采纳新增端口及资源释放接口 | P0，实施前 |
| specs/implemented/inner/l3-core-boundary.spec.md | 精确登记 disposer 闭包等必要方法 | P0，确需变更才改 |
| L3/dispatcher/tools/skill_api.py、tools/flight/ | 端口与六技能 | P1/P2 |
| L3/dispatcher/services/flight_session.py | 原点及会话服务 | P1 |
| L3/dispatcher/execution/、ros_adapter/ 对应文件 | 共享执行与planner 直连 ROS 接线 | P1/P2 |
| L3/dispatcher/core/skill_router.py、L3/dispatcher_node.py | disposer 与装配 | P1/P2 |
| dispatcher 包构建/启动配置（待 P0 确定路径） | 当前包目录无 package.xml/CMakeLists.txt；P0 决定并记录消息/action 依赖的实际构建归属和启动 remap，不能假设现成 catkin 包 | P0 定义、P2 新增/修改 |
| l3-dispatcher-planner/tests/basic-flight/、tests/tool-registry/、tests/core-boundary/ | 领域、协议、边界与集成测试 | P1–P3 |
| L3/dispatcher/tools/registry.py | 生产默认注册六项与完整元数据 | P4 |
| specs/implemented/inner/flight-actions.spec.md、l3 根表、l3-tool-plane.spec.md | 整叶晋升、集合/revision 同批更新 | P4 |
| specs/implemented/architecture/日期-dispatcher-basic-flight.md | 完成时归档新决策，不覆盖旧决策 | P4 |

上表为实施范围记录，具体落地和差异见 §11。`l4-agent/**` 未修改；本轮没有提交、
推送或现场部署动作。

修正前曾在 S5 增加 EGO 急停清窗口和偏航重置；这些改动现已撤回。停止意图的
构造上行到 dispatcher，不把后端算法修复混入本轮迁移。

S4 并发细化：RPC 消费线程与 FSM 线程共用生命周期锁，串行化准入、取消、停止和
单次 FSM 处理；等待释放锁。否则旧动作 poll 与新调用覆盖可交叉写入同一 ActionGate。
该通用同步机制不新增领域分支，先登记 core 的等待辅助方法白名单再实现。

消息闭包复核纠正：此前按无读点/旧回退理由删除 goal_to_follower、yaw_low_speed
超出了本轮范围；现已恢复字段和原读取，仅删除来源任务编号。PositionCommand 不变。

## 11. 完成记录（2026-09-17）

本节是职责修正前的实现与验收历史。当前控制链以 §4.4.2 和新的边界修正决策为准；
下述 115 项结果不覆盖本次未重跑测试的代码。

- P0/S3：直连消息与接线冻结；移除 LocalGoalSet 的来源任务编号、无消费者字段和旧
  yaw 回退；只迁七种 quadrotor 消息、两种轨迹消息、轨迹转换头及 camera_fov。
  未迁入 mission/task、planner/waypoints action、旧转换节点或 mission_executive 包。
- P1/P2：六个独立技能、FlightHost/FlightPorts、FlightSession、WaypointExecution、
  ROS 适配与正式装配入口已实现。共享生命周期锁串行化准入/取消/FSM，等待期间释放；
  注册返回 disposer，旧实例释放不删除新实例；结果只接受当前批次。
- 原点以显式 ground_z 和新鲜 odometry 确认；未知地面、无有效原点、过期/错误坐标系
  输入均失败。时钟/坐标重置和输入失效使原点失效；普通任务覆盖不清同次飞行原点。
- P3：真实 EGO 在隔离 ROS master、受控 odometry/cloud 下生成 cmd。验证旋转、
  平移、取消保持和急停；六个实际技能经真实 FSM 验证，再以正式 basic_flight.launch
  启动 dispatcher，经只读 l4 fleet/bridge 通过真实 Zenoh 调用六工具并接收 outcome。
  测试不运行 cmd 下游飞控或电机。
- 生产入口复验修复了 headless 仍强制要求视觉 pointcloud 配置的问题；headless
  不创建视觉模块、不读取其必填配置，视觉启用路径仍保留原校验。
- P4：默认集合为六个 basic_flight 工具；flight 旧名及其余删除名保持拒绝。
  revision 为 `sha256:39102fa2e900df83c2d4a6d9fd1e795a384f133dc00de6d0fb3946fc69aa1685`，
  与现行工具面契约和测试一致。动作叶已晋升并挂根表。
- 构建：tools/build_ego.sh 创建外部 catkin 构建目录，EGO、dispatcher 与最小依赖
  全部构建通过。完整测试为 115 passed；11 条警告来自 rospy 的 notifyAll 弃用调用，
  没有测试失败。运行与复现步骤见 l3-dispatcher-planner/README.md。

最终文件与原计划的细化：共享生命周期复用放 services/flight_motion.py；端口、元数据
和组合分别放 tools/flight/ports.py、catalog.py、execution/composition.py；ROS 出站和
快照统一在 planner_execution_ros.py；不预建无独立职责的多个 ROS 文件。新增 catkin
包定义、构建脚本、EGO 参数和两份 launch，不复制旧 bringup 的场景图/bridge/mission。

保留边界：R03 已接入至 cmd；R04 只实现 origin，previous/history/text 依赖继续保留；
R05 飞行动作账务已接入，VLA 专属重规划/记录消费未交付。当前只验收 EGO；SUPER
仅同步清理被删除字段读取，未声明其他后端具备完整六能力或直接取消协议。

camera_fov 目录纠正：按用户要求，将实现文件从新增的 ros_adapter/ 移回旧布局的
src/camera_fov.cpp，同步 CMake；保留实现内容和公开头文件。此项仅恢复路径，
不改变逻辑，不运行测试或构建。

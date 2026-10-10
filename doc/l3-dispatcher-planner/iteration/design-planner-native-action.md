# planner 原生 ROS action 迁移方案

> 摘要：将 dispatcher 与 planner 之间的目标、进度、结果和取消统一为 ROS1 actionlib 生命周期，由 planner 进程中的执行领域组件负责到达原目标、连续停稳及取消停止。技能继续拥有多段任务编排。替换现有 topic 协议和两家族重复执行账务，不增加协议桥接节点。本文件为设计过程材料；接口与职责权威位于 `specs/`。

## 0. 元信息

| 项 | 值 |
|----|----|
| 日期 | 2026-10-09 |
| 目标路径 | `l3-dispatcher-planner/ros_packages/dispatcher/`、`ros_packages/planner/`、`ros_packages/utils/quadrotor_msgs/`、`bringup/` |
| 状态 | 代码已交付，待验收（未编译、未运行） |
| 关联文档 | [任务结果收敛方案](design-flight-vla-result-convergence.md)、[执行缝契约](../../../specs/implemented/inner/l3-execution-seam.spec.md)、[技能契约](../../../specs/implemented/inner/l3-skill-contract.spec.md)、[待迁依赖台账](../rest/dispatcher-deferred-dependencies.md) |

## 1. 背景与动机

DiffAgent2 新版当前通过 `LocalGoalSet` 下发目标、`WaypointProgress` 返回批次进度，再由 dispatcher 合并里程计判定成功。这要求各家族自行维护批次关联、执行超时、停稳窗口和取消覆盖。ROS action 可统一通信生命周期，使调用方直接消费动作结果。

收益成立的前提是执行方拥有完整成功判据：仅把 `all_consumed` 包成 action 成功，dispatcher 仍须维护第二个停稳门。目标形态将这些通用执行判断收敛到 planner 进程；VLA 多腿、旋转累计角、工具调用唯一终态仍由 dispatcher 负责。

## 2. 现状事实（问题清单）

以下路径相对 `l3-dispatcher-planner/`，行号为本轮设计定位。

| 证据 | 现状与迁移影响 |
|----|----|
| `ros_packages/dispatcher/dispatcher/ros_adapter/planner_execution_ros.py:26`、`:57`、`:75` | 分离发布目标、订阅进度；关联依赖 `batch_id` |
| `ros_packages/dispatcher/dispatcher/tools/flight/flight_waypoint.py:73`、`tools/vla/vla_waypoint.py:73` | 两家族各自实现批次结束、超时及里程计停稳 |
| `ros_packages/dispatcher/dispatcher/tools/flight/flight_waypoint.py:135` | 取消通过当前位置保持目标覆盖旧批次，发布返回即清除保持待处理标记 |
| `ros_packages/dispatcher/dispatcher/execution/skill_host.py:27`、`:50` | 宿主武装动作、轮询结果并写入 core 代次账务 |
| `ros_packages/dispatcher/dispatcher/core/action_gate.py:62`、`:94` | core 通过完成门和技能裁决推进；这部分是任务生命周期 |
| `ros_packages/dispatcher/dispatcher/tools/vla/vla_skill.py:70` | 位置、终末偏航、贴地按成功结果串行推进 |
| `ros_packages/dispatcher/dispatcher/tools/flight/rotate_skill.py:64` | 每段成功后检查实际累计角，不能由普通航点成功替代 |
| `ros_packages/planner/ego_planner/plan_manage/src/ego_replan_fsm.cpp:114`、`:128`、`:2042` | EGO 使用目标 topic 与批次进度 topic |
| `ros_packages/planner/super_planner/planner/include/ros_interface/ros1/fsm_ros1.hpp:117`、`:255` | SUPER 有独立的目标处理和进度发布 |
| `ros_packages/planner/diff_planner/src/diff_replan_fsm.cpp:651`、`:717` | DIFF 同样消费旧目标并发布进度 |
| `ros_packages/utils/quadrotor_msgs/msg/LocalGoalSet.msg:1` | 旧消息还承载多点窗口、跟随与偏航模式，不能仅按 dispatcher 当前单点调用裁掉能力 |
| `ros_packages/planner/ego_planner/plan_manage/include/plan_manage/traj_server.h:65` | 轨迹跟踪代码引用旧消息中的偏航常量；删除消息需同步处理这些依赖 |

## 3. 目标与约束

- 目标：一个动作只有一个通信生命周期和一个执行结果；后端原生提供 action，飞行与 VLA 共享客户端。
- 目标：统一目录与命名，通用执行领域组件只保留一份；ROS 收发和业务判定分离。
- 非目标：迁移 ROS2、修改站端 RPC、恢复 `mission_executive`、新增任务队列、改变工具名字、把起降 `forwarded` 升级为物理完成。
- 硬边界：禁止新增转接器将 action 再转发为旧 topic；被替代的接口和代码直接删除；odometry、点云、轨迹及 cmd 数据流继续采用适合的数据接口。
- 执行方仅识别运动目标，不识别工具名。action 的 GoalID 是传输层动作关联标识，不作任务编号或能力映射；core 不接触 ROS 类型。
- 当前执行缝契约把取消与完成职责放在 dispatcher，并要求保留既有 planner 接口。本方案是有意改变职责边界，必须在 P0 更新契约后才实施；不能把新增代码解释为符合未修改的旧契约。
- 本轮已授权实施代码，不执行测试、构建、门禁或验证性验收。文档中的未来验收标准不构成执行授权。

## 4. 方案决策

### 4.1 归属与目标目录

每个后端的 planner 进程原生提供同名 `/planner/execute_waypoints` action；启动配置只选择其中一个。共用领域库直接调用各后端的规划、停止及状态读取端口，不创建独立中间执行节点，也不通过旧 topic 回环调用后端。

```text
ros_packages/
  utils/quadrotor_msgs/
    action/ExecuteWaypoints.action
    msg/WaypointTarget.msg
    msg/YawPolicy.msg
  planner/planner_execution/
    include/planner_execution/{execution,execution_ports,settle_monitor}.h
    include/planner_execution/action_server_ros.h
    src/{execution,settle_monitor,action_server_ros}.cpp
    CMakeLists.txt
    package.xml
  planner/ego_planner/plan_manage/
    src/execution_backend.cpp
    src/execution_backend_ros.cpp
  planner/super_planner/planner/
    src/ros_interface/execution_backend_ros.cpp
  planner/diff_planner/
    src/execution_backend.cpp
    src/execution_backend_ros.cpp
  dispatcher/dispatcher/
    execution/{ports,action_session,skill_host,composition}.py
    ros_adapter/planner_action_ros.py
    ros_adapter/flight_state_ros.py
    ros_adapter/flight_commands_ros.py
    tools/flight/{motion,rotate_skill,...}.py
    tools/vla/{vla_skill,ports,catalog}.py
```

上述新增路径为目标设计。`planner_execution` 是链接到后端进程的库，无节点入口；后端文件实现直接领域调用与启动装配，具体拆分结合各后端既有 ROS 隔离边界落实。本轮不顺带重构规划算法。

| 类型 | 命名 | 职责 |
|----|----|----|
| action | `ExecuteWaypoints` | 一次有限航点窗口执行 |
| 目标消息 | `WaypointTarget` | 明确坐标与运动意图，无批次或工具身份 |
| 偏航策略消息 | `YawPolicy` | 模式及路径策略唯一声明，迁移旧常量的使用方 |
| 服务端领域类 | `WaypointExecution`、`SettleMonitor` | 准入、执行、停止及停稳判定，无 ROS 类型 |
| 服务端 ROS 类 | `WaypointActionServer` | GoalHandle 管理、数据转换及领域事件投递 |
| 客户端领域类 | `ActionSession` | 一次动作的本地归属、结果消费和取消待处理 |
| 客户端 ROS 类 | `RosPlannerActionClient` | actionlib 连接与不可变回调事件 |
| 配置前缀 | `planner_execution` | 服务端执行策略的唯一权威 |

### 4.2 接口草案

最终字段类型及原因码在 P0 写入执行缝叶契约；这里给出迁移所需的接口形态。

| 部分 | 拟定内容 | 语义 |
|----|----|----|
| Goal | `header`、`target` | 世界坐标系下的原始航点窗口与终末偏航策略；窗口保留现有 1–3 点范围 |
| 目标内容 | `waypoints`、`yaw`、`look_forward`、`goal_to_follower`、`yaw_policy`、`ground_approach` | 保留原运动意图；低速偏航归入唯一模式声明，不再与独立布尔量重复表达 |
| Feedback | `phase`、`active_index`、`consumed_count`、位置及偏航误差、速度、停稳持续时间 | 展示进度；不构成成功或推进依据 |
| Result | `reason`、`stop_confirmed`、最终有效状态及其有效性标记 | 成败以 action 终态为准；无效观测不得用零值伪装有效 |

动作 Goal 不额外携带 `batch_id`、工具名、上游调用身份或第二套成功布尔值。原始目标与 planner 修正后的轨迹目标分别保存，成功核对原始目标。`goal_to_follower`、全景偏航及路径方向策略须按真实消费者完成映射；后端不支持的组合在准入时明确拒绝。

选择底层 `ActionClient` / `ActionServer` 和显式 goal handle，以控制单活动目标及拒绝策略。不得依赖“发送新 goal 自动取消旧 goal”：官方 `SimpleActionClient.send_goal()` 的行为是停止跟踪旧目标，并不会发送取消请求。[客户端实现](https://github.com/ros/actionlib/blob/noetic-devel/actionlib/src/actionlib/simple_action_client.py)

### 4.3 成功和失败

服务端按“目标准入 → 规划与执行 → 原目标停稳 → 成功”推进。全部航点消费仅进入停稳阶段。位置、速度、加速度、偏航角速度以及显式目标的角度误差同时满足，并持续达到停稳窗口后，才报告 `SUCCEEDED`。

服务端沿用当前连续 odometry 判定：检查坐标系、有限性、接收年龄与源时戳；重复快照不推进窗口；时间倒退、观测间断或超时明确失败。近点目标同样经过完成门。跳过必经点、规划失败、目标不可达不得静默成功。

反馈相位建议为 `planning`、`executing`、`settling`、`stopping`，只是领域执行阶段，不增加 dispatcher core 状态。

| action 状态 | 本方案处理 |
|----|----|
| `SUCCEEDED` | 原目标完成且停稳；客户端才允许技能推进 |
| `REJECTED` | 参数无效、后端不支持、执行忙或安全状态未恢复；不执行目标 |
| `ABORTED` | 已开始的动作失败；结果说明停止是否确认 |
| `PREEMPTED` | 活动目标取消完成，原轨迹失效且停止已确认 |
| `RECALLED` | 未开始执行的目标已撤回，无该目标的执行副作用 |
| `LOST` 或本地结果等待超时 | 通信结果未知；任务不得成功，不推断飞行器已停止 |

`ActionServer` 提供终态接口，但调用这些接口的物理前提仍由本方案的领域实现保证。[服务端实现](https://github.com/ros/actionlib/blob/noetic-devel/actionlib/include/actionlib/server/server_goal_handle_imp.h)

### 4.4 取消、覆盖与恢复

1. dispatcher 取消指定 goal handle，立即禁止该任务再发后继腿，同时保留该 handle 以接收取消结果。
2. 服务端收到取消后使原轨迹停止推进，调用后端原生制动及保持能力，进入 `stopping`。正常取消不广播全局急停。
3. 停止确认要求新鲜观测连续满足速度、加速度与偏航角速度阈值，并由后端确认旧轨迹失效、保持控制已经接管；不要求取消后返回原任务目标。保持位置与安全制动轨迹由后端确定。
4. 停止确认后活动目标报告 `PREEMPTED`。若取消与成功并发，以领域锁内首次完成的终态为准；已取消的上游任务即使收到迟到成功也不推进。
5. 同源新调用沿用现有上游抢占语义，但只在旧动作释放执行权后下发新 goal。等待发生在 dispatcher 已有队列及生命周期中；服务端拒绝忙时的新 goal，不新增待执行队列。
6. 停止超时或缺定位时报告 `ABORTED` 且 `stop_confirmed=false`，服务端进入故障闭锁并拒绝新目标。任务终态与执行资源是否可用分开处理，不能因为失败结果已返回就放行。
7. 故障恢复必须先完成后端安全保持并获得新鲜连续观测；通过既有显式停止或重置流程触发恢复，不靠新业务 goal 隐式恢复。服务端启动时同样先取得安全状态，避免重启后遗留轨迹仍在推进。

全局急停保留独立优先通道：它要能在没有活动 action 时生效。活动 action 在急停后只能失败或取消，不能成功。客户端未收到安全确认时保持本地准入闭锁；恢复需要重新建立服务端安全状态，单纯 action 连接成功不足以解除闭锁。

### 4.5 超时与断连

服务端配置有限 `action_timeout_s`、`stop_timeout_s`，分别约束执行含停稳的总时间、失败或取消后的停止时间；到达执行期限必须主动停止。客户端分别限制连接、准入、执行结果和取消结果等待，不在 engine 生命周期锁内阻塞 `wait_for_result()`。

actionlib 不承担站端租约和飞行安全监控。现有租约失效路径继续触发安全停；通信丢失时客户端不得自动重发原运动目标。客户端消失而服务端仍运行时，服务端执行期限保证动作不会无限运行，但这不等于即时断连急停。即时断连保护所需的现有安全信号链及其后端覆盖情况必须在 P0 明确，不能宣称 action 自带此能力。

### 4.6 dispatcher 账务与技能

ROS 回调只写事件队列；每个事件绑定发送时捕获的本地动作代次、技能实例及 goal handle。engine 节拍经宿主消费事件，再经既有完成门与四裁决推进。禁止在回调到达时把旧结果标记为“当前代次”。

飞行和 VLA 共用一个客户端与 `ActionSession`；删除两家族的批次、停稳和取消保持执行器。保留工具调用 owner、任务代次、单终态和 flight-exclusive 限制，这些不能由 action GoalID 替代。

VLA 保持位置 → 可选终末偏航 → 可选贴地腿，每腿对应一个 action，最后一腿成功才结束调用。旋转继续通过连续 odometry 核对实际累计角；航点 action 成功后再由技能决定下一段。返航原点也继续由 `FlightSession` 持有。

起飞、降落、急停工具当前 `forwarded` 语义单独保留，不能用 action 的存在宣称物理完成。odometry 仍可供 dispatcher 的原点、目标构造及累计旋转使用，但不再重复执行航点停稳判定。

### 4.7 配置与多后端切换

停稳阈值、状态超时、动作超时、高度界和地面高度迁往 `planner_execution` 唯一配置组。以一份启动配置装载所选服务端，并把技能仍需要的高度与角度容差作为只读配置注入 dispatcher；禁止家族各自保留另一套默认值。纯技能参数如最大累计旋转角、贴地接近高度仍归对应家族。

旧 `~flight/*` 中被迁走的键必须提供明确迁移说明，显式配置旧键时拒绝启动，不静默使用默认值。原数值默认保持；新连接、准入、停止期限在 P0 给出单位、正有限值约束及默认值。

EGO、SUPER、DIFF 采用同一 action 与完成语义；各后端原生实现规划和停止端口。分期开发允许，但生产切换必须同一交付完成所有被声明支持的后端，或者明确从启动可选项中移除未支持后端；不得静默回退到旧 topic。

## 5. 迁移映射表

| 旧路径或命名 | 新路径或命名 | 动作 | 说明 |
|----|----|----|----|
| `LocalGoalSet.msg` | `ExecuteWaypoints.action`、`WaypointTarget.msg`、`YawPolicy.msg` | 拆分并重写 | 迁移运动意图、窗口及偏航常量；移除传输批次 |
| `WaypointProgress.msg` | action Feedback / Result | 替换 | 进度与终态分开 |
| `tools/flight/flight_waypoint.py`、`tools/vla/vla_waypoint.py` | `planner/planner_execution/`、`execution/action_session.py` | 合并并删除旧文件 | 物理执行判定归服务端，本地生命周期归客户端 |
| `ros_adapter/planner_execution_ros.py` | `planner_action_ros.py`、`flight_state_ros.py`、`flight_commands_ros.py` | 拆分并重写 | action、观测和同步命令职责分开 |
| 三后端目标回调与进度发布 | 原生后端执行端口及 action 服务端 | 重写 | 直接调用领域方法，不经旧消息转发 |
| dispatcher 保持目标覆盖 | 服务端原生停止及保持 | 迁移 | 停止确认纳入取消结果 |
| `execution/skill_host.py`、`composition.py` | 原路径 | 修改 | 共用客户端、绑定 owner 和代次 |
| `core/action_gate.py` | 原路径 | 按需修改 | 消费统一领域结果，保留四裁决 |
| 旧 topic remap 与执行参数 | action 名称及唯一配置组 | 替换 | 所有后端启动入口同步 |

## 6. 删除清单

| 删除项 | 理由及条件 |
|----|----|
| 目标与进度旧 topic 的生产收发、旧 remap | 新 action 接管；全消费者迁移后同次删除 |
| `LocalGoalSet.msg`、`WaypointProgress.msg` 及生成声明 | 被新接口替代；轨迹代码的常量引用同步迁移 |
| 两家族 `*_waypoint.py` | 通用执行状态与停稳逻辑已归服务端 |
| 旧外部 `batch_id` 分配、过滤和取消保持批次 | 动作关联由 goal handle 管理；后端必要的内部轨迹版本不能机械删除 |
| 旧 `Progress` 数据结构和 `FlightPorts.progress/send_goal` | 由 action 端口替代 |
| dispatcher 内通用停稳窗口及其重复执行状态 | 成功判据唯一归执行方 |
| 已迁移配置的旧参数键与重复默认值 | 单一配置权威；提供明确迁移错误 |

不得按本清单顺带裁掉 R01/R02/R04/R06 保留项、工具 owner/代次、旋转累计观测或 planner 原有模式。旧接口的仓外消费者及脚本须在 P0 登记并安排同步切换；消费者未处理完时不启动生产切换，也不引入兼容桥。

## 7. 实施步骤（P0/P1/... 分期）

### P0 — 契约和完整迁移清单

- 范围：修订执行缝、技能、基础飞行及目录契约；按根契约登记必要叶契约。确定 action 字段、状态映射、配置默认值、全部消费者及三后端停止能力，明确即时断连保护边界。
- 行为不变式：工具名、任务单终态、VLA 多腿顺序、原始目标完成条件不丢失。
- 验收：待用户明确许可；当前仅列判据，不执行门禁。
- 回退：代码未迁移前可撤回拟议契约变更；历史决策保留，并由新决策说明取代关系。

### P1 — 服务端领域库与后端原生接线

- 范围：新 action 类型、通用停稳与生命周期库、EGO/SUPER/DIFF 原生规划和停止端口；新字段和旧模式逐项对应。
- 行为不变式：服务端单活动目标；无任务队列；成功与取消终态均有真实判据。
- 验收：经许可后按后端覆盖提前消费、目标修正、规划失败、停稳、取消与恢复。
- 回退：按代码版本整体回退；开发中间态不作为可部署版本，不启用双协议运行。

### P2 — dispatcher 客户端与生命周期

- 范围：共用 action 客户端、本地会话、回调队列、宿主及装配；取消从同步发布改为可等待的释放过程，覆盖和失败流程一并接线。
- 行为不变式：等待让出生命周期锁；旧回调不推进新任务；取消未确认不发新目标。
- 验收：经许可后覆盖乱序回调、重复终态、抢占、技能重注册及多腿任务。
- 回退：与服务端接口版本一同回退，不能只回退客户端。

### P3 — 原子切换和删除

- 范围：生产入口、依赖和配置切换；删除旧消息收发、重复执行器与残留常量引用；更新 R03/R05 及 rest 索引，附实现路径、证据和剩余触发条件。
- 行为不变式：发布版本只有一套执行协议；不把未验证后端声明为可用。
- 验收：明确许可后实施 §8；未获许可时交付状态必须注明未验收，不能发布为验收通过。
- 回退：整体恢复上一组匹配的消息包、planner、dispatcher 和启动配置，不保留运行时旧协议分支。

## 8. 验收标准

> 统一声明：本轮不运行测试或验证性验收；下列标准仅用于后续获得明确许可后的实施。

- [ ] 三后端提供相同接口与终态语义；不支持的目标准入失败，不能执行中静默改变目标含义。
- [ ] 提前消费、近点、原目标被修正、缺动态观测、重复或倒退时戳都不能伪造成功。
- [ ] 位置、速度、加速度、偏航角速度及显式偏航误差任一不满足时保持等待或失败。
- [ ] 取消前、执行中、停稳中及成功竞态均只有一个终态；停止未确认不得报告成功取消或放行后继目标。
- [ ] 服务端忙时拒绝新目标；同源抢占先释放旧执行权，再开始新动作。
- [ ] 服务端崩溃、客户端退出、结果丢失、网络恢复和重启不会自动重发旧动作或解除安全闭锁。
- [ ] VLA 每腿失败均终止后续腿；全部成功仅有一个工具终态；正反向跨圈旋转满足实际累计角。
- [ ] 原点、起降及急停工具的现有对外语义保持明确，`forwarded` 不冒充物理完成。
- [ ] 全消费者完成迁移，旧 topic 协议、旧消息生成项和旧家族执行器删除；保留项不被误删。
- [ ] 真实 planner 至 cmd 链路覆盖目标执行及停止，实机物理跟踪证据另行说明；不以领域结果代替实机证明。

## 9. 风险与对策

| 风险 | 影响 | 对策 |
|----|----|----|
| 只把批次结束改成 action 成功 | 双重完成门仍存在 | 服务端负责原目标与停稳，客户端仅负责技能判据 |
| action 状态与实际停止脱节 | 旧轨迹仍在执行就开始新目标 | 停止确认、故障闭锁及显式恢复 |
| 简化客户端忘记旧 goal | 取消和终态丢失 | 使用显式 goal handle，保留至释放完成 |
| 后端模式与停止能力不同 | 切换后语义变化 | 分后端直接接线，共同成功标准，不支持组合明确拒绝 |
| 旧消息还被轨迹代码或外部消费者引用 | 删除破坏编译或运行 | P0 完整登记，迁移常量与消费者后原子切换 |
| 配置跨进程不一致 | 技能目标与服务端完成条件冲突 | 一份配置源、只读注入、旧键拒绝 |
| 误把 GoalID 当作任务身份 | 破坏按工具名分发 | GoalID 限于通信关联，工具 owner 和调用生命周期独立 |
| 断连不自动取消 | 动作继续至执行期限 | 明确服务端有限期限与独立安全停链，不承诺 action 自带即时保护 |

## 10. 修改点清单汇总

| 文件或目录 | 动作 | 说明 |
|----|----|----|
| 本方案 | 新增及更新 | 设计与实施记录 |
| `specs/implemented/inner/l3-execution-seam.spec.md` | 待修改 | action 生命周期、完成及取消归属、配置 |
| `specs/implemented/inner/l3-skill-contract.spec.md`、`flight-actions.spec.md` | 待修改 | 客户端端口与异步释放、技能边界 |
| `specs/implemented/inner/l3-package-layout.spec.md` | 待修改 | 删除家族重复执行实现、登记共享会话 |
| `specs/implemented/l3-dispatcher.spec.md` | 按需修改 | 登记新增叶契约及职责变化 |
| `ros_packages/utils/quadrotor_msgs/` | 待新增及删除 | action 与目标类型、旧消息退役、构建依赖 |
| `ros_packages/planner/planner_execution/` | 待新增 | 通用执行领域库及 ROS action 服务端 |
| 三后端规划与 ROS 接线文件、EGO 轨迹偏航引用 | 待修改 | 原生执行端口及常量迁移 |
| `ros_packages/dispatcher/dispatcher/execution/`、`ros_adapter/` | 待修改 | 共用客户端、状态与同步命令端口 |
| `ros_packages/dispatcher/dispatcher/tools/` | 待修改及删除 | 保留技能流程，删除旧执行器 |
| `ros_packages/dispatcher/dispatcher/core/`、`tool_plane/` | 按需修改 | 异步取消释放和准入顺序，不引入领域判断 |
| `bringup/` 及各后端启动配置、包依赖 | 待修改 | action 原子切换与唯一配置 |
| `doc/l3-dispatcher-planner/rest/` | 实施时修改 | R03/R05 归属、证据及剩余触发条件 |
| `specs/implemented/architecture/` | 实施完成时新增 | 归档本轮职责变更决策，不重写历史记录 |

实施记录（2026-10-09）：已按本方案修改契约与生产代码，未执行测试、语法检查、构建、门禁或运行验收。未提交、推送或部署。

实际交付对应 P0–P3：

- `planner_execution` 已新增 ROS 无关的 `WaypointExecution`、`SettleMonitor` 和 ROS action 服务端；原始目标停稳、停止确认及故障闭锁归服务端。
- EGO、SUPER、DIFF 已改为原生后端接线；EGO 保留原地全景连续偏航，SUPER 显式拒绝低速和连续偏航，DIFF 显式拒绝偏航控制；三个后端均拒绝未实现的跟随目标。接口同型不表示运动能力相同。
- dispatcher 的 `ActionSession` 由飞行与 VLA 共用，装配注入 `lifecycle_tick` 持续回收取消结果；宿主只消费发送时绑定的 owner 和代次。起降同步转交增加执行资源空闲要求，忙时失败，不与未停止动作并发。
- 删除旧目标和进度消息、两家族航点执行器、旧 ROS 执行口；偏航常量迁到 `YawPolicy`。后端内部窗口序号保留为规划记账，不再在线上传递批次。
- `bringup/config/planner_execution.yaml` 提供唯一生产默认配置，EGO 启动入口和专用构建脚本已接入新库。SUPER、DIFF 的现有源码接入同一参数树；外部启动器须加载此配置并使观测 topic 与对应后端一致。
- 增加 `/planner/execution_state` 资源快照，包含启动标识和显式恢复代次，解决无活动 goal 时的就绪及重启识别；动作反馈与终态仍只由 action 提供。该快照不构成第二套任务协议。
- 现有验收资产未读取或迁移；后续获许可后须同步新接口并执行 §8，不得将旧接口用例的历史结果算作本次通过。

实施细化：后端原生函数沿既有 FSM 集成，SUPER 的接线集中在 `src/ros_interface/execution_backend_ros.cpp`。
没有新增中间节点或消息转接器；停止服务端使用现有后端控制出口，定位不可用时请求停止但不报告停止确认。
仓外启动器和消费者不在当前检出范围，本轮未替其切换；生产部署仍需同步迁移消费者、配置与构建产物。


## 2026-10-10 强制取消归属调整

取消与资源释放以[当前任务取消与紧急悬停方案](design-task-cancel-emergency-hover.md)为准。
普通任务取消同样触发紧急悬停并立即释放任务归属；停止确认由无 owner 的设备记录跟踪。
新增独立命令输出仲裁，以及 DIFF 的输出代次和保持回执，替代“任务 owner 持有到停稳”的旧设计。
地图、建图、定位、有效原点和常驻端点不在任务释放范围。本次代码未编译或验收。

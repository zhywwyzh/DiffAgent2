# 下行执行缝

Status: implemented
Contract-ID: l3-dispatcher/execution-seam
Parent: specs/implemented/l3-dispatcher.spec.md

## 范围与非目标

> 定义 dispatcher 的动作会话与 planner 原生 ROS1 action。交付状态不由契约状态推断。

## 术语与身份

### 1. 职责

技能拥有目标构造、多段顺序与专属完成判据；core 保持六态与四裁决。
dispatcher 的 execution/ 持有共享 ActionSession、端口、宿主与装配。
planner_execution 是链接到 planner 进程的领域库和 ROS 外壳，无独立节点、任务队列或工具语义。
各后端直接调用领域库并提供规划、停止能力，不通过旧目标 topic 桥接。
mission_executive 与 /mission/task 不恢复。

## 输入、输出与配置

### 2. 端口与收发

- 默认 action 为 /planner/execute_waypoints，使用 quadrotor_msgs/ExecuteWaypoints。
- Goal 包含 header 与 WaypointTarget；目标包含 1–3 点窗口、yaw、look_forward、YawPolicy 与 ground_approach。
- 未接入的目标跟随预留已按用户明确要求删除，消息与领域目标不保留占位或兼容字段；生产方和消费方须同步重新生成消息并构建。
- Feedback 包含执行相位、消费进度和停稳观测；反馈不得驱动任务成功。
- Result 包含 reason、stop_confirmed、state_valid 与最终位姿；成败以 action 状态为准。
- GoalID 仅关联传输动作，不作任务身份；内部轨迹版本不得用于工具分发。
- LocalGoalSet、WaypointProgress 及其生产收发接口退役，不保留兼容桥。
- ROS ActionClient、ActionServer、订阅与发布只在 ROS 适配文件；领域库不依赖 ROS 类型。
- `/planner/execution_state` 为执行资源状态快照，携带启动标识、恢复代次、ready、stop_confirmed 和相位；不承载动作结果。
  每 0.05 s 发布，客户端按接收年龄判断新鲜度。启动标识变化使旧动作失效；显式停止后的恢复代次增长并且重新就绪，才解除本地闭锁。
  该代次仅用于安全恢复关联，不作任务编号。
- `/planner/command_state` 使用 `quadrotor_msgs/CommandState`，携带后端启动标识、输出代次与 holding；DIFF 独立跟踪进程在保持输出发布后回报，服务端校验同启动、同代次及接收新鲜度。不能把 planner 单方面请求停止作为保持接管证据。
- 命令输出由 `CommandOutput` 在短临界区仲裁；独立 odometry 和 0.01 s 保持节律不争用规划锁。EGO/SUPER 在进程内直接交付命令，DIFF 轨迹通过启动标识及输出代次关联。
  独立保持路径是原生输出实现，不桥接退役的目标/进度协议。
- odometry、轨迹、cmd 保持数据流；起飞、降落及全局急停保留独立命令口。

### 5. 配置

共享参数由 /planner_execution 统一持有；服务端与 dispatcher 从同一参数树读取，旧 flight 中对应键显式拒绝。

| 参数 | 默认 | 单位 |
|----|----|----|
| world_frame | world | 坐标系 |
| min_height / max_height | 0.3 / 3.0 | m |
| ground_z | 无，贴地须显式配置 | m |
| state_timeout_s | 1.0 | s |
| action_timeout_s | 60.0 | s |
| stop_timeout_s | 5.0 | s |
| connect_timeout_s / admission_timeout_s | 5.0 / 5.0 | s |
| settle_position_m | 0.30 | m |
| settle_speed_m_s | 0.15 | m/s |
| settle_acceleration_m_s2 | 0.30 | m/s² |
| settle_yaw_rate_rad_s | 0.20 | rad/s |
| settle_hold_s | 0.20 | s |
| settle_yaw_deg | 10.0 | ° |

时间及停稳阈值须正且有限，偏航容差须小于 90°；高度界有限且有序。
ground_approach 才允许下界为 ground_z；不能绕过最大高度。
纯技能参数仍归家族，不在服务端识别具体工具名。

### 7. 后端边界

EGO、SUPER、DIFF 使用同一 action 类型，后端不支持的目标组合必须在执行前拒绝。
规划器算法保持原归属；通用停稳、取消生命周期由 planner_execution 唯一持有。
EGO 支持普通、低速及原地全景连续偏航；连续偏航从本动作起点归一化实际角出发解缠。
SUPER 仅准入普通最短路径偏航，速度朝向模式不准入显式偏航目标；低速和连续偏航显式拒绝。
DIFF 仅准入沿路径朝向，不接受显式偏航控制。

输出边界为 /setpoint_cmd；取消完成依据领域观测和后端保持接管，不等价于已验收实机跟踪。

## 行为规则

### 3. 完成门

原始目标独立保存，planner 内部修正不改变成功目标。全部航点消费仅进入停稳阶段。
位置、速度、差分加速度、偏航角速度和显式终末偏航误差同时合格，并在递增源时戳上持续停稳，才报告 SUCCEEDED。
重复快照不推进窗口；缺观测、过期、坐标不符、时间倒退或跳点不能成功。
姿态和速度沿用 odometry 世界系约定，不另行旋转。
旋转实际有符号累计角仍归技能；VLA 每腿成功才进入下一腿，全部成功才结束工具调用。

### 9. 连续执行扩展

未采纳的连续执行资源扩展见 `specs/proposed/inner/l3-tracking.spec.md` §10。

普通航点动作满足原目标完成门后，也须撤销运动输出、接管保持并确认动态停稳，才返回成功；
防止普通导航成功后仍占用输出，使连续动作无法准入。保持阶段的取消或安全停止覆盖成功候选。
`ActionSession.finish` 仅用于技能内部收尾，保留当前 owner 以消费停止结果；外部取消仍立即
释放 owner 并使用独立 StopRecord。过期轨迹采样只可撤销匹配的输出代次，不能停止后继任务。

## 失败、取消与资源生命周期

### 4. 取消与故障

- 合法任务取消立即失效待发目标与任务归属，并独立尝试全局急停和指定 goal handle 取消；服务端立即关闭旧运动输出并接管保持。
- 停止确认要求原轨迹失效、保持控制已接管及连续动态停稳，不要求回到原任务目标。
- 活动目标停止确认后 PREEMPTED；未执行目标撤回为 RECALLED；未准入为 REJECTED。
- 执行失败为 ABORTED；停止未确认必须 stop_confirmed=false 并闭锁新目标。
- 同源覆盖可进入已有任务队列，但旧动作释放前不得发送新运动目标。服务端无待执行队列，忙时拒绝。
- 故障恢复经显式停止/重置重新确认安全状态；连接重建本身不证明安全。
- 全局急停独立于 action；活动任务失败或取消，不能成功。
- 客户端断连不自动重发。服务端有限执行期限最终触发停止；不宣称 actionlib 自带即时断连安全停。
- dispatcher 立即释放被取消任务的 owner、目标与结果引用；仅保留不含任务对象的 StopRecord 跟踪设备停止及传输回执。停止中/故障禁止新运动，不能重新激活旧任务。
- 停止入口不争用长规划锁；输出发布使用短临界区和执行代次仲裁。停止后旧规划结果不得重新获得输出权。建图、定位、原点与通信端点保持常驻。
- 原生执行状态增加 execution_generation、motion_enabled；DIFF PolyTraj 增加 execution_boot_id、execution_generation，用于跨进程轨迹输出归属，不作任务身份。

### 6. 客户端与生命周期

回调写不可变事件，绑定发送时捕获的动作代次及句柄。宿主在 engine 节拍消费，不在回调中改任务 FSM。
owner、任务代次与唯一终态保留；迟到事件不能用当前代次重新标记。
ActionSession 由飞行与 VLA 共用。任务取消立即释放任务资源；进程关闭才有限等待停止后逆序注销端点，停止未确认不得宣称设备安全。
等待不得持有 engine 生命周期锁。六态 core 的等待仍须输出原因与输入年龄。

## 归属与依赖

本叶唯一拥有共享动作会话、planner 原生动作生命周期和公共执行参数；技能拥有业务目标与多腿顺序，算法归各 planner 后端。

### 变更关联

```contract-links
{
  "implementation": [
    "l3-dispatcher-planner/ros_packages/dispatcher/dispatcher/execution/**",
    "l3-dispatcher-planner/ros_packages/planner/planner_execution/**",
    "l3-dispatcher-planner/ros_packages/planner/ego_planner/**",
    "l3-dispatcher-planner/ros_packages/planner/super_planner/**",
    "l3-dispatcher-planner/ros_packages/planner/diff_planner/**",
    "l3-dispatcher-planner/ros_packages/utils/quadrotor_msgs/action/ExecuteWaypoints.action",
    "l3-dispatcher-planner/ros_packages/utils/quadrotor_msgs/msg/WaypointTarget.msg",
    "l3-dispatcher-planner/ros_packages/utils/quadrotor_msgs/msg/ExecutionState.msg",
    "l3-dispatcher-planner/ros_packages/utils/quadrotor_msgs/msg/CommandState.msg",
    "l3-dispatcher-planner/ros_packages/utils/quadrotor_msgs/msg/YawPolicy.msg",
    "l3-dispatcher-planner/bringup/config/planner_execution.yaml"
  ],
  "depends_on": [
    "l3-dispatcher",
    "l3-dispatcher/tracking"
  ]
}
```

## 条款检查判据

### 8. 门禁与验收

按 AGENTS.md 的统一声明，未获明确许可不执行测试或验证性验收。
后续许可后覆盖三后端、停稳、取消竞态、断连、重启、旧结果和多腿单终态。
| 标识 | 后续判据 |
|----|----|
| G10 | 不恢复 mission_executive 与 /mission/task，不保留旧消息桥接 |
| G11 | 共享执行与服务端不按工具名分支 |
| G12 | 领域执行的完成、取消及跨进程生命周期有对应证据 |

实现记录与剩余条件归 doc/l3-dispatcher-planner/iteration/design-planner-native-action.md；强制取消调整归 design-task-cancel-emergency-hover.md（交付状态见实施记录）。

检查执行与证据记录遵循 `specs/README.md` 的统一许可边界；本文件不记录通过结论。

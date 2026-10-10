# tracking 功能分析与迁移方案

> DiffAgent2 旧版已具备站端单次选框、机上 UETrack 连续跟踪、深度定位、Elastic 运动规划和停止收尾的实现链。建议在 DiffAgent2 新版保留这些业务能力，把任务流程归入 `navigation.track` 技能，重设计连续运动执行接口并接入唯一命令输出与停止确认机制。不能直接复制旧版 mission 层，也不能把每帧目标伪装成一次到点停稳动作。

## 0. 元信息

| 项 | 值 |
|----|----|
| 日期 | 2026-10-10 |
| 目标路径 | `l3-dispatcher-planner/` |
| 状态 | 首期机上代码与文档已交付；未编译、未验收，生产迁移未关闭 |
| 关联文档 | [原生 action 方案](design-planner-native-action.md)、[强制取消方案](design-task-cancel-emergency-hover.md)、[目标预留清理方案](design-remove-unused-follow-reservation.md)、[待迁依赖台账](../rest/dispatcher-deferred-dependencies.md) |
| 契约入口 | `specs/implemented/l3-dispatcher.spec.md` 及其全部叶契约 |

证据路径约定：`旧 l3/` 指 DiffAgent2 旧版的 `diff-dockers/drone_projects/l3-dispatcher-planner/`；`旧站端/` 指其 `diff-dockers/station_projects/l4-agent/`；`新 l3/` 指 DiffAgent2 新版的 `l3-dispatcher-planner/`。旧版位置只从本机忽略配置中的 `OLD_REPO_ROOT` 获取。本方案不记录机器路径。

## 1. 背景与动机

tracking 同时包含视觉目标跟踪和飞机跟随，两者必须分开判断：图像框持续更新，不代表深度定位有效，更不代表规划器已经输出运动或飞机完成跟随。

DiffAgent2 新版已有基础飞行、VLA、动作归属、强制取消和 planner 原生 action，但现行目标是有限航点。新增 tracking 的主要工作是补齐连续感知和连续运动生命周期，而非增加一个工具名或恢复此前已删除的预留字段。

## 2. 现状事实（问题清单）

以下为源码阅读依据，不代表部署状态或运行验收结果。

| 证据 | 事实及影响 |
|----|----|
| `旧站端/src/copaw/station_sidecar/flight/service.py:674`、`:1317` | 自然语言调用先执行一次 seed 接地；另有人工框选入口。站端下发 seed 后，连续闭环留在机上。 |
| `旧 l3/ros_packages/dispatcher/dispatcher/tools/registry.py:96` | 工具名为 `navigation.track`；机上输入必填 `object`、`prompt`、原图像素 `bbox`（xyxy）、`image_stamp`、`session_id`；旧元数据为 `action_result`。工具编号不迁。 |
| `旧 l3/ros_packages/dispatcher/dispatcher/tools/track/skill.py:56`、`:162`、`:267` | `TrackSkill` 默认启动隔离进程；首个可用 bbox 后通过 `TaskActionGoal` 调 mission。类名声明为 `track`、实际分发检查 `navigation.track`，且直接访问宿主私有代次和 action client；不能原样搬入新版。 |
| `旧 l3/ros_packages/dispatcher/dispatcher/tools/track/frames.py:55`、`:84`、`:115` | 有界 RGB 历史用于寻找 seed 对应帧，默认 256 帧、15 s、256 MiB；连续推理消费最新递增帧，源时间与接收时间均检查。不能拿当前图像替代 seed 图像。 |
| `旧 l3/ros_packages/dispatcher/dispatcher/tools/track/producer.py:47`、`client.py:34` | 独立串行 worker 持续推理，结果缓存只保留最新项，不受 dispatcher tick 或几何计算节拍约束；HTTP 重试复用同一请求。 |
| `旧 l3/ros_packages/dispatcher/dispatcher/tools/track/service/session.py:79`、`:142` | `epoch + session_id + send_seq` 隔离服务会话与重复请求；低置信度进入恢复，默认连续 3 帧确认恢复，5 s 后判丢失。恢复位移门默认关闭。 |
| `旧 l3/ros_packages/dispatcher/dispatcher/tools/track/service/uetrack_engine.py:16`、`:70` | UETrack-B 依赖 CUDA、模型和 CLIP 权重及校验清单；模型不会靠迁入 Python 文件自动就绪。 |
| `旧 l3/ros_packages/dispatcher/dispatcher/tools/track/publisher.py:83`、`:145` | 控制 bbox 带图像时戳、尺寸、内外参、观测序号和会话身份；观测及带框图像为独立遥测。带框图使用实际推理帧，显示限频为 5 Hz。 |
| `旧 l3/ros_packages/mission_executive/src/mission_tracking_ros.cpp:59`、`:152` | mission 以 20 Hz 编排启动、跟随、丢失保持与结束，并转发 `/tracking/bbox` 到 `/tracking/planner_bbox`，执行 `/planner/tracking`。这是新版需要上收至技能的任务流程。 |
| `旧 l3/ros_packages/mission_executive/include/mission_executive/tracking_lifecycle.h:7` | 子状态为 STARTING、ACTIVE、HOLD、STOPPING；距离、朝向、飞机速度及目标速度持续满足条件后自动成功，并非无限期跟随。 |
| `旧 l3/bringup/config/tracking.yaml:2` | 配置中的跟随距离为 2.5 m，目标世界高度 1.0 m，距离容差 0.3 m、偏航容差 0.2 rad；飞机/目标速度阈值为 0.1/0.2 m/s，持续 3 s，初始化/丢失/会话时限为 10/5/600 s。它们是文件值，不是已确认的运行参数。 |
| `旧 l3/ros_packages/planners/elastic_tracker/src/planning/planning_nodelet.cpp:180` | 按 bbox 图像时间插值位姿，匹配对齐深度（默认时间差 0.04 s），取框内有效深度中位数，再投影到 world 并更新估计器。无深度时不产生有效测量。 |
| `旧 l3/ros_packages/planners/elastic_tracker/include/tracking/target_estimator.hpp:48`、`:104` | 先用深度测量世界坐标，再固定目标 z；使用六维匀速滤波，估计外推不足 2 s。该实现不等同于任意三维目标运动跟随。 |
| `旧 l3/ros_packages/planners/elastic_tracker/src/planning/planning_nodelet.cpp:1005`、`:1051` | 规划频率读取 `plan_hz`（代码默认 10 Hz），目标估计发布为 20 Hz；不能仅凭历史方案名称声称端到端 12 Hz。 |
| `旧 l3/ros_packages/planners/elastic_tracker/launch/planning/ws_main_tracking_real.launch:6` | 地图输入可选雷达建图或 occupancy，跟踪规划与独立轨迹输出分进程；迁移还涉及地图接口、轨迹格式与输出归属。 |
| `旧 l3/ros_packages/utils/quadrotor_msgs/scripts/motion_gate.py:13`、`:40`、`:83` | 旧版用独立 MotionGate 选择 ordinary/tracking/hold，过滤执行身份并在输入断流后保持。不能与新版 CommandOutput 并存为两个最终命令写入方。 |
| `旧 l3/ros_packages/planners/elastic_tracker/src/planning/planning_nodelet.cpp:147`、`旧 l3/ros_packages/mission_executive/src/mission_tracking_ros.cpp:16` | Elastic 取消会清理目标并报告 PREEMPTED；mission 等待 action done。它们本身没有证明新版要求的保持接管和连续动态停稳。 |
| `新 l3/ros_packages/dispatcher/dispatcher/execution/action_session.py:59`、`:82` | 现有会话按有限目标准入，取消立即释放任务引用，以 StopRecord 独立跟踪设备停止。tracking 必须加入这套资源约束。 |
| `新 l3/ros_packages/planner/planner_execution/include/planner_execution/execution_ports.h:11`、`新 l3/ros_packages/utils/quadrotor_msgs/action/ExecuteWaypoints.action:1` | 现有 Target 和 action 没有连续观测流接口；现行 waypoint 结果语义不能原样用于移动目标。 |
| `新 l3/ros_packages/planner/planner_execution/include/planner_execution/command_output_ros.h:19` | CommandOutput 已有启动标识、输出代次、保持与短临界区仲裁；但不同进程分别实例化并不能自动形成跨后端唯一输出权。 |

还需区分两类丢失：UETrack 低置信度恢复与几何/估计失效保持。目前二者分别有超时，不能迁移后叠加成不可解释的长等待。旧代码允许 `observation_age=0` 关闭部分年龄检查，而文件配置为 0.5 s；源码不足以判断部署取值。新版现行契约要求新鲜度可读及显式处置，不能默认继承关闭检查的分支。

## 3. 目标与约束

- **目标**：实现 `navigation.track` 的单次选定目标、机上连续跟随、短时丢失保持、恢复、正常完成及强制取消；保留同帧遥测。
- **本轮范围**：在已获执行许可后完成首期机上实现、契约边界、显式启动配置及迁移台账。默认生产集合不变；不运行构建、测试或部署。
- **非目标**：多目标切换、在线再识别、机上重新调用语言模型、任意三维运动跟随、自动恢复历史任务，以及直接迁入整个站端或旧部署工程。
- **硬边界**：core 六态保持不变；按原始工具名分发；无任务编号；不恢复 mission 层；禁止桥接旧接口的转接器；被替代功能直接删除。
- 此前删除的目标跟随预留不自动恢复；新增字段只能服务本次明确的生产者和消费者。
- 单次调用只产生一个终态；任务资源立即释放与设备实际停稳分别处理；保持地图、定位和有效返航原点。

## 4. 方案决策

### 4.1 目标调用链与职责

```text
站端单次选框或 VLM 接地
  → navigation.track（原始 seed）
  → TrackSkill（初始化、保持、恢复、完成判据）
      ├─ RGB 缓存 → UETrack 服务 → 带身份的 bbox 连续流
      └─ 原生连续跟踪 action → Elastic 跟踪后端
          bbox + 对齐深度 + 位姿历史 → 世界目标估计 → 轨迹规划
          → 共用执行资源与唯一 CommandOutput → /setpoint_cmd
      ← 目标估计、执行进度、停止确认
  → 唯一 rpc_outcome
```

技能持有 STARTING、ACTIVE、HOLD、STOPPING 子状态及完成候选窗口。几何、目标滤波和轨迹优化保留在独立 planner 能力中。RGB 缓存为纯数据；ROS 适配层是唯一写入方，经宿主端口交给技能。HTTP 推理和图像编码不在 engine 生命周期锁内执行。

### 4.2 连续执行接口

本轮新增原生连续跟踪 action（`TrackTarget.action`，目标端点 `/planner/track_target`）。Goal 建立一次有期限的执行及目标身份，连续 bbox 走一个直接观测 topic，Feedback 返回估计和执行状态，Result 表达停止及故障结果。话题只承载变化的数据，action 负责准入、生命周期和取消。

不逐帧发送 `ExecuteWaypoints`：现有服务端忙时拒绝，且每个目标要求到原目标停稳；频繁 cancel/start 还会不断触发强制停止。连续跟踪必须成为实际实现的原生能力，而不是 waypoint 外面的重试包装。

两个 action 必须共用一个运动资源 owner 和一个停止状态；不同端点不能分别认为自己空闲。建议首期将选定的普通导航后端与 Elastic 算法装配在同一 planner 进程，共享执行资源和输出对象。停止路径使用独立回调队列，规划长锁不得阻塞保持。

若受 Elastic nodelet、地图或轨迹线程约束必须分进程，则需先细化跨进程唯一输出授权和保持回执协议，再实施；不能照搬 MotionGate，或仅凭两个进程都使用 CommandOutput 就宣称独占成立。首期普通后端建议从现有 EGO 开始，SUPER/DIFF 的共存接入不默认视为已完成。

### 4.3 结束语义

默认保留旧版“目标与飞机稳定后自动完成”的业务语义。持续跟随直到取消是另一种产品语义，暂不擅自替换。

建议公开完成元数据使用 `workflow_result`：技能确认距离、朝向、双方速度和持续窗口后，发起内部正常收尾，等待执行侧停止确认，再提交成功。其余任意 action 结束均不能直接推出工具成功。该项相对旧版 `action_result` 是有意变更，须在 P0 明确写入工具面及站端结果消费约定。

内部正常收尾可取消连续 action，但取消回执本身不算成功；必须同时具备当前调用的业务完成证据、原输出已撤销、保持接管及动态停稳。用户取消、租约丢失、同源覆盖优先于正常完成候选，一律按现行规则失败收尾。StopRecord 不保存已取消的技能对象。

短时目标失效立即停止运动，进入技能 HOLD；恢复须满足同一目标身份、递增新鲜观测及旧运动停止确认。最终 `track_lost` 不自动重新初始化模板或改跟其他目标。业务完成窗口只由递增且新鲜的观测推进，重复预测不能冒充新的观测证据。

### 4.4 参数与身份

机上输入建议保留 `object/prompt/bbox/image_stamp/session_id`，新增要求之前先核对站端消费者。`session_id` 仅作为视觉会话关联，不参与工具分发；工具调用仍仅以 `call_id` 关联。内部执行代次、观测序号与服务 epoch 各自限定职责，不恢复 task-id。

配置分为三处唯一权威：技能业务门使用 `~track/*`；跨技能执行和停止使用 `/planner_execution/*`；Elastic 算法及目标估计使用其后端配置。共同消费的跟随距离由单一配置读取或随 action 显式传入，不在两侧复制默认值。参数统一单位后缀，迁移时登记旧名到新名。

固定目标世界高度、深度有效值比例、bbox 中背景深度干扰、同步容差和恢复身份门需要作为明确设计项。不能把旧版“全框中位数 + 固定 z”描述为已解决所有目标定位问题。先保留可追溯的旧算法基线，再依据获许可后的数据决定改进。

### 4.5 目录与命名

```text
l3-dispatcher-planner/
  ros_packages/dispatcher/dispatcher/
    tools/track/{catalog.py,track_skill.py,ports.py,producer.py}
    tools/track/service/                 # 推理服务实现，保持进程隔离
    perception/tracking_frames.py        # 有界纯数据缓存
    execution/{action_session.py,skill_host.py,composition.py}
    ros_adapter/{tracking_frames_ros.py,tracking_observation_ros.py,planner_action_ros.py}
  ros_packages/planner/
    elastic_tracker/                     # 算法领域代码和 ROS 外壳分离
    planner_execution/                   # 共用运动资源、取消、输出和停止确认
  ros_packages/utils/quadrotor_msgs/      # 原生 action 和实际消费的观测消息
  bringup/config/tracking.yaml
  docker/tracker/                        # 模型服务构建与运行依赖
```

| 类型 | 规范 | 示例 |
|----|----|----|
| 技能身份 | 原始工具名 | `navigation.track` |
| 家族目录 | 单一现行家族名 | `tools/track/` |
| Python 类与方法 | PascalCase、snake_case | `TrackSkill`、`wait_action_tick` |
| ROS 文件 | 明确 `_ros` 后缀 | `tracking_observation_ros.py` |
| 配置 | 归属前缀、单位后缀 | `~track/loss_timeout_s` |

上表为目标布局建议，具体端口清单、action 字段和依赖豁免先在 `specs/` 采纳；本文不作为第二份接口契约。

## 5. 迁移映射表

| DiffAgent2 旧版单元 | DiffAgent2 新版归属 | 动作 | 理由 |
|----|----|----|----|
| 站端 `track/grounding.py`、人工框选 | 站端消费者边界 | 保留交互、另行对齐 | 已存在真实 seed 生产者；本轮只读 |
| `tools/track/skill.py` | `tools/track/track_skill.py` | rewrite | 去 ROS、任务编号和宿主私有访问 |
| `mission_tracking_ros.cpp`、`TrackingLifecycle` | TrackSkill 子状态与完成门 | rewrite | 任务流程归技能，不迁 mission |
| `frames.py` | `perception/` + ROS 适配层 | split | 保留有界缓存、精确 seed 和时间回退隔离 |
| `producer.py`、`client.py`、服务会话 | `tools/track/` 及服务进程 | 复用算法并重整端口 | 保留单请求串行、幂等重试及 epoch 隔离 |
| `runtime.py`、`runtime_process.py` | 推理 worker 生命周期 | rewrite | 是否保留额外进程按阻塞与资源隔离需要裁决，不复制旧宿主壳 |
| `BBoxPublisher` 与 mission bbox 转发 | 一条直接观测流 | rewrite | 删除中间转发和二次执行身份改写 |
| Elastic 深度投影、滤波与优化 | `planner/elastic_tracker/` | 迁算法、拆 ROS 外壳 | 保持运动规划独立，适配层不持有领域决策 |
| `/planner/tracking` 的旧 WaypointAction | 原生连续 action | replace | 完整表达持续执行与停止确认 |
| MotionGate 和独立轨迹输出 | 共用 CommandOutput 和原生输出实现 | replace | 单输出权、迟到轨迹失效、独立保持 |
| 带框图像与 observation | ROS 遥测适配层 | rewrite | 同帧显示与控制解耦，不让显示限频影响推理 |

## 6. 删除清单

| 不迁入或被替代项 | 理由 |
|----|----|
| `TaskActionGoal.task_id`、工具编号及 `track` 内部别名 | 新版按 `navigation.track` 直接分发 |
| mission tracking FSM、`/mission/task` | 任务流程回归技能 |
| `/tracking/bbox → /tracking/planner_bbox` 转发层 | 观测直接交给执行消费者 |
| 旧 WaypointAction 跟踪包装与 MotionGate | 原生连续执行和共用输出替代，禁止新旧协议桥接 |
| 未被调用的旧调试、训练和演示入口 | 按迁移闭包选取，不整包复制 |
| 已删除的通用跟随占位字段 | 不为实现 tracking 自动恢复旧预留 |

本轮不删除 DiffAgent2 旧版文件；上述清单约束后续迁入 DiffAgent2 新版的内容。

## 7. 实施步骤（P0/P1/... 分期）

### P0 — 固化业务与执行契约

- 范围：在 `specs/` 新增 tracking 提案，更新技能端口、执行缝、工具目标集合和必要的布局规则；明确正常完成、取消、短时保持、会话预算及输出权。同步 rest 索引及 R03/R05，记录服务仍按 R01/R06 挂账。
- 行为不变式：目标集合不等于生产集合；无空技能注册；不恢复旧预留。
- 验收：获许可后再核对契约和门禁。
- 回退：撤销提案改动，不影响当前生产工具。

### P1 — 接入 seed 与持续视觉跟踪

- 范围：RGB 缓存、UETrack 依赖、服务会话、生产者、同帧遥测和资源逆操作；可单独完成感知链，但不提前宣称可飞行跟随。
- 行为不变式：精确 seed、单服务会话、最新帧优先、迟到结果无效，取消不等待慢 HTTP 才请求停止。
- 验收：获许可后覆盖种子错帧、重复请求、时钟回退、低置信度恢复和模型不可用。
- 回退：撤回本期接线；现行工具集合不变。

### P2 — 接入 Elastic 与原生连续执行

- 范围：几何估计、地图依赖、轨迹规划、连续 action、共用运动资源与唯一输出；先解决普通导航与 Elastic 的同进程装配可行性。
- 行为不变式：仅当前执行拥有运动输出；停止不清图、不停定位；忙时拒绝；旧轨迹不能在停止后恢复输出。
- 验收：获许可后覆盖运动中停止、观测断流、规划长耗时、重启、地图过期和后端切换。
- 回退：撤销新增后端装配，恢复原导航启动配置；不留下旧协议兼容口。

### P3 — 技能闭环与站端对齐

- 范围：TrackSkill 子状态、业务完成门、正常停止汇合、故障原因、宿主装配及站端元数据对齐。实现闭包完成且按约定验收后再加入生产注册表并更新 revision。
- 行为不变式：每次准入一个终态；自动完成与外部取消不能混淆；普通导航与 tracking 切换须先停旧运动。
- 验收：获许可后执行真实站端调用至 `/setpoint_cmd` 的完整链路。
- 回退：同步撤回生产注册及本期调用入口，不保留可发现但不可执行的工具。

## 8. 验收标准

**遵循统一声明：本轮不读取测试文件或测试说明，不运行测试、构建、门禁或验证性验收。以下仅为未来获许可后的判据。**

- seed 绑定原始图像；bbox 越界、时戳错误、内外参不符与缓存过期均明确失败。
- 重试不重复初始化；旧 epoch、旧执行、迟到响应、时间倒退不能控制当前目标。
- 图像跟踪、世界目标估计、运动规划和同帧遥测的状态及耗时分别可观测。
- 无深度、过期位姿、无地图及估计断流不能继续使用无限期旧目标。
- 达距、朝向、双方速度及持续窗口满足后，须确认停止再成功；取消和丢失不能假成功。
- 快速连续取消、满队列、推理阻塞、规划长锁及进程重启下仍只有一个最终输出 owner。
- tracking 与 VLA/基础飞行切换不出现同时输出；停止后地图、定位、返航原点保留。
- 生产工具 schema、完成元数据、失败原因和站端消费同步；结果唯一。
- 频率以实际推理、有效观测和规划耗时测量，不把 timer 配置当作性能交付。

## 9. 风险与对策

| 风险 | 影响 | 对策 |
|----|----|----|
| 把 tracking 当作循环航点 | 频繁停稳、忙拒绝、取消风暴 | 独立连续 action，共享资源 owner |
| 普通 planner 和 Elastic 各自输出 | 抢写控制命令 | 先明确同进程唯一输出；分进程另立实际授权协议 |
| 旧取消完成无物理确认 | 假报已停止或过早切换 | 复用新版保持接管及连续动态停稳证据 |
| 固定目标高度和框内背景污染 | 跟随几何偏差 | 明确首期适用范围；独立设计深度质量门 |
| 推理和几何丢失预算重复 | 停止或失败延迟不可解释 | 技能持有统一任务预算，各阶段报告真实原因 |
| seed 经站端推理延迟过大 | 缓存淘汰、启动失败 | 缓存按实际链路预算配置，不放宽实时运动新鲜度 |
| ARM/CUDA 与模型依赖未闭合 | 服务无法初始化 | 跟踪镜像、依赖、权重校验作为 P1 交付项 |
| 当前停止链尚未验收 | 新功能叠加在未证实基础上 | 保持 R03/R05 未关闭，后续许可后同时取得停止与跟踪证据 |

## 10. 修改点清单汇总

| 文件或目录 | 动作 | 说明 |
|----|----|----|
| 本方案 | 本轮新增 | 源码事实、差异、职责裁决、阶段与风险 |
| `specs/` 的 tracking 提案及相关叶契约 | 已新增或修改 | 业务和连续执行接口、端口、显式注册与 RPC 消费边界 |
| `doc/l3-dispatcher-planner/rest/` | 已同步 | 新增 R10，补充 R03/R05，未关闭运行验收条件 |
| `dispatcher/tools/track/`、`perception/`、`ros_adapter/` | 已新增 | 按领域、纯数据及通信职责拆分 |
| `dispatcher/execution/`、工具注册面 | 已修改 | 共用动作归属与停止；显式装配第九项，默认八项不变 |
| `planner/elastic_tracker/`、`planner_execution/` | 已新增或修改 | 算法迁移、原生连续 action、唯一输出 |
| `quadrotor_msgs/`、`bringup/`、`docker/tracker/` | 已新增或修改 | 消息、启动、配置和模型服务依赖同步交付 |

三个设计项均已落实到源码和相关契约边界：独立连续 action、EGO/Elastic 同进程唯一输出、固定高度与稳定后停止。tracking 叶契约仍处于部分实施提案状态，不据此宣称生产验收完成。

## 实施记录（2026-10-10）

### 交付范围与阶段状态

P0 的接口和边界已落盘，P1 感知及推理服务代码、P2 连续执行及 Elastic 算法已接入，
P3 的机上显式装配和启动配置已交付。P3 生产注册、站端端到端消费与全部阶段的运行验收
尚未完成；这部分在 R10 挂账。因此“首期机上代码交付”不等于“整个 tracking 生产迁移完成”。
本轮不修改 DiffAgent2 旧版或外部站端，也不提交、推送或启动设备。

### 实现归属

- `dispatcher/tools/track/`：原生 `navigation.track` 技能、单 worker HTTP 客户端、会话与序号隔离、
  STARTING/ACTIVE/HOLD/STOPPING、自动完成条件、取消和遥测。推理服务单独进程运行。
- `dispatcher/support/tracking_data.py` 与 `perception/tracking_frames.py`：有界压缩原图缓存，
  精确 seed 匹配；`ros_adapter/tracking_*_ros.py` 是收发层。HTTP worker 解码核对原图真实尺寸，
  传输仍使用原 JPEG。HTTP、解码和显示不占领域节拍。
- `dispatcher/execution/` 与 `ros_adapter/planner_action_ros.py`：同一 ActionSession 支持
  有限航点和连续动作；内部 finish 保留 owner 等结果，超时使用停止预算，不等完整跟踪期限。
  外部取消仍立即释放 owner，独立 StopRecord 跟踪设备停止。
- `planner/elastic_tracker/`：深度配准、位姿插值、固定高度目标滤波、预测、可见区域和轨迹优化；
  EGO 直接提供地图查询，同进程共享 CommandOutput。独立采样同时受源时间和单调时钟约束，
  即使源时钟暂停或规划长锁未释放，过期观测也不能无限期授权运动。
- `planner_execution/`、`quadrotor_msgs/`：连续 action、直接观测消息、互斥准入、停止和停稳。
  过期采样只能撤销匹配代次；普通导航完成后也先进入保持，再交出输出权。
- `bringup/launch/tracking.launch`：显式以 `dispatcher_node.py --tracking-profile` 装配第九项；
  默认入口不变。启动选择只发生在组合根，不增加 RPC 动态工具开关，也不按瞬时就绪修改列表。

### 实施中的具体裁决

1. 跟踪自动完成要求飞机和目标均有递增的新鲜观测；失效或时间间隔断裂即重置完成窗口。
   取消回执仅表示执行结束；只有本次业务候选与确认停止同时成立才上报 `workflow_result`。
2. 普通导航原目标完成门保留，随后追加保持及动态停稳。期间取消或安全停止撤销成功候选。
   清除 EGO 轨迹类中重复的空析构声明，保留停止并回收指令线程的析构逻辑。
3. EGO 与 tracking 使用相同的 PositionCommand 增益语义；二者均不注入 `kx/kv` 配置。
   本轮不添加一套未经标定的控制器增益。
4. 目标附近占据仅在算法局部查询中屏蔽；交付轨迹按未屏蔽的 EGO 膨胀地图检查，包含终点。
   不清除共享地图。目标遮挡等情况可能保守失败，未声明与旧版轨迹完全等价。
5. 预测搜索节点池改为 65536 项，达到容量明确失败；避免复制旧版大规模逐节点分配。
   搜索节点和优化缓冲区改为容器管理，失败及重复会话不会遗留旧分配。
6. 初始化预算采用已有客户端的 30 s，统一技能与客户端边界；旧配置 10 s 不原样继承。
   丢失 5 s、总期限 600 s、运动观测有效期 0.5 s 保留明确边界，禁用无限年龄分支。
7. 模型服务和算法仅迁入运行依赖闭包；不迁 mission、MotionGate、任务编号、旧消息转发或训练入口。
   vendor 下名称包含 `lib/test` 的少量 Python 模块是推理运行依赖，并非本轮执行的验收脚本。

### 部署准备说明（未执行）

首先在外部构建目录生成 `TrackTarget`、`TrackingObservation` 并构建 EGO 依赖闭包；
`tools/build_ego.sh` 已包含 `elastic_tracker`，本轮未调用该脚本。
默认 EGO 因编译依赖变化也需重新构建，不能只替换 dispatcher Python 文件。

GPU 服务镜像以 `l3-dispatcher-planner/` 为构建上下文，使用 `docker/tracker/Dockerfile`；
构建者显式给出固定的 `TRACKER_BASE_IMAGE`、`UV_IMAGE` 与 40 位 `CLIP_COMMIT`。
依赖版本和镜像参数只随源码交付，尚未证明目标 GPU 环境可用。权重只放主机本地区，
以只读目录挂载到容器的 `/weights/track`，其中包括：

- `uetrack_inference.pth.tar`；
- `clip/ViT-L-14.pt`；
- `weights.json`，包含 `checkpoint.sha256` 与 `clip.sha256` 两个实际文件摘要。

服务入口只监听 `127.0.0.1:2250`，部署需使用与 dispatcher 可达的同主机网络空间；
Docker 可使用 host 网络和 GPU 设备授权。单 worker，不自动下载权重，不把容器私有回环端口
误当成宿主可达端口。镜像、主机目录与设备选择由部署配置提供，不在本文件写机器值。

启动 `bringup/launch/tracking.launch` 前，显式提供 `ground_z`、九元素行优先
`camera_rotation`、三元素米制 `camera_translation`。旋转指光学轴转换之后的安装旋转，
不得重复计入光学坐标轴转换。RGB 原图、CameraInfo、对齐深度、world 位姿、EGO 地图和
源时钟必须来自同一标定链；话题可通过 `~track/*` 与 `/elastic_tracker/depth_topic` 配置。
站端按发现面提交 `object/prompt/bbox/image_stamp/session_id`，并消费 `workflow_result`。
首期连续动作仅在该 EGO 装配提供，SUPER/DIFF 不自动获得 tracking 能力。

### 证据与剩余条件

以上是代码及配置修改记录，没有测试、编译、门禁或运行验收证据；本轮也未读取测试资料。
下一阶段需用户明确许可后按 §8 执行构建与受控链路验收，取得模型性能、几何质量、取消停稳、
正常完成和站端结果消费证据，再决定进入默认生产集合并更新契约状态。
R03/R05/R10 保持未关闭；记录服务 R01/R06 不随 tracking 接入关闭。

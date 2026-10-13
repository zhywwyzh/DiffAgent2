# k3s Unity 仿真栈接入方案

> 摘要：复用已有可运行镜像与 Exploration 工作区的 k3s 编排经验，为 DiffAgent2 新版实现 Unity、动力学、EGO/dispatcher、站端和可观测性启动链。以本仓库现行协议和契约为约束；本文是实施方案，不替代 spec。

## 0. 元信息

| 项 | 值 |
|----|----|
| 日期 | 2026-10-12 |
| 状态 | 代码已交付；P0–P3 实现接入，未构建、未部署、未运行验收 |
| 默认目标路径 | `l3-dispatcher-planner/bringup/k3s/unity/`、`l3-dispatcher-planner/tools/` |
| 参考来源 | DiffAgent2 旧版的部署编排；使用者指定的 Exploration 工作区；当前独立 L2、L4 检出 |
| 来源定位 | DiffAgent2 旧版根从被忽略的 `.local.env` 的 `OLD_REPO_ROOT` 读取；其他来源使用使用者指定的本地检出，实际主机路径不入库 |
| L2 基线 | `l2-simulator-amd64` 的 `unity-version`，本次已拉取至 `f3d6cb9` |
| L4 基线 | 当前 `l4-agent` 的 `exploration-version`；后续实施固定实际提交，不把分支名视为制品身份 |
| 关联契约 | `specs/implemented/l3-dispatcher.spec.md` 及其全部叶契约；`topology.spec.md`、`development-workflow.spec.md`、`observability.spec.md` 及相关叶契约 |
| 关联材料 | `design-planner-native-action.md`、`design-task-cancel-emergency-hover.md`、`../rest/dispatcher-deferred-dependencies.md` 的 R03/R05 |

使用者已确认参考工作区的 k3s 方案及其容器可运行；此结论作为选型依据。它不等同于 DiffAgent2 新版接线已通过验收。请求中的“七月设计”暂按“契约设计”理解；如指特定历史文档，收到文档后补充依据。

## 1. 背景与动机

当前已有独立 L2 仿真器仓库、L3 原生 Action 执行链与原生 L4 站端，但缺少将三者装配到同一仿真栈的部署入口。参考工作区已经提供 k3s 管理 ROS master、动力学、Unity TCP 接入、算法节点与日志的运行方式。

本方案采用该方式，保留现有镜像作为执行环境，集中调整源码挂载、编译闭包、启动命令、配置与资源所有权。Unity 场景和站端继续使用其现有主机运行方式。

## 2. 设计时的现状事实（问题清单）

以下 N 表示 DiffAgent2 新版根；O 表示 DiffAgent2 旧版根下的 `diff-dockers/`；E 表示使用者指定的 Exploration 工作区下的 `diff-dockers/`。这三个标记只用于相对文件定位。

- [ ] `N/AGENTS.md:23–33`：本仓库已有编排定位，但 `auto_deployer` 等实际内容未迁入；现有定位不能作为部署已实现的证据。
- [ ] `N/l3-dispatcher-planner/tools/build_ego.sh:3–16`：当前构建以本库包白名单装配外部 catkin 工作空间，包含 `planner_execution`，构建目录必须在源码树之外。
- [ ] `N/l3-dispatcher-planner/bringup/launch/basic_flight.launch:2–17`：入口需要显式地面高度，启动 EGO 与 headless dispatcher，默认输入为标准 odometry/cloud。
- [ ] `N/specs/implemented/inner/l3-execution-seam.spec.md:10–34`：航点执行归 planner 原生 Action；禁止恢复 `mission_executive`、`/mission/task` 和旧目标兼容桥。
- [ ] `E/drone_projects/auto_deployer/deploy/station-host-sim.py:344–347`：参考 L3 编译集合包含 `mission_executive`、`bridges`、`exploration_manager`，不能原样用于新版。
- [ ] `E/drone_projects/auto_deployer/k3s_config/sim/l2-sim.deployment.yaml:43–73`：动力学使用已有 L2 镜像、主机网络和单一外部 ROS master。
- [ ] `E/drone_projects/auto_deployer/deploy/station-host-sim.py:256–272`：Unity 模式保留动力学容器，关闭本地雷达与 3DGS，并挂载 L2 的现行 launch。
- [ ] `E/drone_projects/auto_deployer/deploy/station-host-sim.py:302–327`：Unity TCP/传感器桥接实际复用 L3 镜像，挂载独立 bridge 源码和编译产物；不要求使用单独 Unity 镜像。
- [ ] `E/drone_projects/auto_deployer/deploy/station-host-sim.py:450–462`：`original` 模式复用外部 Unity 进程；`editor` 模式要求用户进入 Play，部署脚本不代为启动原场景。
- [ ] `N/l2-simulator-amd64/projects/unity-simulator/bringup/launch/unity_simulator.launch:2–16`：现有 `original/native` 两种传感器入口已经实现；无需为新版再造一层传感器兼容桥。
- [ ] `N/l4-agent/bringup/ground-station-native/l4-app.sh:35–37,67–136`：L4 由主机服务管理四个进程，服务单元名固定；启动另一工作区会重写同名服务的路径。
- [ ] `O/drone_projects/auto_deployer/k3s_config/sim/l3.deployment.yaml:97–108` 与 E 同名文件：使用已有 L3 镜像，但启动的是其自身 `bringup.launch`，不等于启动 N 的源码。
- [ ] `E/drone_projects/l3-dispatcher-planner/docker/amd64/Dockerfile:1,17–71,74–89`：镜像提供 Noetic、编译与运行依赖，源码和 devel 产物另行挂载。镜像本身可运行与新版依赖闭包兼容是两项事实。
- [ ] `N/l3-dispatcher-planner/ros_packages/dispatcher/dispatcher/ros_adapter/flight_commands_ros.py:18–26`：起降必须有真实订阅者，否则失败。L2 当前默认以空中初始位姿进入动力学，不能据此宣称起飞、降落及返航原点已接通。
- [ ] `E/drone_projects/l3-dispatcher-planner/ros_packages/bridges/scripts/drone_bridge.py:1–40`：图像、点云、状态经独立遥测 Zenoh 会话上传；新版基本飞行入口尚未装配该生产者。

## 3. 目标与约束

- **目标**：形成基于已有镜像的 k3s Unity 启动链，运行当前 L2 源码对应的传感器接入和当前 L3 的 EGO/dispatcher；具备明确的配置、构建、启停、所有权和后续验收步骤。
- **首期能力范围**：已有空中初始位姿下的平移、旋转、站端给定航点执行及停止；具体成功仍由现行技能与 Action 判定。注册表保持现行集合，缺少下游的工具按现行失败路径处理。
- **完整站端范围**：发现/租约/任务控制、图像和点云遥测、日志三条链分别接入并分别报告状态；只打开网页不算完整接入。
- **非目标**：迁入整套 `auto_deployer`、真机部署、自动探索技能、3DGS、改造原 Unity 场景、将 L4 容器化、为运行仿真重新设计 dispatcher。
- **硬边界**：不新增新旧任务接口转接器；不恢复退役 Mission 协议；不以旧 L3 进程代跑新版任务；已被替代的目标侧入口直接删除。
- L2 与 L4 保持独立 Git 所有权，不复制为父仓库源码，不更新 gitlink，不在本轮提交或推送其内容。
- 本次只实现源码；构建、运行及机器配置待运行轮次执行。不运行测试、不做验证性验收、不读取测试文件。

## 4. 方案决策

### 4.1 运行布局与镜像选择

首期沿用单台 `station-host`、amd64、k3s/containerd、`hostNetwork: true`、ROS 回环地址。所有 ROS Pod 固定到同一个显式配置的节点，避免 hostPath 与 localhost 跨节点失效。各 Deployment 使用单副本和 `Recreate`，避免滚动更新制造重复 ROS 发布者。

| 组件 | 运行位置 | 镜像基线或入口 | 职责 |
|----|----|----|----|
| `sim-roscore` | k3s Deployment | `image-registry/l2-uav-simulator-amd64-sim/amd64-ubuntu20.04-cuda0.0.0` | 显式启动唯一 ROS master |
| `l2-sim` | k3s Deployment | 同一 L2 镜像 | SO3 控制、四旋翼动力学、odometry；关闭本地雷达及 3DGS |
| `sim-unity` | k3s Deployment | `image-registry/l3-dispatcher-planner-real/amd64-ubuntu20.04-cuda0.0.0` | ROS-TCP Endpoint 与已有 Unity 传感器桥；沿用 E 的实际镜像选择 |
| `sim-l3` | k3s Deployment | 同一 L3 镜像 | 运行新版构建产物、EGO、dispatcher，显式覆盖参考镜像的旧启动入口 |
| Unity bridge/L3 编译 | k3s Job | 同一 L3 镜像 | 分离编译目录、执行期限与完成记录 |
| `sim-telemetry` | k3s Deployment，完整站端阶段接入 | 同一 L3 镜像与经准入的遥测代码 | ROS 数据上传到站端，不持有任务控制面 |
| 日志采集和中继 | k3s，完整站端阶段接入 | `image-registry/fluent-bit:3.1-amd64`、`image-registry/l4-visualizer/lx-log-relay:amd64` | 按现行日志契约上传本栈日志 |
| Unity Editor/Player | 主机图形会话 | 原有 Unity 工程或明确选择的场景包 | 场景渲染与传感器；不放入 ROS Pod |
| L4 四服务 | 主机服务管理器 | 当前 `l4-agent/Makefile` | 控制台、站端桥、可视化与 VLA |

`image-registry` 是角色占位。实际仓库地址与镜像引用从主机本地配置解析；初次准入记录实际 digest，编译和运行使用同一镜像身份，不只依赖可移动的 `latest`。优先使用已运行的现有镜像，不预设重建镜像。

Python/ROS ABI 与新增 C++ 依赖属于新版部署的准入项：后续明确许可后，在所选镜像中核实当前源码所需解释器、ROS Python 模块、Zenoh、Eigen/PCL 等依赖。发现缺口再形成镜像派生变更，不能静默使用另一工作区的 Python 环境或旧 devel 产物。

### 4.2 目录架构与命名

按当前默认编辑范围，首期部署资产放在 L3 的 bringup 下；它是组合启动入口，不进入 dispatcher 领域包。源码仓库路径通过父目录定位独立 L2、L4，允许本地配置显式覆盖。

```text
specs/proposed/runtime.spec.md
specs/proposed/inner/unity-k3s-bringup.spec.md
doc/l3-dispatcher-planner/iteration/design-k3s-unity-bringup.md
l3-dispatcher-planner/
  bringup/k3s/unity/
    README.md
    runtime.defaults.env
    roscore.deployment.yaml
    dynamics.deployment.yaml
    sensors.deployment.yaml
    l3.deployment.yaml
    compile.job.yaml
  tools/
    station-host-sim.py
    build_ego.sh
  .artifacts/k3s-unity/           # 被忽略，配置渲染、制品、日志与状态
```

| 类型 | 命名规范 | 示例 |
|----|----|----|
| 主机操作入口 | 实体前缀、连字符 | `station-host-sim.py` |
| k3s 模板 | 职责名 + 资源类型 | `sensors.deployment.yaml` |
| 配置键 | 大写下划线、单位明确 | `SIM_READY_TIMEOUT_S` |
| 临时制品 | 单一工作区根下按职责分目录 | `l3/`、`unity-bridge/`、`rendered/` |
| ROS 收发代码 | 保持现行适配层边界 | `ros_adapter/*_ros.py` |

实施前在中央 `specs/` 新增运行时根提案与叶提案，定义资源所有权、镜像、配置和生命周期；不把部署责任塞进 dispatcher 根。当前方案不创建空目录、占位代码或无消费者包。

### 4.3 配置及工作区所有权

配置解析顺序为已跟踪的非机器默认值加被忽略的根 `.local.env` 中明确声明的覆盖键。只有一个解析器读取白名单并产生有效配置，禁止 shell `source` 执行配置内容；未知键、非法类型和缺失必填项显式报错。既有无关 `.local.env` 键不传入 Pod。

必需字段：目标节点、namespace、栈身份、ROS master 端口、Unity TCP 地址/端口、L2/L4 源码根、镜像引用、Zenoh router、地面高度与初始位置。默认 `SIM_UNITY_SENSOR_SOURCE=original`、`SIM_UNITY_MODE=editor`，不默认启用探索或 tracking。

- 首期 namespace 沿用 `sim`，采用同一主机仿真栈独占策略。端口可配置；默认值参考 E 的 master `22311` 与 Unity `10000`。
- namespace 不隔离主机网络端口。启动前同时检查 namespace 所有者与端口占用；已有其他工作区栈时拒绝接管，明确报告归属。不得自动停止另一工作区。
- 所有资源携带工作区身份标签；身份由规范化工作区位置派生，配置指纹另存。位置摘要不是 ROS 任务编号，也不进入 RPC payload。
- `down` 仅删除属于本工作区的已登记资源，不删除整个 namespace、共享 CRD、别人的 Job 或主机数据。
- 不复制 E 的实际 `LX_STACK_ID`；新栈使用独立 `sim/<instance>`。L3、遥测和日志三平面必须使用同一栈身份与 router。
- L4 身份与服务配置仍由其 config-db 负责，`.local.env` 不成为 L4 身份参数的第二来源。

### 4.4 构建与挂载

L2 动力学优先使用现有镜像内的编译产物，挂载当前 L2 launch/config。记录镜像摘要与 L2 源码版本；若源码所要求接口与镜像实际产物不一致，先编译 L2 或选择匹配镜像，不能仅用新 launch 掩盖旧二进制。

Unity bridge 编译 Job 仅纳入 L2 的 `ros_tcp_endpoint` 和 `unity_simulator`，产物独立保存。运行时复用同样的容器路径，确保 Python 安装路径和 catkin 的绝对引用有效。

L3 编译 Job 直接调用当前 `tools/build_ego.sh`，以其包集合为唯一构建入口，不沿用参考脚本的 `catkin build mission_executive ...`。建议源码只读挂到 `/source/l3`，构建工作空间挂到 `/work/l3`；两者在编译与运行 Pod 中完全一致，满足现有脚本的源码树外构建约束。产物包含本版 ROS 消息及原生 Action，不能复用 E 的 devel。

构建记录包含镜像 digest、源码内容摘要、消息定义、编译命令、编译/运行路径及配置版本。开始构建先失效旧记录；只有成功完成才生成新记录。`up` 只消费有效记录，不自动安装依赖、不隐式编译。失败 Job 日志保留，源代码只读；生成物目录单独可写。

L2 控制器与 L3 都使用 `quadrotor_msgs/PositionCommand`。两边消息定义及实际生成版本必须一致；不能给 L2 全局叠加一个缺少 SO3 消息的新消息包，也不能让 L3 加载缺少新版 Action 的 L2 消息包。每个 Pod 保留自己的包集合，按共享 wire 类型核实兼容性；不建立消息转换节点。

### 4.5 接口与行为

任务链固定为 L4 → 现行 Zenoh RPC/租约 → dispatcher 技能 → `/planner/execute_waypoints` → EGO → `/setpoint_cmd` → L2 SO3/动力学 → `/ekf_quat/ekf_odom`。

Unity 输入仍由现有 L2 原场景桥提供 `/drone_0_visual_slam/odom`；原 RGB、深度、雷达经该桥输出标准话题。新版部署只选择现有 `original` 入口，不另增新旧接口转换层。`native` 参考场景作为明确选择的第二运行模式，不与原传感器并行启动。

L3 使用 `basic_flight.launch`，共享 `/planner_execution` 参数由既有 EGO launch 装载，`ground_z` 显式传入。L3 容器显式执行当前 launch，不落入镜像复制的旧 bringup，也不装配 Mission、在线探索或旧任务编号。

`/command/emergency_stop` 与 Action 取消保持现行语义：停止旧输出、保持接管、动态停稳；部署脚本不发布“成功”结果，不靠 Pod Running 推断任务成功。`/sim/reset` 的单独动力学重置不暴露为新版正式 reset；正式 reset 必须停止并重建整个本栈，使 dispatcher 原点、Action 关联和 planner 状态一起失效。

当前仿真初始高度不是地面高度。默认空中初始化不产生有效起飞原点；起降消费者缺失时明确失败，返航无原点时明确失败。完整起降需要后续单独设计真实动力学消费者及其状态闭环，不为演示伪造订阅者或原点。

### 4.6 操作入口与生命周期

已实现 `python3 l3-dispatcher-planner/tools/station-host-sim.py <action>`，本次没有实际执行。
组合动作 `start/stop` 将业务栈和本站端顺序装配，单项动作如下。

| action | 行为 |
|----|----|
| `render` | 读取配置、校验配置结构、生成本地清单；不连接或修改集群 |
| `prepare` | 显式解析镜像身份、准备标定、提交编译 Job；不启动业务栈 |
| `up` | 归属/占用/制品检查 → master → 动力学与 TCP 桥 → 传感器就绪 → 新版 L3；完整站端阶段再接遥测、日志 |
| `status` | 分别报告资源归属、进程/Pod、输入新鲜度、任务面与数据面状态，不修改环境 |
| `down` | 要求活动任务结束或取消、释放本机空闲租约，停止本工作区资源；其他 owner 的租约或活动任务阻止关闭 |
| `reset` | 执行同样的关闭约束后整体 down/up，生成新运行实例；不只重置动力学 |
| `station-start/stop` | 显式管理当前工作区 L4；检查固定服务单元路径和监听端口归属 |

`original` 模式下 Unity 由用户打开原工程并进入 Play；`up` 等待真实数据并有限超时，不能自动修改场景、关闭原组件或重复启动 Player。独立 `native/player` 模式只管理本入口启动且登记的 Player 服务；退出保留日志与场景包。

L4 已有服务指向其他检出时，默认拒绝重写；允许继续使用已有站端必须显式选定，状态明确显示其源码归属，不能声称运行了当前 L4。站端退出不由 Pod 生命周期隐式触发。

启动失败记录阶段和诊断，只清理由本次启动新建且属于本栈的资源，不撤销启动前已存在的实例。运行期间的自动重启由 k3s 负责；重启不恢复旧 RPC 调用或旧 Action。

### 4.7 就绪、日志与可视化

- master 就绪采用 ROS XMLRPC；其他组件不允许自动另起 master。
- 动力学就绪检查持续且新鲜的 odometry。Unity 就绪分 TCP Endpoint 进程与真实 RGB/深度/cloud 两级；避免空 TCP 连接探针对 ROS-TCP-Endpoint 的既有 Unity 连接造成干扰。
- 新版 L3 就绪应覆盖 planner 原生 Action、执行状态新鲜度与控制面初始化；具体探针只读，不申请任务租约或发送运动。
- 使用来源既有 `original` 时间语义时，RGB/深度以接收时间标记，不能宣称采样时戳严格同步；此模式的精确图像与位姿绑定是单独验收项。
- 完整站端需准入 E 的现有遥测生产逻辑，拆为独立 ROS 收发包/进程，遵循本库适配边界；不引入旧 Mission 控制接口。实施前在 `specs/` 补齐站端遥测契约，核对当前 L4 消费者的消息格式、采样时戳、标定、限流和 presence。
- 遥测候选通道为 `meta`、`drone_status`、`camera`、`depth`、`cloud`；地图/轨迹按实际新版生产者接线后才启用。未知电池/飞控模式保持未知，不伪造为可飞。
- 日志复用现有 fluent-bit 与 relay 镜像，限定本 namespace/工作区标签；只投递 `lx/<stack-id>/logs`。任务、遥测、日志各自会话和状态独立。按现行日志契约由 visualizer 展示。

## 5. 迁移映射表

| 来源 | 新目标 | 动作 | 原因 |
|----|----|----|----|
| E 的 `roscore.deployment.yaml` | `bringup/k3s/unity/roscore.deployment.yaml` | merge/rewrite | 保留镜像和单 master，参数化归属与端口 |
| E 的 L2 清单与 Unity 模式渲染 | `dynamics.deployment.yaml` | rewrite | 保留已有动力学容器，直接选 Unity 配置 |
| E 的 `bridge_manifest` | `sensors.deployment.yaml` | rewrite | 保留实际使用的 L3 镜像及 L2 bridge，独立制品路径 |
| E 的 L3 Deployment | `l3.deployment.yaml` | rewrite | 显式运行新版 launch 与 Action 产物 |
| E 的 `compile_job` | `compile.job.yaml` 与主机入口 | rewrite | 保留 k3s Job 方式，调用新版编译闭包 |
| E 的 setup/up/down 与 Makefile | `tools/station-host-sim.py`、根 `Makefile` | merge/rewrite | 单解析器、所有权、阶段化生命周期；根 Makefile 按使用者明确要求提供操作入口 |
| L2 的 Unity 和动力学源码 | 保持独立 L2 检出 | reuse | 通过运行镜像与源挂载使用，不复制源码 |
| L4 原生生命周期 | 保持独立 L4 检出 | reuse | 显式调 Makefile，补编排侧归属检查 |
| E 的 ROS→Zenoh 遥测生产者 | 后续 `ros_packages/telemetry_bridge/` | rewrite | 完整站端必需，依契约准入后只保留现行消费者闭包 |
| E 的 fluent-bit/relay 配置 | 后续 `bringup/k3s/unity/logs.yaml` | rewrite | 复用镜像与日志协议，限制采集范围 |

## 6. 删除清单

本次新增部署和遥测实现，没有替换现存生产代码。以下来源内容不进入目标侧：

| 不迁入或替换后删除的内容 | 理由 |
|----|----|
| Mission 编译目标、旧 `bringup.launch` 及任务转换节点 | 与现行执行缝契约冲突 |
| 3DGS 容器及其 socket/共享内存配置 | Unity 单传感器后端，不复制无消费者资源 |
| 自动探索 YOLO、`exploration_manager` 及旧验收脚本 | 不属于本次启动链；新版能力未准入 |
| 指向来源工作区的路径、固定栈身份、过期挂载 | 目标运行必须可归属到新版 |
| 仅用于另一后端的 GPU/privileged/hostIPC 设置 | 按各容器实际需求保留，不能整份照搬 |
| 旧版原地 `/sim/reset` 操作入口 | 避免重置动力学却保留旧任务、地图或返航原点 |

来源仓库本身不删改；目标侧不保留兼容别名或注释桩。

## 7. 实施步骤（P0/P1/P2/P3）

### P0 — 契约、配置与资源归属

- 范围：运行时根/叶提案、当前方案、配置键、路径与命名规范、镜像引用和工作区归属。
- 行为不变式：既有 L3 RPC/技能/Action 不变；L2/L4 仓库所有权不变。
- 后续许可后的验收：配置渲染、必需键失败、其他工作区资源拒绝接管。
- 回退：删除本次尚未投入运行的配置和清单，不操作已有栈。

### P1 — 基础容器与制品准备

- 范围：复用现有镜像，master/L2/Unity bridge 清单及 Unity/L3 编译 Job。
- 行为不变式：唯一 master、唯一 odometry/cloud 生产者、编译与运行路径一致。
- 后续许可后的验收：镜像内运行时依赖、共享消息一致性、新版构建、制品过期拒绝；不以参考工作区结果替代新版结果。
- 回退：仅删除本次 Job/制品记录，保留源码和来源镜像。

### P2 — 新版 L3 与 Unity 的运动闭环

- 范围：新版 L3 launch、配置与启停入口，original Unity 接入；同步更新 rest 索引与 R03/R05 的本轮证据/剩余条件。
- 行为不变式：任务仍经现行 owner 门与 Action；停稳前不准入新运动；取消不停止常驻传感器；正式 reset 整体重启。
- 后续许可后的验收：平移、旋转、航点、取消与急停；无起降消费者/无返航原点明确失败；断开 Unity、定位过期和重启不产生假成功。
- 回退：停止新版拥有的资源，再显式回到已知可用的参考工作区；不混用两版 L3 二进制。

### P3 — 完整站端与可观测性

- 范围：中央站端遥测契约、当前消费者对应的 ROS→Zenoh 数据生产、日志采集；显式接入当前 L4。
- 行为不变式：任务/遥测/日志面分离；相机与标定一致；不更改任务结果语义；固定主机服务归属明确。
- 后续许可后的验收：console 获取租约和调用、visualizer 实时图像/点云/日志、故障与陈旧状态显示、停止与资源释放。
- 回退：停止本轮遥测/日志组件，恢复明确记录的站端服务归属；不得自动接管另一工作区。

P0–P2 交付基础仿真启动链，P3 才构成完整站端运行链。未完成 P3 不得宣称页面已完整接入 Unity 数据。

## 8. 验收标准

统一声明：依 `AGENTS.md` §9，本轮不执行测试、构建、语法门禁或验证性验收，不读取测试文件。以下均为取得明确许可后的待办，不是通过记录。

- [ ] 配置只在本地保存机器值；镜像 digest、工作区身份、源码与制品记录可追溯。
- [ ] 所有 ROS Pod 在指定节点使用同一 master；重复实例、其他 owner 与端口冲突均拒绝启动。
- [ ] Unity 原场景不被修改；原传感器桥与本地雷达/3DGS 不争用标准话题。
- [ ] 镜像与生成消息支持当前 L3；运行的是新版包和原生 Action，无旧 Mission 节点。
- [ ] 实际 odometry、图像、深度和点云持续更新，数据坐标与时间语义明确。
- [ ] 平移/旋转/航点以真实 Action 结果和停稳完成；取消、断连、超时与旧结果处理符合现行契约。
- [ ] 起降和返航缺少物理条件时按契约失败，初始空中状态不生成虚假原点。
- [ ] down/reset 不影响其他工作区，活动任务与租约检查完整，Unity 外部实例保持其 owner 管理。
- [ ] 完整站端阶段明确展示任务、遥测和日志状态；原场景接收时戳不冒充严格同步采样时戳。
- [ ] 每一阶段的运行证据归本次实际源码/镜像/配置；R03/R05 未满足既有可删除条件时继续保留。

## 9. 风险与对策

| 风险 | 影响 | 对策 |
|----|----|----|
| 参考镜像可运行，但新版依赖有所增加 | 构建或 Python 导入失败 | 先复用，许可后核实依赖；确有缺口再增量派生镜像 |
| devel 内存在绝对路径和版本化消息 | 误加载旧源码或 wire 类型不一致 | 固定编译/运行挂载路径；按源码、镜像和消息指纹隔离产物 |
| hostNetwork 与固定 L4 服务名 | 不同工作区争用服务与端口 | 首期独占、明确 owner、拒绝自动覆盖 |
| original 深度为 JPEG 灰度换算且接收时戳 | 精度和图像位姿对应受限 | 保留模式真实语义；运行阶段专项确认，不通过改标签伪造精度 |
| 地面高度、出生高度和原场景原点不同 | 起降/返航/贴地行为错误 | 独立配置并按场景确认；不把初始高度当 ground_z |
| 基础控制面可用但站端无数据 | 页面空白被误判为整体不可用或整体已完成 | P3 明确补数据与日志生产者，三平面分别显示状态 |
| 来源 spec 尚未在新版采纳 | 将外部实现习惯误当权威 | 新增中央提案并逐项对齐，不复制整套来源 spec |

## 10. 修改点清单汇总

最初设计轮次只新增本文；本次按使用者指令接入以下实施清单，运行状态见文末。

| 文件或目录 | 动作 | 说明 |
|----|----|----|
| `specs/proposed/runtime.spec.md` | 新增 | k3s 部署、配置与资源所有权的根提案 |
| `specs/proposed/inner/unity-k3s-bringup.spec.md` | 新增 | Unity 运行模式、容器职责、生命周期与制品规则 |
| `l3-dispatcher-planner/bringup/k3s/unity/` | 新增 | 清单、非机器默认配置与简体中文运行说明 |
| `l3-dispatcher-planner/tools/station-host-sim.py` | 新增 | 配置、渲染、prepare/up/down/reset 与归属检查 |
| `l3-dispatcher-planner/tools/build_ego.sh` | 复用，按实际需要最小调整 | 唯一新版构建包清单，供 Job 调用 |
| `l3-dispatcher-planner/README.md` | 更新 | 补 k3s 入口，并同步修正与现行 Action 不一致的启动描述 |
| `doc/l3-dispatcher-planner/rest/README.md` 与保留项台账 | P2 实施时更新 | R03/R05 的实现证据、未验收状态与剩余条件 |
| 中央站端遥测提案、`ros_packages/telemetry_bridge/`、`logs.yaml` | P3 已按提案接入代码，未运行 | 完整可视化链，不成为任务协议兼容层 |

本轮未提交、未推送、未安装依赖、未部署，也未改变现有 Unity、L2、L3 或 L4 运行状态。

### 本次实施补充

使用者已要求按本方案执行代码优化，本次执行 P0–P3 的代码闭包。统一入口增加
`start/stop` 组合动作，分别组合业务栈与当前站端；单独 `up/down` 保留。清单使用
JSON（YAML 子集）以便主机解析无需额外 PyYAML。共用资源骨架，职责模板只声明
本组件实际参数，避免重复所有权与挂载实现。

P3 遥测仅重写当前消费者实际使用的 meta/status/RGB/depth/cloud，删除来源中的
轨迹、场景图、tracking、旧任务消息依赖；源码不触碰独立 L2/L4。日志采集由同 Pod
relay 接收，采集路径只匹配本工作区的业务 Pod；无需共享集群 RBAC。
参考 L3 镜像的 Dockerfile 使用 Focal 系统 Python；prepare 按本仓库实际导入闭包
检查依赖，缺失时报告具体模块与错误，运行时不安装。不用 Python 版本号代替
实际源码与依赖兼容性判定。

本次不执行测试、构建、语法门禁或部署。代码交付后仍须获准构建并接入实际 Unity
场景；完整运行与动态停止证据保持未验收，R03/R05 不关闭。

### 2026-10-13 参考启动链收敛方案（先方案后改码）

使用者再次明确参考工作区的完整 k3s 流程及既有容器可用，应以这些容器为基线。
只读依据：参考 Makefile 的 sim-prepare/up；station-host-sim.py 的 compile_job
与 bridge_manifest；station-host-deploy-sim.sh 的运行时选择；L3 Dockerfile 与
wheelhouse 中的 cp38 依赖。它们使用现有镜像与挂载源码，不预先构建新版镜像。

本次优化决定：

1. 删除上一轮新增但没有真实缺口依据的 runtime-image 配方及构建说明。
2. 删除 prepare 的 Python >= 3.10 人为版本门槛，保留系统解释器默认值；依赖
   准入检查导入真实 headless 入口、飞行/VLA 装配和遥测闭包，输出具体失败原因。
3. 本地默认配置使用 image-registry 角色加参考镜像后缀，由 `.local.env` 的
   SIM_REGISTRY 解析完整引用，避免重复手工维护四个镜像；单镜像可显式覆盖。
4. 对齐参考脚本的 kubectl/crictl 调用与 containerd/docker 存储选择，不把
   sudo k3s 命令权限当作参考主机已具备的前提；保持镜像摘要固定和工作区归属。
5. 仍重新编译本仓库 L3，不复用参考工作区 devel；不迁 Mission 或探索任务。

依赖缺口只在获准构建后按具体错误处理，不为尚未发现的缺口预设派生镜像。
这次只修改启动实现与文档，不构建、不运行测试或探针，不改变现有部署。

### 2026-10-13 Make 操作入口方案

使用者明确要求 make 操作，本次覆盖默认 L3 编辑范围，在编排仓库根新增
Makefile。它只调用现有主机启动器，不新增配置源或另一套部署逻辑。
`sim-prepare` 编译；`up/down/status` 管理完整链；`sim-up/sim-down/sim-status/
sim-reset` 操作业务栈；`station-setup/station-up/station-stop/station-status`
操作当前 L4。默认目标显示帮助，多目标串行执行，禁止并发启停。
同步启动说明和 L3 README 为 make 命令，保留 Python 作为实现入口。
本次不执行 make、构建、测试或部署。

本次按上述方案交付：已移除版本门槛和 runtime-image 文件，默认镜像角色解析、
具体导入错误报告、sudo kubectl/crictl 与 docker 存储选择已写入启动器。
未执行 prepare、镜像拉取、构建或依赖探针；引用参考流程属于源码对照依据，
不记为运行通过。

### 本次代码交付记录

- P0：中央 runtime 根、Unity 装配及站端遥测叶提案；白名单配置解析、主机本地
  活动配置快照、namespace/资源 owner 与 UID 删除前置条件已接入。
- P1：职责清单骨架、JSON 渲染、digest 固定、L3/Unity 编译 Job、L2 镜像实际
  PositionCommand MD5 核对及源码摘要记录已接入；失败 Job 不产生有效记录。
- P2：本仓库 basic_flight.launch、阶段化 up/down/reset、原场景 Play 接入与
  明确 Player 用户服务管理已接入。关闭不绕过动态停稳和现行租约协议。
- P3：独立 telemetry_bridge、限频/带宽与最新值槽、RGB/深度/cloud/status
  编码、fluent-bit/relay、当前 L4 的服务归属及相机外参同步已接入。
- 操作入口：`render/prepare/start/status/stop` 以及单独的
  `up/down/reset/station-start/station-stop`，完整用法归 bringup 中 README。

编译、测试、语法门禁、运行探针、镜像构建和部署均未执行。没有 Unity 或站端
运行证据；当前镜像解释器、实际场景、机器配置与 R03/R05 的动态证据仍须在
明确许可后的运行轮次落实。中央提案保持 proposed，方案不标记验收完成。

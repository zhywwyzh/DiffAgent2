# L3 源码远端投放与 drone 原生编译方案

> 摘要：由 station-host 投放 DiffAgent2 新版源码，在 drone-host 的 k3s 中使用
> ARM64 镜像原生编译，保留可追溯制品，再显式启停新版 L3。
> 借鉴 DiffAgent2 旧版的交付机制，按新版构建闭包和执行契约重新实现。
> 本文是过程方案，接口已登记到 `specs/proposed/`；代码已接入，没有运行证据。

## 0. 元信息

| 项 | 值 |
|----|----|
| 日期 | 2026-10-13 |
| 目标路径 | `l3-dispatcher-planner/tools/`、`l3-dispatcher-planner/bringup/k3s/real/` |
| 状态 | in-progress；P0–P2 代码接入，未编译与验收 |
| 关联文档 | [Unity 装配方案](design-k3s-unity-bringup.md)、[执行缝](../../../specs/implemented/inner/l3-execution-seam.spec.md)、[运行时提案](../../../specs/proposed/runtime.spec.md)、[待迁依赖台账](../rest/dispatcher-deferred-dependencies.md) |

## 1. 背景与动机

操作者需要将 station-host 当前工作区代码（包括未提交修改）投放到 drone-host，
控制设备自行编译，并取得真实结果。后续可以启动或更新新版 L3，而不必手工 SSH
复制命令，也不用为每次源码调整重新构建业务镜像。

首期完整交付包括远端投放、编译与端侧 L3 启停，按 P1/P2 顺序实现，不能只完成
编译就宣布首期交付结束。设备上已有 DiffAgent2 旧版部署；新版必须在独立工作空间落地。
L0 传感器、L1 定位与 L2 飞控控制器视为已有外部基础设施，明确其输入输出与所有权，
不把“L3 能启动”表述为“新版已经具备全套真机一键安装”。Unity 仿真保持独立入口。

## 2. 现状事实（问题清单）

以下路径以 DiffAgent2 新版根目录为基准；标注“DiffAgent2 旧版”的路径以
`OLD_REPO_ROOT` 为基准，该值只从被忽略的 `.local.env` 读取。

- [ ] `Makefile:8`、`:35`：现有 `sim-prepare` 委托本机仿真启动器，没有远端目标参数。
- [ ] `l3-dispatcher-planner/tools/station-host-sim.py:413`：prepare 在本机集群构建；
  `:840` 的命令入口没有远端交付或设备编译动作。
- [ ] `l3-dispatcher-planner/tools/build_ego.sh:9`：已有 EGO、Elastic、执行库、dispatcher
  和公共消息的明确构建闭包，`:16` 可选遥测；`:20` 默认 `catkin_make -j2`。
  不能直接复制 DiffAgent2 旧版的全树 `catkin build` 后声称行为一致。
- [ ] `l3-dispatcher-planner/bringup/launch/ego.launch:13`：
  `fsm/realworld_experiment` 当前写死为 false；真机配置入口尚需核对并显式装配。
- [ ] `l3-dispatcher-planner/bringup/launch/basic_flight.launch:2`：地面高度必须显式配置；
  `:4`、`:5` 使用定位和点云输入，不能把仿真初始位姿作为设备侧缺省值。
- [ ] DiffAgent2 旧版 `diff-dockers/drone_projects/auto_deployer/provisioner/steps/base.sh:54`：
  `base_deliver_l3` 用 rsync 投放 ros_packages 和 bringup，保留远端制品。
  `:117` 通过 SSH 调用设备编译脚本，`:150` 的 recompile 负责 down、compile、up，
  不包含源码投放。
- [ ] DiffAgent2 旧版 `diff-dockers/drone_projects/auto_deployer/compile/drone-host-compile-on-jetson.sh:266`：
  设备原生 catkin 构建；`:345` 设置期限，`:369` 起挂载源码和持久制品，
  `:398` 读取容器真实退出码。其 8 并发、14 GiB、功耗要求为旧部署配置，不能视为所有设备通用值。
- [ ] DiffAgent2 旧版 `diff-dockers/drone_projects/auto_deployer/deploy/drone-host-deploy-real.sh:63`：
  已有 L0/L1/L2 分组；`:708` 还包含旧 mission 等运行单元，新版不能整份应用。

## 3. 目标与约束

- **目标**：一个 station-host 命令完成源码快照投放并取得设备编译结果；断线可查；
  编译失败不破坏上一个成功版本；之后按显式命令启动、关闭或切换新版 L3。
- **本轮不做**：修改业务技能/RPC；迁入旧 mission；修改独立 L2/L4 仓库；
  安装操作系统/k3s/驱动；自动升级固件、修改功耗模式、解锁电机或起飞；
  将旧部署器整体迁入；默认启用 tracking 或 GPU 推理服务。
- **硬边界**：禁止新旧协议转接器；被替代入口直接删除；运维不绕过飞行租约；
  编译成功不等于运行就绪，运行就绪不等于可以飞行。
- **端侧隔离**：DiffAgent2 新版与 DiffAgent2 旧版不得共用宿主机工作空间，包含源码、
  外部启动/编译脚本、配置、制品、日志、锁和状态。允许复用已可用的镜像、k3s 和
  containerd 镜像存储；复用镜像不表示复用旧版源码、catkin overlay 或可写挂载。
- **当前授权**：按方案实施本地代码与文档。未执行远端命令、编译或验收。

## 4. 方案决策

### 4.1 执行位置与目标目录

```text
station-host：make → station-host-drone.py
                        │ SSH 控制、rsync 源码快照、日志回传
drone-host：             ▼
                 drone-host-runtime.py
                        │ 本地锁、持久状态、k3s 资源归属
                        ▼
                 ARM64 编译 Job → 成功制品 → 显式启动 L3
```

拟新增目录如下；未实现前不创建脚本占位文件。

```text
l3-dispatcher-planner/
  tools/
    station-host-drone.py
    drone-host-runtime.py
    build_ego.sh
  bringup/k3s/real/
    README.md
    runtime.defaults.env
    compile.job.yaml
    l3.deployment.yaml
    runtime_probe_ros.py
```

| 类型 | 规范 | 示例 |
|------|------|------|
| 站端可执行入口 | station-host 前缀，声明 Entity/Invoked | `station-host-drone.py` |
| 设备入口 | drone-host 前缀，声明 Entity/Invoked | `drone-host-runtime.py` |
| ROS 探测模块 | ROS 收发集中于 `_ros.py` | `runtime_probe_ros.py` |
| Python 类/函数 | PascalCase / snake_case | `BuildRecord` / `start_build` |
| Make 目标 | drone 前缀，动作显式 | `drone-prepare` |
| 运维标识 | 发布内容摘要、构建尝试标识 | `release_digest`、`build_attempt` |

运维标识只关联源码、Pod、日志和制品，不进入 RPC 或业务任务身份。
新入口直接实现新版流程，不调用 DiffAgent2 旧版脚本，也不为 `base.*` 保留别名。

### 4.2 操作入口

以下命令已接入代码，**尚未编译或运行验收**，在 DiffAgent2 新版根目录执行。现有 `up/down/status`
继续表示本机仿真，不依据环境变量悄悄改成真机操作。

| 命令 | 设计语义 |
|------|----------|
| `make drone-plan` | 本地解析配置，展示交付范围、目标与动作，不连接设备 |
| `make drone-sync` | SSH 预检后投放当前工作区快照；不编译、不停服务 |
| `make drone-build` | 编译明确选定的已投放快照；L3 运行中拒绝，不隐式停止 |
| `make drone-prepare` | sync → build；不启动业务 |
| `make drone-up` | 启动明确选定且成功编译的版本；已有不同版本运行时拒绝 |
| `make drone-down` | 满足维护门后，仅停止本工具拥有的 L3 |
| `make drone-deploy` | sync → 维护门 → down → build → up；一次远端互斥事务 |
| `make drone-status` | 查看远端操作、构建、候选/活动版本及输入就绪情况 |
| `make drone-logs` | 查看当前操作与编译日志快照；等待提交结果时持续输出日志 |
| `make drone-build-cancel` | 显式取消当前编译，不发送飞行取消或修改运行版本 |
| `make drone-rollback` | 已关闭新版 L3 后显式启动同配置的前一成功制品 |

根 Makefile 只做委托。组合流程由设备入口持锁执行，不用 Make 依赖列表实现排序，
避免 `make -j`、多个终端或不同 station 同时修改设备。
独立 sync/build/up 使用本地记录中的精确摘要并与设备登记核对，不采用“远端最近一个”。

### 4.3 配置与设备身份

机器配置只放根 `.local.env`，示例仅给变量名和角色占位，不写真实值。

- `DRONE_SSH_TARGET`：已有 SSH 配置中的设备别名；使用 SSH agent/密钥与 known_hosts，
  不关闭主机密钥校验，不传密码命令行。
- `DRONE_REMOTE_ROOT`：设备专用交付目录；拒绝根目录、家目录本身、非自有目录及路径逃逸。
- `DRONE_OLD_REMOTE_ROOTS`：设备上 DiffAgent2 旧版源码与外部部署脚本所在目录的保护清单；
  实际值只放主机本地配置，不能用 station-host 的 `OLD_REPO_ROOT` 代替远端路径。
  首次接入须登记完整目录集合并核对旧版工作负载的 hostPath 和服务 WorkingDirectory。
- `DRONE_NODE`、`DRONE_NAMESPACE`：设备节点与新版专用 namespace；核对远端 cluster/node 身份和 ARM64。
- `DRONE_STACK_ID`：显式 `real/...` 身份，首次登记后固定；与 `sim/...` 分开，不复制仿真配置。
- `DRONE_L3_IMAGE`：现有 `image-registry` 的 ARM64 L3 镜像引用，预检解析并锁定 digest。
- `DRONE_ZENOH_ROUTER`、`DRONE_ROS_MASTER_URI`、`DRONE_ROS_IP`：明确网络角色，
  不从 Unity 参数猜测。ROS1 双向连通所需主机地址必须显式配置。
- `DRONE_BUILD_JOBS`、`DRONE_BUILD_MEMORY`、`DRONE_BUILD_TIMEOUT_S`：按设备资源配置；
  首期并发默认 2，内存预算显式提供，不照搬旧设备资源上限。
- `DRONE_GROUND_Z`、定位/点云主题、世界系与设备状态来源：真机装配输入；
  空间标定和高度阈值沿用新版唯一参数树。

配置作为数据解析并校验，拒绝未知 DRONE 键，不 `source`、`eval` 或拼接用户 shell。
SSH 使用固定入口与结构化请求；rsync 路径保留参数边界。敏感配置不随源码同步，
远端配置单独以受限权限写入；日志和报告不打印认证材料。

### 4.4 投放：当前工作区 → 冻结快照

1. 白名单收集新版 `ros_packages/`、实际使用的 `bringup/launch`、`bringup/config`、
   `bringup/k3s/real` 及构建/设备入口。排除 `.git`、`.local.env`、制品、缓存、
   模型权重和运行地图；不遍历独立仓库。
2. 在 station-host 忽略区生成冻结快照，记录相对路径、文件内容 SHA-256、模式和合法
   内部符号链接；外部/绝对链接拒绝。创建前后核对源清单，源正在变化则要求重试。
3. Git revision 和 dirty 仅用于展示；传输身份以实际快照内容为准，含未提交及白名单内
   未跟踪源码，不因 Git 状态清洁与否漏投文件。
4. rsync 到远端独立 staging 目录；`--delete` 只能作用于该目录，不触及活动版本、
   配置、日志、地图或制品。设备核对完整内容清单后，在同一文件系统原子发布源码目录。
5. 重复投放同摘要可复用；摘要相同而内容不符明确失败。后续编辑本机文件不改变已投放版本。

远端布局相对于 `DRONE_REMOTE_ROOT`：

```text
control/                    # 设备入口的版本化交付及所有权登记
config/                     # 设备本地配置
staging/                    # 未完成传输
releases/<source-digest>/    # 冻结源码，编译和运行均只读
builds/<attempt>/work/       # 本次构建产物，成功封存
builds/<attempt>/record.json
builds/<attempt>/compile.log
state/                      # active/candidate、操作日志、锁
cache/                      # 可选编译缓存；不是成功制品
```

### 4.4.1 新旧工作空间隔离（硬约束）

端侧使用两个互不包含的目录树，角色占位如下，实际路径由本地配置指定：

```text
<旧版工作空间>/              # 已部署内容，由 DiffAgent2 旧版管理
  ...                       # 包括旧版源码与外部启动脚本
<新版工作空间>/              # DRONE_REMOTE_ROOT，全新独立目录
  control/<control-digest>/ # 新版外部编译/启动入口及依赖
  config/
  releases/
  builds/
  state/
  cache/
```

1. 投放前在 drone-host 解析真实路径。新版根目录不能等于、包含或位于任何旧版保护目录内；
   不允许符号链接或 bind mount 别名把新版目录指向旧版目录。对比真实目录、挂载来源与
   文件身份，无法判定时拒绝投放，不只比较路径字符串。
2. 新版根目录首次只能在空目录建立所有权登记；非空且没有匹配登记的目录拒绝接管。
   之后每次投放、编译、启停和清理均核对同一登记及目录边界。
3. 外部脚本全部投放到新版 `control/<control-digest>/`。SSH 和 systemd 使用其绝对路径，
   WorkingDirectory 指向新版根；不覆盖旧版 deploy/compile 目录，不从 PATH 查找同名脚本，
   不修改旧版入口软链接、shell 启动文件或全局启动脚本。活动操作固定控制脚本摘要，
   后续投放不能改写正在执行的脚本。
4. 所有可写 hostPath 都位于新版根目录；配置、编译缓存、制品、运行日志和状态不与旧版
   共用。rsync、chown 和清理范围同样限定于新版拥有的目录，不跨目录修复旧版权限。
5. namespace、Job/Deployment、ConfigMap 和 systemd unit 使用新版专属名称与所有权标记；
   systemd 名称含工作区身份，日志读取按对应 unit/Pod UID，不复用旧版固定任务名。
6. 新版与旧版可以保留同一设备上的完整部署文件，但同一设备控制链只允许一套 L3 活跃。
   首次切换由操作者通过旧版自己的入口停止旧版 L3，新版只检查是否已退出。
   新版 `drone-down` 不停止旧版服务，`drone-deploy` 不自动接管旧版资源。

日常交付范围是新版 L3 源码、L3 启动配置与新版运维脚本。已有 L0/L1/L2 和 ROS master
通过既有运行接口复用，不通过 source 旧工作空间或挂载旧版 devel 来复用。

### 4.5 原生编译与制品身份

- 使用 k3s `batch/v1 Job`，`restartPolicy: Never`、`backoffLimit: 0` 和期限，
  固定设备节点与 ARM64 镜像摘要，不使用 x86 交叉编译或 QEMU。
- 显式覆盖镜像入口，执行新版 `build_ego.sh` 构建闭包。源码挂到 `/source/l3`，
  工作空间挂到 `/work/l3`；运行时使用同一容器路径，避免 catkin devel 的绝对路径失效。
- 镜像内允许存在多个工作空间。新版进程只加载 `/opt/ros/noetic/setup.bash` 和本次
  `/work/l3/devel/setup.bash`；不用 login shell 自动加载旧 workspace，不继承指向旧版的
  `ROS_PACKAGE_PATH`、`CMAKE_PREFIX_PATH`、`PYTHONPATH` 或动态库搜索路径。
  镜像既有旧源码可以存在，但不进入新版编译/运行依赖搜索路径。
  不同 Pod 内可以使用相同容器路径，前提是各自映射独立宿主目录；若实际共处同一容器，
  则必须分设容器内工作空间并保持各自构建/运行路径一致，不覆盖已有 workspace。
- P1 为现有构建脚本增加有界并发参数，默认仍为 2；本机仿真与远端共用这一份包集合。
  不整树构建，不引入旧 mission；遥测按已实现 profile 明确选择。
- 编译 Job 只写本次工作目录；源码只读，默认无特权、无设备节点、无 Docker socket，
  不继承旧脚本 `privileged: true`。依赖镜像内 Noetic、工具链和系统 Python，
  根据实际导入依赖报告缺项，不无依据强制 Python 升级。
- 构建身份包含源码摘要、镜像 digest、CPU 架构、构建脚本/参数、profile 和消息 schema。
  每次尝试单独保存；先前成功制品永不原地写入。首期允许干净构建，后续可用 ccache
  提速；禁止通过硬链接复制后编译污染旧制品。
- 成功条件是编译容器真实退出码 0，并生成指定二进制、Python 消息及 devel 环境。
  保存产物清单/摘要和构建记录后才可标记候选；mtime、PID、SSH 成功或 Job 创建均不代表成功。
- runtime Pod 固定使用该源码目录、工作目录和镜像 digest，制品只读；日志另挂可写目录。
  不通过移动 `current` 符号链接让已有 Pod 在原地换代码。
- 制品保留不自动清理；磁盘不足提前失败并报告占用。后续显式清理仅允许无活动 Pod、
  无构建引用的失败尝试/历史版本，活动和前一成功版本受保护。

### 4.6 远端互斥、断线与失败

设备端是操作状态的唯一写入方。短操作持设备目录锁；编译和 deploy 由设备
systemd 瞬态服务运行设备入口并全程持锁，不让锁依赖 station SSH 连接存活。
瞬态服务、Job、日志与请求记录相互关联，重连查询同一次操作，不重新启动编译。
设备不具备该执行能力时预检报缺项，不静默退化成易随 SSH 退出的后台 shell。

状态区分 `syncing / staged / building / built / activating / active / failed / cancelled / unknown`。
记录阶段、节点、源码/镜像摘要、Pod UID、时间、容器退出码与失败原因。
stdout 输出最终结构化结果，stderr 跟随日志；SSH 断线返回“远端状态待查询”，
不能替远端写入 failed 或成功。Pod deadline 提供终止上限。

设备重启后，基于记录、systemd 状态与 Pod UID 对账；不可判定则 unknown 并禁止 up。
服务不存在但 Job 仍活跃时禁止第二次构建，先接管观测或显式取消。
取消只删除 UID 匹配的本次 Job，等待 Pod 退出后写终态；日志失败与构建失败分别记录。

### 4.7 真机维护门与 L3 运行边界

编译要求设备进入明确的地面维护状态，目标设备控制链上的 L3 已停止，资源预算足够；
不要求 L0/L1/L2 和 ROS master 全部停机，不为编译重投或重启底层服务。
若旧版 L3 仍运行，报告冲突并要求由旧版入口处理，新版不代为停止。
既有底层服务可以继续提供状态观测；剩余内存或 CPU 预算不足时明确拒绝编译，
不擅自停止外部服务腾资源，也不开放飞行期间编译。

P2 启停接入真实设备状态后，维护门必须能证明已着陆、未解锁且状态新鲜。
仅 `/planner/execution_state.stop_confirmed=true` 不够：空中悬停也可能已动态停稳。
已有 L3 还必须无活动调用、无运动输出，当前站端释放租约；运维入口不抢租约、不代发
land/disarm。先核定设备实际 MAVROS 状态/落地消息及 freshness，缺失时不启用自动停机。
全栈已关闭时不能把“没有 Pod”当作落地证据；维护登记须由仍可观测的设备状态建立，
并在维护期间保持禁止飞行的条件，超时或状态失联则停止操作。

新版只拥有自己的 L3 Deployment 与构建资源；按 owner 标记和 UID 操作，namespace
不与旧版独占 namespace 混用。新 namespace 不能隔离 hostNetwork/ROS 输出，因此 up
还须检查同 ROS master 的旧 planner、dispatcher、cmd 发布者和重复 stack presence，
有冲突明确拒绝，不能同时运行两套 L3。

P2 增加真机 profile：把 EGO 的 realworld 参数显式传入，仿真保留原缺省值；
复用 `basic_flight.launch` 与同源 planner 配置，不复制两份算法参数。
启动前读取外部 L0/L1/L2 的定位、点云、控制输入端和消息类型，核对 `PositionCommand`
生成 MD5、单位/坐标系及起降/急停连接；不兼容就拒绝，不添加转换节点。
就绪分别报告 Pod、输入新鲜度、planner 原生 action、task presence 和控制链条件。
没有实际 L2 消费和设备反馈证据时不得宣称整机可飞。

### 4.8 激活与回退

采用 `Recreate`，禁止两个 planner 滚动重叠运行。新版本 ready 前保留旧制品与旧配置，
但不并行启动。成功后原子更新 active 记录，保存前一版本。
构建失败保持旧 active 指针，业务保持已停止状态；不以“回滚”名义自动重新启动设备。
启动失败尝试相同维护门关闭；停止未能确认时保留资源与 active 记录，明确报告故障，
不得假称已停止。显式选择前一成功记录后可再次 `drone-up`，
仍执行维护、输入和消息一致性检查；已失效配置不能直接复用。

## 5. 迁移映射表

| DiffAgent2 旧版机制 | DiffAgent2 新版目标 | 动作 | 理由 |
|----|----|----|----|
| `base_deliver_l3` 原地 rsync | 冻结快照、staging、摘要发布 | rewrite | 避免 Python 源码或制品被运行中覆盖 |
| `base_compile` SSH 前台编译 | 远端持锁服务 + Job + 可重连记录 | rewrite | SSH 失联不丢真实构建状态 |
| Jetson catkin 全树构建 | 共用 `build_ego.sh` 闭包 | rewrite | 不迁旧 mission 和无人消费依赖 |
| `base_recompile` down/build/up | 显式 `drone-deploy` | rewrite | 包含投放，区分维护门与启动结果 |
| `.artifacts` 原地增量产物 | 按尝试封存的制品目录 | rewrite | 保住上一成功制品，可显式回退 |
| provisioner LLM 编排 | 固定状态机 CLI | 不迁 | 用户需要确定性开发操作，不引入额外模型依赖 |
| 旧全栈 bringup overlay | 新版 L3 real profile | rewrite | 外部设备资源仍归原 owner |

## 6. 删除清单

| 删除项 | 理由 |
|----|----|
| 本轮无现存远端入口可删 | 新版尚未实现该能力 |
| 实施中不得新增的旧接口：`base.*`、旧 mission 清单、旧目标消息桥 | 防止兼容入口与过期功能回流 |
| 若实施期出现临时重复包列表或 real 参数副本，同批删除 | 构建闭包与 planner 配置必须各有唯一来源 |

DiffAgent2 旧版是参考，只读；本方案不删除或改写对方仓库内容。

## 7. 实施步骤（P0/P1/P2 分期）

### P0 — 契约与配置定稿

- 范围：在 `specs/proposed/inner/drone-remote-build.spec.md` 定义投放、构建、状态和所有权，
  挂到 runtime 根；明确首期维护条件和 P2 硬件状态来源。整理 real 配置与命令说明。
- 行为不变式：现行业务协议不变；proposed 不代表已交付。
- 验收：获许可后核对父子清单、字段和配置边界；本轮不执行。
- 回退：撤销本轮新增提案，保留现行 Unity 和业务契约。

### P1 — 可独立使用的远端投放与编译

- 范围：实现 plan/sync/build/prepare/status/logs/build-cancel；源码快照、设备执行器、
  Job、制品记录、断线恢复；根 Makefile 加相应 drone 目标；共用构建闭包并支持并发参数。
- 行为不变式：不隐式启停飞行资源；活动/成功制品不覆盖；设备维护条件不满足则拒绝编译。
- 验收：获许可后按 §8 投放、原生构建、失败和断线场景留证。
- 回退：停止本次构建，移除本次拥有的非活动资源；不改旧版或已有运行版本。

### P2 — 新版 L3 真机启停与更新

- 范围：核定维护状态来源、外部依赖边界、real launch 配置、L2 消息 ABI；
  实现 up/down/deploy 和状态就绪报告；同步 R03/R05 台账与索引。
- 行为不变式：无飞行解锁动作；无双 planner；停止不等于着陆；未知状态不执行切换。
- 验收：获许可后在指定设备维护条件下验证启动、关闭、失败留停和显式回退。
- 回退：保留上一成功记录并停止候选版本；经相同维护门显式恢复旧记录。

P1 完成后即可交付“投放代码并让设备编译”，即使 P2 尚无设备侧接口证据；
这只算中间里程碑，首期完成须包含 P2 的端侧启动、关闭与更新。
未实现的命令不以成功空桩出现在 Makefile 中。

## 8. 验收标准

**遵循 AGENTS.md §9：以下是后续许可后的判据，本轮不执行、不读取测试文件。**

- [ ] 工作区未提交修改被准确投放；上传中断不产生可编译的完整版本；路径逃逸被拒绝。
- [ ] 新旧远端根目录相同、父子嵌套、符号链接或挂载别名重合时拒绝投放；未知非空目录不接管。
- [ ] 旧版源码、外部脚本、配置、制品和服务定义在新版完整交付前后不被修改。
- [ ] 新版服务 WorkingDirectory、脚本路径、hostPath、catkin/Python 搜索路径全部指向新版归属；
  镜像内已有旧工作空间不参与新版解析，不因同名 ROS 包加载旧版代码。
- [ ] 编译前后源码、镜像、配置和构建参数可追溯；真实 ARM64 容器退出码决定结果。
- [ ] 编译失败、OOM、超时和取消没有成功记录；上一成功制品字节保持不变。
- [ ] SSH 断线重连观察同一 Job；并发 station、旧 Pod 和设备重启不触发重复构建。
- [ ] 维护条件不成立、状态陈旧、L3 控制冲突或资源预算不足时明确拒绝相应操作；
  L0/L1/L2 正常运行本身不构成拒绝条件，也不触发自动重启。
- [ ] P2 的 L2 消费 MD5/主题与新版一致；旧任务协议未引入；真实配置缺项明确报错。
- [ ] 编译/运行挂载路径一致；切换期间最多一个新版 L3，无旧版并行 cmd 发布者。
- [ ] 启动失败保持停止；显式回退重新核对维护条件；不伪造落地、停稳或飞行完成。

## 9. 风险与对策

| 风险 | 影响 | 对策 |
|----|----|----|
| ARM64 镜像缺当前源码依赖 | 无法编译或导入 | 锁 digest，实际依赖预检；明确缺项后再设计镜像调整 |
| 新旧 quadrotor_msgs ABI 不同 | L2 拒收命令 | 检查生成 MD5 与真实消费者；不建立协议桥 |
| Jetson 内存、存储或温度不足 | OOM、超时、设备负载过高 | 显式预算、低并发、维护编译、资源预检；不自动改功耗 |
| 旧版 L3 或外部服务同主机运行 | 话题冲突、争抢设备 | 核对实际进程/Pod/ROS 发布者；拒绝接管 |
| 新旧宿主目录或外部脚本重合 | 投放覆盖既有部署、误运行另一版本 | 独立根目录、真实路径/挂载核对、专属脚本路径与资源身份 |
| 复用镜像时继承旧 catkin overlay | 同名包解析到旧源码或消息 | 显式入口、干净环境、只加载系统 ROS 和新版 devel |
| catkin 产物含绝对路径 | 编译成功但运行失败 | 编译与运行使用相同容器源码/制品路径 |
| 仅凭悬停判定可以停机 | 失去空中控制 | 将着陆/未解锁维护证据与 planner 停稳分开 |
| P2 所需落地状态来源未确认 | 无法安全自动更新 | P1 可作中间成果；首期仍待 P2，不用静态布尔值冒充观测 |
| 保存版本导致磁盘增长 | 后续投放失败 | 预检空间，显式清理无引用历史，保护活动及上一成功版本 |

## 10. 修改点清单汇总

下表为本轮实施范围；实际代码接入状态与剩余条件见本节末的实施记录。

| 文件 | 动作 | 说明 |
|----|----|----|
| `doc/l3-dispatcher-planner/iteration/design-drone-remote-build.md` | add（本轮） | §0–§10 设计方案 |
| `specs/proposed/runtime.spec.md` | modify（P0） | 登记远端编译叶契约 |
| `specs/proposed/inner/drone-remote-build.spec.md` | add（P0） | 运维协议唯一归属 |
| 根 `Makefile` | modify（P1/P2） | 显式 drone 目标 |
| `l3-dispatcher-planner/tools/station-host-drone.py` | add（P1） | 配置、快照、传输、远端操作观测 |
| `l3-dispatcher-planner/tools/drone-host-runtime.py` | add（P1/P2） | 本地锁、状态、Job、运行生命周期 |
| `l3-dispatcher-planner/tools/build_ego.sh` | modify（P1） | 共用构建闭包及并发参数 |
| `l3-dispatcher-planner/bringup/k3s/real/` | add（P1/P2） | 配置、Job、L3 清单、ROS 探测与说明 |
| `l3-dispatcher-planner/bringup/launch/ego.launch`、`basic_flight.launch` | modify（P2） | 显式真机参数传递，保留仿真默认 |
| `doc/l3-dispatcher-planner/rest/README.md`、`dispatcher-deferred-dependencies.md` | modify（P2） | 部署消费者接入证据与剩余条件；不提前关闭 R03/R05 |

### 2026-10-13 实施记录

上述文件已接入代码；远端提案仍在 proposed，未采纳为已验收能力。
新增 station-host 源码冻结、rsync、设备请求与状态等待入口；drone-host 入口负责目录隔离、
版本化控制脚本、systemd 持锁执行、k3s Job、制品摘要和 L3 Recreate 启停。
构建脚本加入 `L3_BUILD_JOBS`，realworld 参数由 launch 显式传递，仿真缺省仍为 false。

实现细化：首版拒绝源码符号链接；镜像使用完整引用，由设备 k3s crictl 解析摘要；
L2 MD5 通过只握手不发布消息的 PositionCommand 发布端检查；编译期间每隔约 20 秒
重新观察维护状态，失效则终止本次 Job。成功制品保存文件摘要和链接目标，up 前重新核对。
`drone-logs` 返回日志快照，提交等待过程持续回传；新增显式 `drone-rollback`。

没有执行语法检查、构建、测试、远端部署或验收，不能标记 done。
后续需在获许可后证明目标镜像依赖、systemd 权限、ARM64 编译、MAVROS 消息频率/时钟、
L2 握手、停止和租约门、重启/断线/取消行为及真实设备运行闭环。

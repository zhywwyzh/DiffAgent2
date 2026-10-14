# 设备侧 L3 投放、编译与启动

代码已接入，未编译、未测试、未连接设备验收。契约见
[远端部署提案](../../../../specs/proposed/inner/drone-remote-build.spec.md)，过程见
[实施方案](../../../../doc/l3-dispatcher-planner/iteration/design-drone-remote-build.md)。

## 前提与隔离

drone-host 已有 ARM64 k3s、ROS Noetic L3 镜像，以及可用的 ROS master、L0/L1/L2。
本入口只投放和运行新版 L3，不安装或重启底层服务，不执行解锁、起降或自动抢租约。
已有镜像可复用，新版根目录必须独立于旧版源码和外部启动脚本的所有目录。
配置中登记实际旧版远端目录；同路径、父子嵌套、符号链接和 bind mount 别名均拒绝。
不能用 station-host 的旧版路径代替 drone-host 路径。

station-host 需要 Python 3、SSH 和 rsync。drone-host 需要 Python 3、rsync、systemd、
k3s，以及对 `systemd-run`、`k3s kubectl`、`k3s crictl` 的非交互执行权限。
容器需要系统 Noetic、当前 L3 的构建依赖、Zenoh 及 MAVROS 消息定义。
探针订阅已有 MAVROS 状态，不运行第二个 MAVROS 节点。

## 本地配置

在仓库根的忽略文件 `.local.env` 设置；完整键表见 `runtime.defaults.env`。
下列值是角色占位，必须替换为自己的设备配置，不能直接执行。

```dotenv
DRONE_SSH_TARGET=<SSH设备别名>
DRONE_REMOTE_ROOT=<新版端侧绝对目录>
DRONE_OLD_REMOTE_ROOTS=["<旧版端侧源码绝对目录>","<旧版端侧外部部署脚本绝对目录>"]
DRONE_NODE=<本设备k3s节点名>
DRONE_NAMESPACE=<新版专属namespace>
DRONE_STACK_ID=real/<新版独立身份>
DRONE_L3_IMAGE=<现有ARM64镜像的完整引用>
DRONE_ZENOH_ROUTER=tcp/<router地址>:<端口>
DRONE_ROS_MASTER_URI=http://<ROS-master地址>:<端口>
DRONE_ROS_IP=<设备ROS可达地址>
DRONE_BUILD_MEMORY=<设备可用内存预算，单位Mi或Gi>
DRONE_GROUND_Z=<已标定地面高度>
```

并发缺省为 2；内存必须显式配置，构建前要求剩余内存足以容纳预算和额外余量。
默认观测 `/mavros/state`、`/mavros/extended_state`、`/ekf_quat/ekf_odom` 和
`/cloud_registered`。当前执行契约固定 `world` 和 `/setpoint_cmd`。
需要真实、递增、与设备墙钟一致的消息时戳；没有落地/未解锁证据不执行编译或启停。

## 首次投放与启动

先通过 DiffAgent2 旧版自己的入口停止旧版 L3；保留可用的 L0/L1/L2 与 ROS master。
确认设备在地面、未解锁，且维护期间不解锁。随后在 DiffAgent2 新版根目录：

```bash
make drone-plan       # 仅展示本地目标与投放文件，不连接设备
make drone-prepare    # 冻结并投放 L3，然后端侧原生编译
make drone-up         # 使用匹配源码、配置及镜像摘要的成功制品启动
make drone-status
```

源码含白名单中的未提交修改，排除测试、缓存、模型、地图及本地配置。
镜像入口被覆盖，只加载系统 Noetic 和新版 devel；不加载镜像内旧 workspace。
编译和运行的容器路径均为 `/source/l3` 与 `/work/l3`，对应新版宿主目录。
L2 消息不兼容时拒绝启动，不增加消息转换节点。

## 日常更新与关闭

先在站端结束任务、释放当前租约，并确认已落地、未解锁：

```bash
make drone-deploy     # 投放 → 维护检查 → 关闭新版L3 → 编译 → 启动
make drone-down       # 仅关闭本工具管理的新版L3
```

也可分别使用 `drone-sync`、`drone-build`、`drone-up`。
`drone-build` 不自动关闭服务；运行中拒绝编译。L0/L1/L2 不因这些操作被重新投放或重启。
启动失败会尝试同样的安全关闭；无法确认时保留资源和活动记录，明确报告失败，
不把删除成功或 Pod 状态当作设备安全证据。恢复配置后处理故障，再执行 down。

## 断线、日志与回退

```bash
make drone-status
make drone-logs
make drone-build-cancel
make drone-rollback   # L3已关闭时，显式启动同配置的前一成功制品
```

编译由设备 systemd 服务持锁运行；SSH 断开后先查询状态，不重复提交。
等待命令持续输出日志；`drone-logs` 返回当前日志快照，可重复查询。
取消只作用于当前编译 Job，不发送飞行取消指令。worker 已退出而 Job 遗留时，
显式取消会核对 UID 并等待退出，解除未完成操作记录。

设备保留 `state/` 中的操作记录和日志、`builds/` 中的编译日志/产物清单，
源码位于 `releases/`，设备脚本位于 `control/`；这些目录都在新版根目录内。
站端选择与操作报告位于 `l3-dispatcher-planner/.artifacts/drone/`，不纳入版本控制。
每次尝试单独构建，首版不提供跨版本增量产物复用；历史目录不自动删除。
不修改旧版部署，也不自动启动旧版作为回退。

## 当前边界

默认装配 EGO、dispatcher 和其依赖，未装配 tracking 推理服务或新增遥测运行单元。
镜像缺少当前源码依赖、设备缺少新鲜 MAVROS 消息、资源不足或 L2 消息不匹配时明确失败。
Pod 就绪报告定位/点云、原生 action 和任务控制面，不代表实机飞行闭环已验收。

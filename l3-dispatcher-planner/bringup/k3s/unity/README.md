# 本仓库的 k3s Unity 仿真启动

从 DiffAgent2 新版根执行。当前为代码交付，尚未构建、部署或运行验收；以下命令
是实际入口，不是本轮已执行记录。

## 本地配置

编辑编排仓库根被忽略的 `.local.env`，保留已有其它键。尖括号内容替换为本机
实际值，不写回已跟踪文件。配置作为数据解析，不执行 shell 展开。

```dotenv
SIM_NODE=<当前主机的amd64节点名>
SIM_NAMESPACE=sim
LX_STACK_ID=sim/<新版独立实例名>
ZENOH_ROUTER=tcp/<router>:<port>
SIM_REGISTRY=<参考镜像仓库的主机及端口>
SIM_GROUND_Z=<场景world系地面高度>
```

L2、L4 默认取编排仓库根下的独立 `l2-simulator-amd64/`、`l4-agent/` 检出；
`SIM_L2_ROOT`、`SIM_L4_ROOT` 可覆盖，相对路径从编排仓库根解析。
默认 master 端口 22311、Unity 端口 10000，仅同机回环通信；出生位置默认
`(0,0,1)`，可用 `SIM_INITIAL_X/Y/Z` 覆盖，出生高度与地面高度独立。

原场景默认 `SIM_UNITY_SENSOR_SOURCE=original`、`SIM_UNITY_MODE=editor`。
`SIM_UNITY_DEPTH_RANGE_M` 必须匹配原场景 farClipPlane，
`SIM_UNITY_CAMERA_TRANSLATION_FLU` 必须匹配真实相机挂载。内参取 CameraInfo，
相机外参由本入口以 systemd drop-in 同步到本站端；默认参考值不是标定证据。

namespace 若属于参考工作区，须由原工作区停止原栈后再启动新版，或者为新版
配置独立 namespace 和空闲端口。Unity 必须连接相同配置端口。固定站端服务
属于其它检出时，同样由原检出停止，新版不会覆盖。
旧入口停止后若仍留下未登记的 namespace，新入口仍拒绝接管；为新版选择一个
尚未使用的专用名称，例如 `sim-new`，并先释放同机 ROS/Unity 端口。入口不会
自动删除旧 namespace 或为旧资源补 owner 标签。
L4 config-db 必须已有 `lx_station_id`，`lx_zenoh_router` 须与本栈一致。

## 准备与完整启动

首次准备 L4 依赖，已有虚拟环境和两套前端产物时可跳过 setup。
setup、prepare 会安装依赖或构建，在允许该工作后执行。

```bash
make station-setup
make sim-render
make sim-prepare
```

原 Unity 工程须打开并处于 Play；独立 L2 检出不包含完整原场景。确认其 ROS
连接地址/端口后执行：

```bash
make up
```

完整链为 master → 动力学与 Unity TCP → 真实传感器 → 本仓库 EGO/dispatcher
→ 遥测与日志 → 本工作区 L4 四服务。入口有限等待真实 RGB、深度、CameraInfo、
点云、odometry，任务面、数据面和日志面分别报告状态。Unity 在 Endpoint
创建前暂时断连时保持 Play，等待重连。

成功后打开 `http://127.0.0.1:8088`，在“连接无人机”选择配置的新栈并点击
“连接”；可视化位于 `http://127.0.0.1:8391`。探针不申请租约、不发送运动。
起降缺少消费者、返航缺少确认起飞原点时仍按现行契约失败。

## 镜像解释器

默认复用参考启动流程的现有镜像，镜像后缀在 runtime.defaults.env 中声明。
配置 `SIM_REGISTRY` 即可解析四个完整引用；也可逐项显式覆盖 SIM_L2_IMAGE、
SIM_L3_IMAGE、SIM_FLUENT_IMAGE、SIM_RELAY_IMAGE。prepare 固定实际 digest。

ROS、catkin、Python 和已有依赖沿用镜像；默认解释器 `/usr/bin/python3`。
不要求预先构建新镜像或另装 Python 3.10。prepare 编译本仓库源码并导入实际
headless dispatcher、飞行/VLA 装配、生成消息和遥测模块，缺失时报告具体错误。
实际依赖兼容性仍需获准构建后确认，不能将参考栈可运行直接视为新版已验收。
源码和 devel 挂载指向本工作区，不运行镜像内旧 L3，不复用参考工作区产物。

## 查询、关闭与重启

```bash
make status
make down
```

stop 前在 WebUI 取消任务或急停并等待停稳。入口核对 planner、租约和归属，只
删除本栈资源并停止登记的本站端，保留 namespace、编译产物、日志缓冲和外部
Unity。无法确认安全关闭时保留资源并报错。

仅业务栈用 `make sim-up/sim-down/sim-status`，仅本站端用
`make station-up/station-stop/station-status`；`make sim-reset` 整体重建业务栈，
不调用单独动力学 `/sim/reset`。源码或配置变化后执行
`make down → make sim-prepare → make up`；关闭和查询读取活动配置，避免丢失旧栈归属。
制品、清单、日志与状态集中在 `.artifacts/k3s-unity/`，启动拒绝过期产物。

根 Makefile 调用 `tools/station-host-sim.py`，不维护第二套部署逻辑；直接运行
`make` 显示帮助。所有 make 命令均在编排仓库根执行，多目标操作按顺序串行。

启动失败后已经出现控制面、但无法确认停止时，保留资源供站端处理。编译 Job
失败或超时保留在集群，日志见 `compile-l3.log`、`compile-unity.log` 与
`compile-l2-wire.log`；超时前还未生成本地日志时可在对应 Job 查看容器日志。

## 已有 native Player

```dotenv
SIM_UNITY_SENSOR_SOURCE=native
SIM_UNITY_MODE=player
SIM_UNITY_PLAYER_PATH=<已有可执行Player的本地路径>
SIM_UNITY_SCENE_ID=<本地场景标识>
```

Player 须包含 UnitySensorBackend、UnityPlayerBootstrap 和完整场景。
prepare 生成 `config/player.json`，Player 用 `-lx-config` 读取。本入口不下载
未知场景或构建 Unity 工程，只管理带本工作区身份的 Player 用户服务，真实
传感器仍须满足就绪条件。

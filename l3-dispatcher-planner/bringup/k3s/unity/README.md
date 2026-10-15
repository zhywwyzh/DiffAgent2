# 本仓库的 k3s Unity 仿真启动

从 DiffAgent2 新版根执行。2026-10-14 已完成完整 sim-prepare：L3、Unity bridge
编译、Python 3.8.10 导入和 L2/L3 消息一致性检查通过；尚未启动业务栈或运行验收。
构建修复记录见 doc/l3-dispatcher-planner/iteration/design-unity-python38-build.md。

## 本地配置

编辑编排仓库根被忽略的 `.local.env`，保留已有其它键。尖括号内容替换为本机
实际值，不写回已跟踪文件。配置作为数据解析，不执行 shell 展开。

```dotenv
PUBLIC_ZENOHD_ROUTER=tcp/<router>:<port>
SIM_REGISTRY=<参考镜像仓库的主机及端口>
```

`LX_STACK_ID` 默认按工作区生成稳定的 `sim/unity-<owner>`，namespace 默认
`sim-unity-<owner>`，不复用其它工作区的 `sim`。两者可显式覆盖。
`SIM_NODE` 缺省时从 k3s 节点地址识别本机唯一的 amd64 节点；保留同机挂载约束，
不需要人工填写。自动发现需要集群读取权限；显式指定节点时 render 可离线执行。
`SIM_GROUND_Z` 可省略，普通启动和普通航点不依赖地面标定；起飞会话、返回原点
及 VLA 贴地能力仍按各自现行契约检查，不用出生高度伪造地面或原点。
Router 的配置键统一为 `PUBLIC_ZENOHD_ROUTER`，容器内部仍注入 `ZENOH_ROUTER`。

L2、L4 默认取编排仓库根下的独立 `l2-simulator-amd64/`、`l4-agent/` 检出；
`SIM_L2_ROOT`、`SIM_L4_ROOT` 可覆盖，相对路径从编排仓库根解析。
默认 master 端口 22311、Unity 端口 10000，仅同机回环通信；出生位置默认
`(0,0,1)`，可用 `SIM_INITIAL_X/Y/Z` 覆盖，出生高度与地面高度独立。

原场景默认 `SIM_UNITY_SENSOR_SOURCE=original`、`SIM_UNITY_MODE=editor`。
`SIM_UNITY_DEPTH_RANGE_M` 必须匹配原场景 farClipPlane，
`SIM_UNITY_CAMERA_TRANSLATION_FLU` 必须匹配真实相机挂载。内参取 CameraInfo，
相机外参由本入口以 systemd drop-in 同步到本站端。当前默认值沿用用户确认已实验验证的
Exploration 原场景配置；更换场景时需同步对应参数。

namespace 若属于参考工作区，须由原工作区停止原栈后再启动新版，或者为新版
配置独立 namespace 和空闲端口。Unity 必须连接相同配置端口。固定站端服务
属于其它检出时，启动前报告冲突；可执行新版 make down 统一关闭本机站端后再启动。
旧入口停止后若仍留下未登记的 namespace，新入口仍拒绝接管；为新版选择一个
尚未使用的专用名称，例如 `sim-new`，并先释放同机 ROS/Unity 端口。入口不会
自动删除旧 namespace 或为旧资源补 owner 标签。
L4 config-db 必须已有 `lx_station_id`，`lx_zenoh_router` 须与本栈一致。

## 准备与完整启动

首次准备 L4 依赖；只有虚拟环境、全部控制台入口和两套前端产物齐全时才可跳过 setup。
缺少 agent-station-vla 等入口时须重新 setup 同步本地安装。完整启动在创建仿真资源前
检查这些入口，站端开始启动前即登记；部分启动失败后仍可用 make down 清理。
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
编译 Job 默认单任务、内存上限 8192 MiB，与业务容器资源独立。可在根 .local.env
用 SIM_BUILD_JOBS、SIM_BUILD_MEMORY_MIB 调整正整数值；OOMKilled/退出码 137
表示编译容器遭内存终止。重新 prepare 保留 catkin 缓存并重建失败 Job；主机需有
足够空闲内存。

实际依赖兼容性仍需获准构建后确认，不能将参考栈可运行直接视为新版已验收。
源码和 devel 挂载指向本工作区，不运行镜像内旧 L3，不复用参考工作区产物。

## 查询、关闭与重启

```bash
make status
make down
```

stop 前在 WebUI 取消任务或急停并等待停稳。入口核对 planner、租约和归属，只
删除本栈资源，并关闭本机固定的 L4 四服务及已知退役站端单元；即使它们来自其它
检出或缺少启动登记，也不会跳过。存在连接时先安全释放，忙时拒绝关闭。
保留 namespace、编译产物、日志缓冲和外部
Unity。无法确认安全关闭时保留资源并报错。

仅业务栈用 `make sim-up/sim-down/sim-status`，仅本站端用
`make station-up/station-stop/station-status`；`make sim-reset` 整体重建业务栈，
不调用单独动力学 `/sim/reset`。构建输入或镜像变化后执行
`make down → make sim-prepare → make up`；仅运行参数变化时执行
`make down → make up`，启动前按当前参数重新生成遥测和 Player 配置。
关闭和查询读取活动配置，避免丢失旧栈归属。活动资源配置冲突时仍拒绝覆盖。

L3、Unity bridge、L2 消息检查各有独立成功记录；prepare 仅重建输入或镜像、
命令、路径变化的组件。修改 Markdown、启动器停止逻辑或遥测频率不失效编译缓存；
编译资源、Python 3.8 导入、消息一致性和真实构建失败仍明确报告。
首次升级到 schema=2 记录需执行一次 `make sim-prepare`，保留原 catkin 增量缓存；
不自动把旧记录视为新格式缓存。此后重复 prepare 可复用有效组件，不反复创建编译 Job。
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

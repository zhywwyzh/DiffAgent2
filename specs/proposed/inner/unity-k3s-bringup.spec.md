# Unity k3s 装配契约

Status: proposed — 待评审，尚未采纳
Contract-ID: runtime/unity-k3s-bringup
Parent: specs/proposed/runtime.spec.md

## 范围与非目标

约束 station-host 的 Unity k3s 装配；不改变 Unity 场景和任务行为，原场景与原生 Player 的资源边界分别按装配规则处理。

## 术语与身份

工作区 owner、namespace 与制品配置摘要共同限定资源归属；Pod 就绪不表示输入新鲜或任务完成。

## 输入、输出与配置

### 装配与配置

入口为 `l3-dispatcher-planner/tools/station-host-sim.py`。已跟踪的
`runtime.defaults.env` 提供非机器默认值，根 `.local.env` 覆盖声明的键；
未知 `SIM_` 键拒绝，无关配置不传给容器。配置不经 shell 求值。
Router 配置统一采用 PUBLIC_ZENOHD_ROUTER，装配到容器的 ZENOH_ROUTER。
LX_STACK_ID 与 namespace 缺省按工作区 owner 生成稳定的独立身份，不复用其它工作区。
SIM_NODE 缺省时按本机地址匹配唯一 amd64 节点，可显式覆盖；无匹配或歧义时报错。
SIM_GROUND_Z 可省略，不阻塞普通启动及普通航点；地面相关能力按所属契约检查。

镜像默认使用参考工作区同名 L2/L3、fluent-bit 和 relay，由本地 SIM_REGISTRY
替换 image-registry 角色；单项完整引用可覆盖。沿用镜像的系统解释器，不设置
无实际源码依据的 Python 版本门槛。prepare 导入真实源码闭包，具体缺口明确
报错；不预先要求重建镜像。containerd/docker 镜像存储按主机实际运行时选择。

ROS master、动力学、Unity 传感器、L3、遥测和日志固定在自动发现或显式指定的本机 amd64
节点；单副本 Recreate、hostNetwork。禁止隐式另起 ROS master。镜像显式覆盖
ENTRYPOINT，业务入口运行本仓库源码与编译产物，不调用参考工作区 L3。

日志采集与 relay 共用私有 Pod 网络的 loopback，不占主机日志端口；采集器只
匹配本 namespace 中本工作区业务部署的容器 stdout 路径，不申请共享 RBAC。

Unity `original/editor` 复用外部场景 Play；不启动或停止外部 Unity。
`native/player` 使用明确指定的本地 Player 和配置，独立 systemd 用户服务登记
归属；只停止本入口拥有的实例。原场景、传感器原生模式不并行。

### 制品

`prepare` 显式通过 k3s Job 编译 L3 与 Unity bridge，解析镜像 digest，记录源码
内容摘要、构建入口和挂载路径。运行产物位于被忽略的 `.artifacts/`，构建的
容器路径为 `/work/l3`、`/work/unity`；源码为 `/source/l3`、`/source/l2`。
- **UB4 编译身份**：L3、Unity bridge 和 L2-wire 必须分别按实际构建输入、镜像摘要、
  构建命令、解释器及挂载路径记录身份；不得把无关部署工具、Markdown 文档、
  Unity 客户端场景或普通运行配置混入 ROS 编译身份。
- **UB5 缓存生命周期**：prepare 可以复用身份一致且必要产物齐全的独立成功记录；
  重建前必须失效该组件记录，编译及依赖检查成功且输入未变化后才写回。
  不得把 Job 存在、编译缓存目录存在或失败退出视为成功。up 必须拒绝缺失、过期
  或版本不匹配的制品；旧版记录不得自动当作新格式缓存。
- **UB6 运行配置**：运行参数变化必须重新生成对应配置，保持活动资源配置一致性检查；
  不涉及构建输入的参数变化不得强制重新编译。
共享 PositionCommand 定义必须相同；L2 与 L3 分别加载自身消息集合。
镜像依赖不满足时 prepare 失败，禁止启动时隐式安装依赖。

## 行为规则

### 就绪与能力边界

master 用 XMLRPC；传感器使用递增、近时 ROS header；不以空 TCP 探针干扰 Unity。
L3 需要原生 Action 服务端、执行状态和现行 task presence。遥测、日志使用各自
独立 Zenoh 会话。部署不会申请租约或发送运动用于探测。
起降消费者与返航原点缺失时仍按既有契约失败，不制造虚假消费者或原点。
代码交付不构成运行验收；统一测试许可约束继续适用。

## 失败、取消与资源生命周期

### 生命周期

- `render` 仅生成本地 JSON 格式的 YAML 清单，不创建集群资源；缺省节点时只读查询集群，显式指定节点时可离线生成。
- `prepare` 只准备制品；业务栈已存在时拒绝重编译。
- `up` 顺序为 master、动力学与 TCP、真实传感器、L3、遥测与日志。
- `start` 必须先检查当前 L4 的依赖入口、归属和端口，再执行 up 和站端启动；L4 依赖通过其已有 setup 显式准备。
- `status` 分别报告 Pod、ROS 输入年龄、planner、任务、遥测和日志平面。
- `down/reset` 必须先确认 planner 动态停稳且无运动，并确认 connection/status
  可达且无其他 owner。本机当前租约可通过现行站端 release 释放；忙时拒绝。
  不可达时拒绝删除正在运行的 L3，不提供强制绕过选项。
- `reset` 整体 down/up，不调用单独 `/sim/reset`。
- `stop` 必须经过 down 安全约束，再关闭本机固定 L4 四服务及已知退役站端单元。
- `station-start` 必须检查服务单元和端口归属，不静默覆盖其它检出的活动服务。
- **UB7 完整站端停止**：stop/station-stop 必须关闭本机固定站端服务，不因来源检出或登记缺失跳过；
  已不存在的服务可以跳过。存在连接时必须成功安全释放，忙时或查询失败必须报错。
  清理固定用户单元及仿真相机 drop-in，不强杀占端口的未知进程。
- **UB8 部分启动**：必须在执行站端启动前写入登记；启动非零或超时后登记保留，
  完整关闭必须能够清理已经创建的服务。缺少正式可执行入口必须在业务栈启动前报告。

namespace 使用工作区 owner 注解作互斥锁；资源同时携带 owner 标签和配置摘要。
创建使用 API 原子 create，遇到未归属资源立即拒绝。失败仅回收本次新建资源，
保留原有资源和编译日志；业务重入使用原记录，不默默替换正在运行的配置。

## 归属与依赖

运行时装配归本提案，任务归 l3-dispatcher，遥测载荷归 runtime/station-telemetry，日志归 observability/log。

### 变更关联

```contract-links
{
  "implementation": [
    "l3-dispatcher-planner/tools/station-host-sim.py",
    "l3-dispatcher-planner/tools/build_ego.sh",
    "l3-dispatcher-planner/bringup/k3s/unity/**",
    "l3-dispatcher-planner/bringup/launch/basic_flight.launch",
    "Makefile"
  ],
  "depends_on": [
    "runtime"
  ]
}
```

## 条款检查判据

UB4–UB6：核对组件缓存、实际输入变化与运行配置分离；UB7–UB8：核对完整站端关闭、部分启动登记、依赖预检查及安全释放。
UB1：核对配置拒绝、源码摘要和挂载一致性；UB2：核对资源 owner、重入和失败回收；UB3：核对 down/reset 停稳、租约与就绪判据。证据归实施方案，未获许可不执行检查。

检查执行与证据记录遵循 `specs/README.md` 的统一许可边界；本文件不记录通过结论。

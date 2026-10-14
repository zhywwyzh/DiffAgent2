# 设备侧 L3 投放与运行

Status: proposed — 待评审，尚未采纳
Contract-ID: runtime/drone-remote-build
Parent: specs/proposed/runtime.spec.md

## 范围与非目标

### 范围

station-host 冻结源码并投放；drone-host 持久执行操作；k3s Job 原生编译 ARM64。
仅管理新版 L3，复用外部 ROS master、L0/L1/L2 和现有镜像。业务协议不变。

## 术语与身份

### 隔离与身份

- 新版设备根目录与本地登记的全部旧版远端目录互不包含；拒绝符号链接和目录别名。
  首次只登记空目录；后续核对 owner。旧版源码、脚本、制品及服务定义不修改。
- 新版控制脚本按摘要存储，源码按内容摘要发布，构建按独立尝试保存。
  所有可写挂载、配置、日志、缓存、状态和锁位于新版根目录。
- 编译/运行只加载系统 Noetic 和新版 devel，不加载镜像的旧 catkin overlay。
  容器源码路径 `/source/l3`、工作空间 `/work/l3` 在编译与运行间一致。
- namespace、systemd unit 和资源名按新版 owner 隔离；删除必须核对 owner 与 UID。

## 输入、输出与配置

输入为冻结源码、镜像摘要、部署配置与真实设备状态；输出为操作 JSON、构建记录及日志。具体编译与启动约束见编译与运行，不使用伪造状态补齐输入。

## 行为规则

### 操作

`plan` 只读本地；`sync` 投放冻结快照；`build` 编译选定源码；`prepare` 组合前二者；
`up/down/deploy` 显式管理新版 L3；`status/logs` 观察；`build-cancel` 取消编译。
组合操作由设备 systemd 服务持锁推进；SSH 断线不重建 Job，重连查询已有记录。
stdout 为 JSON 结果，日志保存在设备及站端忽略区。未知状态拒绝重新执行和启动。

### 编译与运行

- 构建闭包唯一归 `tools/build_ego.sh`，使用固定 ARM64 镜像摘要、非特权 Job，
  有资源预算、期限、零重试；只有容器退出码为零和实际制品齐备才能登记 built。
- 旧成功制品不修改；失败和取消保留诊断；up 只能选择源码/制品/配置匹配的成功记录。
- 编译、启动、关闭必须获得新鲜的已落地且未解锁状态。观察来源为已有 MAVROS；
  缺失或失联不得用配置布尔值替代。编译停止目标控制链 L3，不重启 L0/L1/L2。
- 新版 down 还须确认 planner 停止、禁用运动、控制面无主且无活动调用。
  不抢租约、不自动 land/disarm、不代停旧版。旧版仍运行则 build/up 拒绝。
- 真机 EGO 显式传入 realworld 参数；启动前核对 L2 PositionCommand MD5、
  定位、点云与控制连接；不新增协议桥。运行采用 Recreate，不双 planner。
- built、Pod 就绪、输入就绪和控制面就绪分别报告；不据此宣称已完成实机飞行验收。

## 失败、取消与资源生命周期

失败保留诊断，取消仅针对当前编译；已有成功制品不修改，资源删除核对 owner 与 UID，关闭遵循编译与运行中的停稳与租约门。

## 归属与依赖

本叶拥有独立设备工作空间的源码投放、构建与启停；复用外部 ROS master 和 L0/L1/L2，业务协议和构建闭包保持原 owner。

## 条款检查判据

DR1：核对目录隔离、源码与制品身份；DR2：核对设备状态、旧版运行拒绝及关闭门；DR3：核对断线重连和失败保留，证据归实施方案。

### 验收

遵循 AGENTS.md §9，未获明确许可不运行测试、编译或验证性验收。
方案、阶段状态及剩余条件归 `doc/l3-dispatcher-planner/iteration/design-drone-remote-build.md`。

检查执行与证据记录遵循 `specs/README.md` 的统一许可边界；本文件不记录通过结论。

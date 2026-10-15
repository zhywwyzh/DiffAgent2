# DiffAgent2 新版

本仓库管理机端内置项目、站端与仿真独立检出，以及统一部署和契约。DiffAgent2 旧版位置只从被忽略的根 `.local.env` 读取。

## 目录与归属

- `drone_projects/l3-dispatcher-planner/`：本仓库跟踪的机端调度、执行与规划项目。
- `station_projects/l4-agent/`：独立 Git 检出，原生站端应用；父仓库忽略其源码。
- `simulation_projects/l2-simulator-amd64/`：独立 Git 检出，动力学和 Unity/3DGS 仿真；父仓库忽略其源码。
- `deployment/tools/`：全栈启停、远端投放与设备执行入口。
- `deployment/k3s/`：仿真和设备装配清单、默认配置及容器探针。
- `deployment/.artifacts/`：本地编译、运行状态和日志，均被忽略。
- `specs/`：唯一契约注册表；`doc/l3-dispatcher-planner/` 保存实施方案与迁移台账。

目录规则归 [工作区布局契约](specs/implemented/inner/workspace-layout.spec.md)。独立检出与父仓库分别管理版本，不自动提交或更改远端。

## 根 Makefile

先在根 `.local.env` 配置机器参数，独立检出须已放入上述位置。常用操作：

```bash
make station-setup
make sim-prepare
make up
make status
make down
```

Unity 原场景须处于 Play。完整关闭停止本工作区仿真和本机 L4 服务，保留外部 Unity、namespace 和编译缓存；活动任务及连接仍须安全停止或释放。

完整说明见 [Unity 操作入口](deployment/k3s/unity/README.md)和[设备投放入口](deployment/k3s/real/README.md)。机端项目内部构建与 launch 见 [L3 说明](drone_projects/l3-dispatcher-planner/README.md)。

## 目录迁移后准备

从旧平铺目录迁移后，主机绝对路径已改变，必须重新执行 `make sim-prepare` 建立新制品记录；本地 L4 虚拟环境须按锁文件重新安装。不要恢复旧路径软链接。设备投放清单布局也已更新，重新部署前需同步并编译新版本；本轮目录迁移不自动操作设备。

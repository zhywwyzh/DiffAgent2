# 工作区部署编排

本目录拥有跨项目的镜像、k3s 清单、启停、远端源码投放和本地制品，不承载 L3 任务领域代码。

- `tools/station-host-sim.py`：本机 Unity 仿真与 L4 生命周期。
- `tools/station-host-drone.py`：设备源码冻结、投放及操作观察。
- `tools/drone-host-runtime.py`：设备侧隔离工作空间管理。
- `k3s/unity/`、`k3s/real/`：对应装配文件与说明。
- `.artifacts/`：被忽略的制品与状态。

默认从根 Makefile 操作；本地配置只读根 `.local.env`。项目源码分别位于 `drone_projects/`、`station_projects/` 和 `simulation_projects/`，容器 L3 与编排源码分挂载 `/source/l3`、`/source/deployment`。

编译缓存和源码签名会随实际路径变化而失效，迁移后通过对应 prepare 入口重新建立记录。具体行为归根 specs 中的 runtime 叶，不在本目录另建 spec。

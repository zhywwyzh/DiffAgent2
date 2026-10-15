# 工作区采用角色目录并独立部署编排

Status: implemented
Date: 2026-10-15
Record-Format: structured

## 背景

DiffAgent2 新版机端 L3、站端 L4 和仿真 L2 平铺，跨项目编排嵌在 L3 内；工具将 L3 父目录当作工作区根。用户参考 DiffAgent2 旧版，明确采纳角色分组，并要求 Makefile 与契约严格同步。

## 决策

机端项目归 drone_projects，站端应用归 station_projects，仿真项目归 simulation_projects，全栈编排归 deployment。保留 L3 内置子树及 L2/L4 独立检出关系，不复制源码或引入旧路径兼容入口。

## 理由与放弃的选项

按职责分组可以辨认运行位置和版本 owner；独立 deployment 避免算法项目承担整个工作区生命周期。不继续按 L2/L3/L4 平铺，也不把站端运行的仿真器仅因层级编号归为真实机端工程。

## 影响

同步根 Makefile、主机配置默认路径、根定位、容器挂载、设备投放清单、契约实现绑定与文档导航。旧编译记录和虚拟环境因绝对路径变化必须重新准备；历史正文保留当时事实。

## 关联契约与替代关系

要求归 [工作区布局契约](../inner/workspace-layout.spec.md)；实施及检查结果归 [迁移方案](../../../doc/l3-dispatcher-planner/iteration/design-workspace-role-layout.md)。不改变运行时提案生命周期或宣称业务验收完成。

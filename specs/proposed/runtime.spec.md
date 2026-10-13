# 运行时装配契约

Status: proposed — k3s Unity 代码实施中，未构建与验收
Contract-ID: runtime

运行时装配拥有镜像、制品、配置、资源所有权与生命周期。任务行为仍归现行
l3-dispatcher，日志归 observability，实体命名归 topology。

## 不变量

- 编译与运行使用同一镜像摘要、源码身份和容器挂载路径。
- 主机配置为数据，不作为 shell 执行；机器值仅存于被忽略的本地文件。
- 一个 namespace 同时仅由一个工作区管理；主机网络额外检查端口冲突。
- 删除仅针对本工作区登记且当前归属一致的资源；不删除 namespace 或共享权限。
- 运行状态、数据新鲜度和任务结果分别报告，不以进程在线推断任务成功。

## Inner contracts

| Contract | Authority |
|----------|-----------|
| `specs/proposed/inner/unity-k3s-bringup.spec.md` | Unity 仿真编译、装配与启停 |
| `specs/proposed/inner/station-telemetry.spec.md` | 当前站端遥测消费者的数据格式与生产边界 |

## 边界

不修改技能注册、RPC、原生 Action、Unity 场景或独立 L2/L4 仓库的协议。

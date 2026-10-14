# Unity 启动配置收敛方案

> 摘要：承接用户确认可靠的 Exploration 参数，取消全栈启动对局部能力参数的依赖。

## 0. 元信息

- 日期：2026-10-14
- 目标路径：`l3-dispatcher-planner/tools/`、`bringup/`
- 状态：代码已交付，未构建或验收
- 关联文档：`design-k3s-unity-bringup.md`

## 1. 背景与动机

`make up` 被新增的四项配置门拦截。沿用经过实验的配置来源，减少人工输入。

## 2. 现状事实（问题清单）

- `l3-dispatcher-planner/tools/station-host-sim.py:67` 将节点、身份、地面高度全部列为必填。
- `l3-dispatcher-planner/bringup/launch/basic_flight.launch:2` 无条件要求地面参数。
- `l3-dispatcher-planner/ros_packages/dispatcher/dispatcher/execution/ports.py:9` 已允许地面参数缺省。

## 3. 目标与约束

统一采用 PUBLIC_ZENOHD_ROUTER；工作区实例名自动生成；本机节点自动发现，保留显式覆盖；地面高度只约束依赖它的能力。不改变可靠的传感器参数，不设计转接器，不保留替代配置别名。不构建、不测试、不启动验收。机器值只写被忽略的本地配置。

## 4. 方案决策

目录架构沿用 tools 与 bringup，不新增包装层。文件使用既有 station-host-sim.py；辅助函数使用 snake_case。默认实例和 namespace 根据工作区 owner 稳定生成。本机节点通过 k3s 节点地址与本机地址匹配，必须唯一且为 amd64；无法确定则明确报错，不猜测远端。省略节点时配置解析需要只读访问集群。容器变量仍为 ZENOH_ROUTER，配置唯一来源为 PUBLIC_ZENOHD_ROUTER。ground_z launch 参数默认空，仅显式配置时写入 ROS 参数。

## 5. 迁移映射

- 配置 ZENOH_ROUTER → PUBLIC_ZENOHD_ROUTER：重命名，容器接口保持。
- 必填 SIM_NODE → 可覆盖的自动发现值。
- 必填 LX_STACK_ID → 稳定的工作区独立默认值。
- 必填 SIM_GROUND_Z → 可选值；缺省不注入地面参数。

## 6. 删除清单

删除四项强制必填门及无条件地面参数注入。保留领域层按能力拒绝缺少地面信息的行为，不伪造地面或原点。

## 7. 实施步骤

P0：先记录方案。P1：修改配置解析、清单装配和 launch，保持资源归属及 hostPath 同机约束。P2：同步说明和迁移台账，写本地 Router 与镜像仓库。回退仅撤销本方案新增改动，不覆盖工作区既有修改。

## 8. 验收标准

按 AGENTS.md 统一声明，本次不运行测试、门禁、构建或验证性验收。后续获准后覆盖缺省配置、显式节点、歧义节点、可选地面参数及任务能力边界；不将代码交付宣称为启动成功。

## 9. 风险与对策

自动发现依赖集群读取权限，显式节点可避免解析阶段查询。已有制品配置摘要将变化，必须显式 prepare。原栈占用 ROS/Unity 端口仍会阻止启动，不自动停止其他工作区。

## 10. 修改点清单汇总

- tools/station-host-sim.py：配置收敛、节点发现、可选地面。
- bringup/k3s/unity/runtime.defaults.env：默认键收敛。
- bringup/launch/basic_flight.launch：可选地面参数。
- bringup/k3s/unity/README.md：配置及首次操作说明。
- runtime/unity-k3s-bringup 提案：同步配置和 render 的只读节点发现行为，按统一许可声明跳过门禁。
- rest 索引与台账：记录 R03/R05 的可选地面配置边界及未验收状态。
- 根 .local.env：仅更新本地可靠的公共服务地址。

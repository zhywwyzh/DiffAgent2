# dispatcher 迁移执行顺序与文档导航

> 后续执行的统一入口：先按本文件定位阶段，再依次读取该阶段的权威契约、子方案和
> 实现文件，完成编辑与验收后推进。本文件只拥有顺序、依赖和进度；具体行为归 specs，
> 具体实现决策归子方案，不建立第二份协议或实现清单。

## 0. 元信息

| 项 | 值 |
|---|---|
| 日期 | 2026-09-16 |
| 状态 | in-progress（职责上行修正，未重跑测试） |
| 目标路径 | l3-dispatcher-planner 及对应 doc/specs |
| 当前进度 | RPC 保持已迁入；取消覆盖已收回 dispatcher，字段和 planner 行为已恢复；修正版按用户要求未测试、尚未提交 |
| 上游边界 | l4-agent 只读，不修改其源码、配置、测试或文档 |
| 使用方式 | 每次开始或恢复执行先读本文件 §4/§7，再进入当前阶段列出的文档 |

## 1. 背景与动机

RPC 对接和基础飞行是两轮有依赖的迁移，不能按文件排列顺序随意实施。
先验证上层请求/终态闭环，再确认执行接口，才能区分通信失败和执行失败。
生产注册是最后的交付动作，不是用来启动联调的占位手段。

## 2. 现状事实（问题清单）

- `specs/implemented/inner/l3-execution-seam.spec.md:10` 明确取消独立 mission_executive 包。
- 同文件 §4 已按用户裁定明确不迁入 /mission/task，由 dispatcher 经端口直接驱动 planner。
- `l3-dispatcher-planner/ros_packages/dispatcher/dispatcher/utils/rpc_plane.py:250` 的快速
  终态窗口等前置问题，证据和复现归 RPC 子方案 §2。
- `l3-dispatcher-planner/ros_packages/dispatcher/dispatcher/tools/registry.py:35` 的
  默认生产集合为空；基础飞行子方案描述目标，不表示实现已经恢复。

## 3. 目标与约束

- 提供确定的阅读、编辑、验收和推进次序；每个阶段有唯一的子方案入口。
- 规范优先。子方案与现行契约冲突时先修目标提案/完成契约评审，再写代码。
- 不修改 l4，不新增任务编号、兼容层或生产空实现，不恢复独立 mission_executive。
- 本轮代码与验收记录见 §7 和子方案执行记录；后续扩展仍按同样的契约与验证顺序推进。

## 4. 方案决策

### 4.1 文档目录与职责

```text
doc/l3-dispatcher-planner/iteration/
  design-dispatcher-migration-execution-order.md  # 顺序和进度唯一入口
  design-dispatcher-l4-rpc-integration.md         # RPC 实现路线
  design-dispatcher-basic-flight-migration.md     # 飞行实现路线
specs/implemented/inner/
  flight-actions.spec.md                         # 已采纳的动作契约
  l3-l4-rpc.spec.md                              # 已采纳的 wire 契约
```

方案文件使用 `design-dispatcher-主题.md`，契约使用聚焦的 `*.spec.md`；阶段编号
统一用本总纲 S0–S6，子方案的 P 编号仅表示局部步骤，不另行决定全局顺序。
提案采纳时整叶移至 implemented，并在同一改动修复本总纲和子方案的入链。

### 4.2 执行顺序与文档访问表

| 阶段 | 依次访问的文档 | 编辑范围与结果 | 进入下一阶段的条件 |
|---|---|---|---|
| S0 基线 | 本总纲 → [l3 根契约](../../../specs/implemented/l3-dispatcher.spec.md)及其全部叶 → [spec 注册规则](../../../specs/README.md) → [rest 索引](../rest/README.md)及相关台账 → 两份子方案 §2/§8 | 核对工作区已有修改、准备测试依赖、记录现状；只读核验 l4 来源 | 基线可复现；环境失败与实际代码失败分开记录，不能把未跑报告为通过 |
| S1 RPC 修复 | [RPC 提案](../../../specs/implemented/inner/l3-l4-rpc.spec.md) → [RPC 子方案](design-dispatcher-l4-rpc-integration.md) §4、P1 → 其 §10 实现文件 | 解析拒绝、终态关联、重放 owner 门、owner watch 和资源生命周期 | 子方案通用回归通过；生产集合仍为空 |
| S2 RPC 闭环交付 | RPC 提案 §6 → RPC 子方案 P2/P3、§8 → 只读 l4 消费者 | 受控 session 和隔离 Zenoh 测试；采纳 RPC 叶，更新根表/工具面归属，归档决策 | RPC1–RPC7 有证据；没有 l4 改动；前置方案 done |
| S3 直连接口取证 | [执行缝现行契约](../../../specs/implemented/inner/l3-execution-seam.spec.md) → [飞行动作提案](../../../specs/implemented/inner/flight-actions.spec.md) → [飞行子方案](design-dispatcher-basic-flight-migration.md) §4.3/§4.4、P0 → 台账 R03/R04/R05 | 核对实际 planner/飞控直连接口，完善子方案及必要契约修订；冻结端口、消息、取消/结果、构建和 remap | 直连接线矩阵落在飞行子方案 §4.4；必要契约已先行修订，无未解析消息或部署依赖 |
| S4 飞行实现 | 动作提案 → 飞行子方案 P1/P2、§4/§10 → 对应领域/端口/适配文件 | 先宿主/disposer/原点服务，再状态和停止链、起降、共享目标执行、平移/旋转、返航；使用测试注册表 | 领域、边界和模拟下游测试通过；真实完成/取消均有实现；生产仍为空 |
| S5 飞行集成 | 动作提案 §6 → 飞行子方案 P3/§8 → RPC 子方案既有回归 → 台账对应验收 | 真实 l4 消费者与 EGO 直连接口集成，使用受控状态输入验证至 /setpoint_cmd 输出 | 参数、结果、取消、原点与急停保持命令均达 cmd 边界验收；不验证 cmd 下游处理 |
| S6 生产交付 | 飞行子方案 P4 → spec 注册规则 → 工具面现行契约 → rest 台账与索引 | 同批注册六工具、计算 revision、采纳动作叶、更新根表和测试，归档新决策 | 默认集合与已交付实现严格一致；保留旧 flight 名拒绝；证据齐全才置 done |

依赖链固定为 `S0 → S1 → S2 → S3 → S4 → S5 → S6`。可以提前做只读取证，
但不得越过前置验收写入后阶段生产行为。S3 的取证不是许可重建旧 mission 层。

### 4.3 已确定的直连架构

用户已明确：/mission/task 是 dispatcher 与旧 mission_executive 间的中间转换接口，
当前 dispatcher 自己负责六态任务 FSM 和动作下发，不再需要该转换层。
[直连决策](../../../specs/implemented/architecture/2026-09-16-dispatcher-direct-planner.md)
和现行执行缝契约已落实这一方向，不再保留“必要时恢复旧 action”的选项。

S3 核实具体 planner 输入、反馈、取消/覆盖与停止机制，确定消息和部署接线；不重新
裁决是否保留旧转换层。技能负责领域意图，通用执行模块负责动作账务，ROS 适配层
集中通信；core 不新增领域发布器。action_result 不等于 ROS action。

## 5. 迁移映射表

| 原文档局部阶段 | 全局归属 | 动作 |
|---|---|---|
| RPC P0 | S0 的已起草文档输入 | 保留提案，补基线 |
| RPC P1 | S1 | 执行通用修复 |
| RPC P2/P3 | S2 | 验证并采纳 |
| 飞行 P0 | S3 | 核实 planner 直连端口与反馈 |
| 飞行 P1/P2 | S4 | 实现能力，不注册生产 |
| 飞行 P3 | S5 | 集成与物理证据 |
| 飞行 P4 | S6 | 同批交付与归档 |

## 6. 删除清单

- 撤回飞行方案中“必须实现 /mission/task 服务端/客户端”的预设，删除固定的
  mission_action_ros.py 建设要求，按 S3 核实的 planner 直连职责确定文件。
- 现行执行缝契约已按用户要求修订直连方向；不将方向采纳写成代码已实现。
- 不删旧版/l4 文件、不清理用户已有修改；实现替代项的删除由各子方案负责。

## 7. 实施步骤与进度记录

每次执行按以下流程操作：读总纲定位首个未完成阶段 → 依 §4.2 从左到右读文档 →
编辑该阶段子方案列明的文件 → 跑阶段验收 → 在子方案登记命令、结果和限制 →
更新下表 → 进入下一阶段。跨会话恢复仍从此表定位，不按 IDE 当前标签猜阶段。

| 阶段 | 当前状态 | 验收记录归属 |
|---|---|---|
| S0 | 完成；隔离依赖环境中 83 项基线通过 | RPC 子方案 §8 |
| S1 | 完成；RPC/租约/资源生命周期修复 | RPC 子方案 P1/§8 |
| S2 | 完成；真实 l4 消费者、回环 Zenoh 验证和契约采纳 | RPC 子方案 P2/P3/§8 |
| S3 | 边界已修正：仅去来源编号，保留其他字段与 planner 原行为 | 飞行子方案 §4.4/P0 |
| S4 | 代码已修正：旧 stopMotion 职责上行到 dispatcher | 飞行子方案 P1/P2/§8 |
| S5 | 旧实现验收保留作历史；本修正版未重跑（用户要求） | 飞行子方案 P3/§8 |
| S6 | 六工具注册不变；模块提交待修正收尾 | 飞行子方案 P4/§8 与 rest |

每阶段范围和不变式见 §4.2，具体回退按对应子方案 P 阶段执行。阶段失败保持原阶段，
不跳过测试、不开放占位工具。先前实现的 S6 结果仅作历史；本修正版验证状态以本表为准。

## 8. 验收标准

- 两份子方案和 rest 入口均链接本总纲；局部 P 与全局 S 一一对应。
- 每一步明确读取入口、编辑归属、前置和退出条件；全部阶段完成前不标总纲 done。
- 子方案中的直连接口与 S3 取证矩阵一致，不保留互斥路线的强制实现要求。
- 提案晋升同步修链接、根表和生命周期状态；当前规范仍是唯一权威。
- l4 无修改；文档相对链接、简体中文、隐私及空白检查通过。

## 9. 风险与对策

| 风险 | 对策 |
|---|---|
| 总纲和子方案重复维护行为细节 | 总纲只维护依赖/进度，行为指向 spec，实施细节指向子方案 |
| 将取消包误解为可以不实现完成/取消 | S3 核实完整执行语义，不恢复旧转换接口 |
| 具体直连消息需要变更 | 先登记变更并修契约，再改代码，不能造转接层绕过 |
| 环境/实机证据缺失却推进 | 保留明确的未验收状态，仅继续不依赖该条件的只读调查 |

## 10. 修改点清单汇总

| 文件 | 动作 |
|---|---|
| 本总纲 | 新增，后续执行统一入口 |
| design-dispatcher-l4-rpc-integration.md | 增加总纲入链 |
| design-dispatcher-basic-flight-migration.md | 增加总纲入链，纠正 mission action 预设 |
| specs/implemented/inner/flight-actions.spec.md | 明确 dispatcher 直连 planner，禁止旧 action 转换层 |
| rest/README.md、保留项台账 | 对齐直连方向与待迁状态 |
| specs/implemented/inner/l3-execution-seam.spec.md、对应架构决策 | 明确不迁入旧转换层，dispatcher 直接经端口驱动 planner |

2026-09-17 用户已启动代码迁移，按本文件顺序实施；当前进度以 §7 为准。

2026-09-17 范围收敛：用户指定当前实际使用 EGO，旧版支持 planner_backend 配置切换；
本轮只负责到 cmd 输出，后续处理不属本仓库任务。S3 旧版取证表见飞行子方案 §4.4.1，
S5 以真实 planner 的 cmd 输出和受控反馈验收，不要求 cmd 下游实机验证。

2026-09-17 完成记录：外部构建目录中的 EGO/dispatcher/最小消息依赖构建通过；
完整测试 115 passed（11 条 rospy 弃用警告）。测试从原始 l4 客户端经过正式启动入口、
默认注册表、六态 FSM 和真实 EGO 到 /setpoint_cmd，并验证 outcome 回链。未测试或
部署 cmd 下游组件；未修改 l4 或 DiffAgent2 旧版；未提交/推送。

## 职责上行修正记录

按用户纠正，保留 yaw_low_speed 和 goal_to_follower，不再以 basic-flight 迁移为由
裁剪其他消息字段。EGO 的新取消回调、停止状态/偏航改动已撤回；planner 差异仅与
来源任务编号有关。dispatcher 通过既有目标口发送新批次保持意图并管理失效结果。
先前 115 项通过记录不覆盖这一修正；未新增或执行测试，未执行构建，未提交。

# task-id 删除后的工具名与业务语义迁移遗留项

更新日期：2026-09-17。状态：**任务按原始工具名识别已接入；原编号关联的业务判据仍须逐项核对和迁移，不能视为全部完成。**

本文件是迁移遗留项和调查入口，不是第二份规范。职责与机制以
[l3 根契约](../../specs/implemented/l3-dispatcher.spec.md)、
[core 边界](../../specs/implemented/inner/l3-core-boundary.spec.md)、
[技能契约](../../specs/implemented/inner/l3-skill-contract.spec.md)和
[迁移规程](../../specs/implemented/inner/l3-migration-protocol.spec.md)为准。

## 用户明确的迁移含义

**删除 task-id，是直接使用原本的 tool 名字识别任务，例如 `navigation.vla_nav`；不是删除任务身份、对应能力或其原有业务语义。**

新版的任务分发链应当直接使用：

```text
上层 rpc-json.method（例如 navigation.vla_nav）
  → ToolCall.name（保留同一个工具名）
  → 按该名字查找已注册技能
  → 对应技能处理任务及自己的子流程
```

不再增加“工具名 → 数字编号 → 技能”的映射，不把编号换成另一套枚举或新造的名字。
也不能把删除编号字段解释成“原先依赖它的条件都可以删除”。

当前是否可调用还取决于技能是否完整迁入并注册。`navigation.vla_nav` 等名字即使暂时
未注册，后续迁移仍使用上层原名；当前拒绝未注册调用不代表名字被废弃或业务需求消失。
上层依据是工作区只读的 `l4-agent/`，本项不要求修改 l4。

## 当前事实与证据

以下路径相对本仓库根，行号用于定位，后续优先按符号查找。

| 位置 | 已确认事实 | 结论 |
|---|---|---|
| `l4-agent/src/copaw/agents/tools/plan_tools.json:92` | 上层工具名包含 `navigation.vla_nav` | 沿用实际调用名，不凭旧编号另造名称 |
| `l3-dispatcher-planner/ros_packages/dispatcher/dispatcher/utils/rpc_plane.py::_execution_call` | 将请求 method 作为调用的 name 交给 runtime | 任务身份仍在，编号不是必要中间层 |
| `l3-dispatcher-planner/ros_packages/dispatcher/dispatcher/core/skill_router.py::dispatch_plan` | 按 `skill_command.call.name` 查表分发 | core 只负责按名分发，不承担工具领域分支 |
| `l3-dispatcher-planner/ros_packages/utils/quadrotor_msgs/msg/LocalGoalSet.msg` | 已移除 `source_task_id`、`SOURCE_TASK_*`；其他被误删字段已恢复 | 消息去编号不等于原业务判据迁移完成 |
| `l3-dispatcher-planner/ros_packages/planner/ego_planner/plan_manage/src/ego_replan_fsm.cpp` 的修改前版本 | `aimCallback`、`aimCallbackYawPreset` 曾按来源编号限制 panorama | 移除来源判断有行为影响，不能只按编译通过结案 |
| `l3-dispatcher-planner/ros_packages/planner/super_planner/planner/include/ros_interface/ros1/fsm_ros1.hpp` 的修改前版本 | 同样存在 `panorama_source_allowed` 及不允许时的偏航回退 | 两个后端的旧判据均需追溯上层业务归属 |

修改前证据可在 DiffAgent2 新版提交 `71e76e1` 的对应 planner 文件中查看。
DiffAgent2 旧版的接口和调用链取证入口见
[基础飞行方案 §4.4.1](../l3-dispatcher-planner/iteration/design-dispatcher-basic-flight-migration.md#441-s3-旧版接线取证2026-09-17)。
不把工作区源文件位置或个人主机路径写入此记录。

## 必须继续处理的遗留项

| 原先与编号关联的内容 | 新版归属与迁移方向 | 当前状态 |
|---|---|---|
| 任务识别与分发 | rpc-json 原始 method → ToolCall.name → 同名技能注册 | 已接入；后续技能继续沿用原工具名 |
| 工具专属流程、完成门和重规划条件 | 对应技能或其共享领域服务 | 按能力逐项迁移，不能因编号已删而遗漏 |
| panorama 的来源限制和偏航模式选择 | 在 dispatcher 对应技能/业务策略中判断，再给 planner 下发已确定的运动参数 | **待追溯并迁移**；当前仅移除了 planner 的来源编号判断，尚未证明已有等价上层策略 |
| 原来源编号的日志用途 | 有真实消费者时记录原始 tool 名及原有调用关联信息 | 待核对记录/诊断消费者，不能把相关可观测信息一起丢弃 |
| 尚未迁入工具的名字 | 例如 `navigation.vla_nav`、`navigation.scene_graph_nav`，仍以上层实际名字为依据 | 技能未迁入时拒绝调用；不据此登记为永久删除 |

旧 panorama 判断使用 `SOURCE_TASK_EXPLORATION`、`SOURCE_TASK_COUNTING` 等内部来源
常量。**这些旧内部来源与当前工具名、技能子流程的对应关系尚未在本遗留项中核实。**
不能擅自断言它们分别等同于哪个 `navigation.*` 工具，也不能仅凭名字相近指定允许列表。

task-id 删除本身不表示用户批准所有来源使用 panorama。当前来源门已移除而对应上层
判据未确认，是需要继续处理的语义缺口；不将它表述为已经完成等价迁移。

## 后续处理顺序与边界

1. 从只读 l4 的原始工具名出发，追溯 DiffAgent2 旧版实际技能、子流程、动作构造和
   原编号读点，记录该判断原本解决的业务问题。
2. 区分“识别任务”与“判断能力是否允许某动作”。前者直接使用工具名；后者归对应
   技能或共享业务策略。core 仍只按名分发，不加入 `if name == ...` 的领域判断。
3. 需要保留的业务判据先在统一 `specs/` 明确，再按工作空间迁移方案实施。
   planner 接收航点、yaw 模式等运动语义，不为保留来源限制重新接收 task-id，
   也不把 `source_task_id` 机械替换成 planner 内的工具名分支。
4. 日志或运行记录确有任务身份需求时传递原始 tool 名，不能重新创建编号表。
   `call_id` 是一次调用的关联键，`batch_id` 是下行动作/反馈关联键，均不替代工具身份。
5. 实现后记录原判据到新技能/策略的落点和行为证据。若要改变或放弃某个旧判据，
   单独明确裁决，不能借去编号默认放行。

`yaw_low_speed`、`goal_to_follower` 是独立消息字段，本项不把它们列入 task-id 删除范围。
取消 mission_executive 的控制职责继续上行到 dispatcher，不借此给 planner 添加专属
任务控制接口；相关纠正见
[职责边界修正记录](../../specs/implemented/architecture/2026-09-17-dispatcher-planner-boundary-correction.md)。

## 触发条件与关闭条件

迁入 VLA/场景导航、处理 panorama/全景旋转、整理来源日志或继续删除任务身份字段时，
必须重新参考本项，并结合
[l3 保留项台账](../l3-dispatcher-planner/rest/dispatcher-deferred-dependencies.md)的 R05/R07 等关联条目。

关闭本项前必须确认：

- 实际上层工具名在解析、分发和所需记录链中保持一致，不存在隐蔽编号映射。
- 所有真实旧判据均有新的技能/策略归属，或有明确的改变/退役裁决。
- panorama 等旧来源限制有允许与拒绝场景的行为证据，不能只证明编号字符串已消失。
- 能力可调用状态与生产注册表一致，未迁入能力不冒充完成。

| 日期 | 处置 | 验证状态 | 后续触发 |
|---|---|---|---|
| 2026-09-17 | 登记按原工具名识别任务的迁移含义，以及旧来源判据待上行迁移的缺口 | 本轮仅文档整理；未修改代码、未新增或运行测试、未构建 | VLA/场景技能、panorama 策略或来源日志迁移 |

当前不关闭本项。以后接入或明确退役时，在此追加实现位置、证据和剩余触发条件，并同步
l3 的 rest 索引；不只留下“以后处理”。

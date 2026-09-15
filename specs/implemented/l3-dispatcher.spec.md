# l3 调度与执行契约

Status: implemented

Contract-ID: l3-dispatcher

> 拥有 l3 层（任务分发 / 下行执行 / 运动规划）的系统边界、职责划分与不变量。
> 具体裁剪清单、迁移步骤与每轮验收归 `doc/l3-dispatcher-planner/iteration/` 下的
> 决策记录所有，不进本契约。

## 不变量

> 以下为 l3 的稳定骨架；任何一轮迁移都不得违反。

- **三段构成**：l3 = 任务分发（dispatcher）+ 下行执行缝（execution seam）+
  运动规划（planner）。planner 已独立分层，不在本契约的重构范围。
- **core 只分发**：dispatcher core 持有六态 FSM 与任务队列，按工具名分发；
  不持有任何工具的领域语义。
- **能力即技能**：每个对外任务能力是一个技能，按名注册；core 只按名解析，
  不做语义分支。
- **无任务编号**：l3 不引入任务编号或等价的中间表示。任务识别直接基于
  rpc-json 的解析结果；引入编号映射属概念污染与无效开销。
- **收发集中**：ROS 的订阅、发布、服务与 action 只出现在适配文件；领域逻辑
  经抽象端口或内存状态获取数据。
- **未注册即失败**：分发未命中已注册技能时必须上报失败并停在空闲态，不得
  排空队列后回报完成。
- **终态唯一**：一次调用有且仅有一个终态事件（done / fail / cancel），相位
  序列按此收敛。
- **节律不绑定语言**：执行缝的 tick 频率由能力需求决定（10 Hz 与 20 Hz 皆
  合法）；改变频率不要求改变实现语言。

## Inner contracts

> 叶契约拥有各自聚焦的机制与判据。

| Contract | Authority |
|----------|-----------|
| `specs/implemented/inner/l3-core-boundary.spec.md` | dispatcher core 的准入与禁令 |
| `specs/implemented/inner/l3-ros-adapter-boundary.spec.md` | ROS 收发隔离、端口与内存访问方式 |
| `specs/implemented/inner/l3-execution-seam.spec.md` | 下行执行缝（原 mission_executive 的能力归属） |
| `specs/implemented/inner/l3-skill-contract.spec.md` | 技能的身份、生命周期、端口与逆 |
| `specs/implemented/inner/l3-migration-protocol.spec.md` | 旧库向新库迁移的裁决、准入与禁止事项 |
| `specs/implemented/inner/l3-tool-plane.spec.md` | 工具发现/调用/事件/取消与连接租约的对外协议 |

## 边界

本契约不拥有：planner 的内部算法与后端选择；l4 侧协议与站端行为；编码风格
与命名（归 `development-workflow/l3-coding-style`）；镜像构建、部署与集群
编排；某一轮的具体裁剪清单与验收步骤。

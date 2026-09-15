# dispatcher core 契约落实方案

> 摘要：依据现行 `specs/implemented/inner/l3-core-boundary.spec.md` 修正核心依赖、按名分发、动作裁决与可观测性；用户随后明确同时执行两份现有拆分、改名方案；本方案的契约修复合并至新结构。

## 0. 元信息

| 项 | 值 |
|----|----|
| 日期 | 2026-09-15 |
| 目标路径 | `l3-dispatcher-planner/ros_packages/dispatcher/` |
| 状态 | done |
| 关联文档 | l3 根契约与全部六份叶契约；本目录 `_TEMPLATE.md` |

## 1. 背景与动机

核心文件表面无 ROS 导入，但感知继承链仍使核心拥有领域实现与额外端点。运行状态与契约中的失败收敛、动作归属、等待诊断也有偏差，需要用可执行回归约束。

## 2. 现状事实（问题清单）

- `l3-dispatcher-planner/ros_packages/dispatcher/dispatcher/engine.py:32` 导入并继承 `BasePolicyNode`，其内部持有 ROS 端点和几何计算。
- `l3-dispatcher-planner/ros_packages/dispatcher/dispatcher/core/skill_router.py:73` 准入仅检查激活名字非空，未检查实际注册项；动作归属按名字回退。
- `l3-dispatcher-planner/ros_packages/dispatcher/dispatcher/engine.py:452` 缺失技能时自行选择裁决；IDLE 未发完成相位。
- `l3-dispatcher-planner/ros_packages/dispatcher/dispatcher/engine.py:604` 等待任务与等待动作路径缺周期诊断，多处直接写状态绕过迁移日志。
- `l3-dispatcher-planner/ros_packages/dispatcher/dispatcher/core/workflow.py:100` 任务注入未迁入，后续代码依赖不存在的方法；当前技能注册面为空，完整飞行链路尚不可运行。

## 3. 目标与约束

- 目标：现行 core 方法白名单不变，核心通过注入读取输入，按原始工具名分发，完成门只认动作归属实例，所有等待与状态迁移可观测。
- 非目标：迁入全部技能、重构感知内部算法、修改 planner、执行独立文件改名与三域拆分方案。
- 硬边界：无新旧接口转接器、无兼容别名；保留用户已有修改；不提交或推送。

## 4. 方案决策

目标目录保持 `dispatcher/engine.py`、`dispatcher/core/*.py`、`dispatcher_node.py`；新增回归归属 `tests/core-boundary/`。文件与函数使用小写下划线，类使用 PascalCase。

核心构造函数接收帧与输入健康读取回调，装配根独立构造既有感知对象并传入其读取方法，原感知配置直接作用于该对象。删除继承，避免核心获得全部感知方法与 ROS 端点。类型专用导入不应牵入技能实现。

路由严格使用 `call.name`，归属只用动作快照；缺失归属或非法裁决上报失败，禁止隐式成功。四裁决机械执行；等待任务、感知、动作与异常恢复输出原因和年龄。现有事件名、主题与字段保留，新增迁移原因用于原无日志的路径。

## 5. 迁移映射表

| 旧路径/命名 | 新路径/命名 | 动作 | 备注 |
|----|----|----|----|
| engine 感知继承 | 装配根独立感知对象与读取回调 | rewrite | 唯一生产装配调用方为 `dispatcher_node.py` |
| 工具名回退路由 | 原始调用名查表 | rewrite | workflow 与 engine 均有活调用方 |
| 直接写状态 | `_set_dispatcher_state` | rewrite | 统一来源、目标、原因 |

## 6. 删除清单

| 删除项 | 理由 |
|----|----|
| engine 的 `BasePolicyNode` 继承与导入 | 领域依赖与额外端点不属于 core |
| 动作归属按名字兜底 | 会把旧动作交给新实例裁决 |
| 完成判定中不影响结果的 numpy 计算及注释桩 | 无有效调用结果，属于死代码 |

## 7. 实施步骤

### P0 — 依赖与分发边界

- 范围：engine、装配根、路由及类型依赖。
- 不变式：六态、主题、参数名与四类出站端口不变。
- 验收：真实 core 导入无 ROS；AST 白名单与依赖闭包；路由负例。
- 回退：仅还原本轮差异，保留开始前修改。

### P1 — 状态收敛与诊断

- 范围：四裁决、未注册失败、等待诊断、异常恢复。
- 不变式：四裁决名称与既有事件名称不变。
- 验收：真实 FSM 在假时钟与假技能下运行，检验相位、队列与迁移；既有工具面测试。
- 回退：按本轮差异恢复。

## 8. 验收标准与结果

- [x] 核心与工具面回归：`uv run --isolated --no-project --python python3 --with pytest --with eclipse-zenoh --with pyyaml python -m pytest -q l3-dispatcher-planner/tests/core-boundary l3-dispatcher-planner/tests/tool-registry`，**80 项通过**。
- [x] 现存 l3 Python 源文件语法检查通过；core AST 方法集合符合修订后的白名单；六态数量不变。
- [x] 核心导入闭包无 ROS 与领域实现；协作模块不反向导入 engine；四类出站通道白名单通过。
- [x] 未注册失败不排空队列、不产生 done；四裁决、实例归属、迟到动作结果、恢复与等待诊断回归通过。
- [x] 默认工具集合为空，revision 与工具面 spec 一致；22 个已删除工具名及旧别名的 RPC 请求均拒绝且不入队。
- [x] engine 已迁旧定义及注释引用零残留；生产工具、缺失任务注入入口、场景/抓取/记录状态标识零残留。
- [x] spec 状态及父契约引用有效；本仓门禁引擎尚未迁移，以上述 AST、结构检查与测试判定。

验证限制：本轮未做 ROS/实机飞行端到端验证。全部未实现生产工具已按用户要求删除，当前无飞行/导航生产能力；未来新增技能须连同执行链与端到端验收一起交付。感知实现内部仍含 ROS 通信，planner 中仍有既有来源编号检查；这些是保留实现的后续边界工作，不能将本轮核心通过外推为全 l3 的 G5/G7/G8 全绿。

## 9. 风险与对策

| 风险 | 影响 | 对策 |
|----|----|----|
| 感知配置原先加载到继承对象 | 分离后配置错位 | 将 base_policy 配置加载到实际感知对象 |
| 技能及任务注入缺失 | 本轮结束时完整飞行链路不可运行 | 使用真实 core 与可控输入回归；完整端到端恢复归技能及任务注入迁移轮次 |
| 未执行方案与现行 spec 不同 | 范围误解 | 以现行 spec 为准，已异步询问是否扩大范围 |

## 10. 修改点清单汇总

| 文件 | 动作 | 说明 |
|----|----|----|
| `dispatcher/engine.py` | 修改 | 去继承、裁决收敛、日志与等待 |
| `dispatcher/core/skill_router.py` | 修改 | 精确查表与实例归属 |
| `dispatcher/core/telemetry.py` | 修改 | 等待诊断明确年龄含义 |
| `dispatcher/tools/skill_api.py` | 修改 | 清理不存在的领域类型导入 |
| `dispatcher_node.py` | 修改 | 装配期注入输入读取 |
| `tests/core-boundary/` | 新增 | 静态门禁与行为回归 |
| 本方案及 `specs/implemented/architecture/` 决策记录 | 新增 | 过程记录与结构理由 |


执行补充：用户已确认同时执行两份既有方案。白名单先按拆分方案修订，保留原方案中的方法集合。`StateLedger` 增加构造参数 `host_state_get`，用于读取实际宿主状态，避免为了迁移日志复制第二份状态；`last_state` 只存 ledger，队列回调访问 ledger。动作裁决修复与可观测性增补归本方案，结构搬迁本身不重复保留已确认的缺陷。新增迁移原因有 `inference:start`、`mission:ready`、`dispatch:action_in_progress`、`dispatch:frame_missing`、`action:done`、`post_action:replan`、`post_action:advance`、`post_action:queue_finished`、`inference:exception`；原有原因字符串不改名。


最终交付记录：结构拆分、核心契约修复与用户追加的全部未迁入链路删除合并交付。`engine.py` 从开始时约 784 行缩为 373 行。`workflow.py` 在重命名阶段逐字迁移，后续通用入口接线与缺失链删除由 `design-dispatcher-unmigrated-chain-removal.md` 接管，故最终文件内容不再与旧版本逐字相同；无旧路径兼容入口。

结构理由已归档至 `specs/implemented/architecture/2026-09-15-dispatcher-core-and-capability-pruning.md`。工作区未提交、未推送。最初既有工具面基线为 52 通过、7 失败；删除无实现链路并将旧连接 queryable 断言对齐现行单 RPC 契约后，最终回归全绿。


最终入口复核：无感知需求的已注册技能不应被启动期首帧等待阻塞。将启动期独立首帧循环并入 INIT 的就绪判定；只在队首技能声明需要感知时等待输入。未注册任务也应优先进入失败分发，不能被无关传感器等待掩盖。

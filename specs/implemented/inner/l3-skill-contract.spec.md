# 技能契约

Status: implemented

Contract-ID: l3-dispatcher/skill-contract
Parent: specs/implemented/l3-dispatcher.spec.md

> 定义技能（tool）的身份、生命周期、端口与逆。适用于 `ros_packages/dispatcher`
> 下一切对外任务能力。
> `dispatcher/dispatcher/tools/skill_api.py` 是本契约的参考实现；两者冲突时以本契约为
> 准并修正实现。

## 1. 技能是什么

> 一个技能 = 一种对外任务能力的完整实现：把一次调用翻译为动作意图，并持有
> 该能力专属的子状态。

- 技能是 **l3 对外的唯一任务能力形态**。新增任务能力 = 新增技能，不得在 core
  或执行缝内增加分支。
- 技能按**名字**注册与解析；core 只按名分发，不识别技能内部语义。
- 技能之间不互相调用。共享能力下沉为服务，由各技能分别使用。

## 2. 身份声明

> 每个技能必须静态声明以下三项，缺一即缺陷。

| 声明 | 含义 |
|------|------|
| `name` | 技能的注册名，与调用侧的名字一致；是分发的唯一键 |
| `requires_perception` | 是否需要感知帧；为真时 core 在分发前做决策链就绪检查 |
| `synchronous` | 为真 = 同步执行、不入队、不进感知门，在调用线程内直接完成 |

- 技能身份只有名字一项，**不声明也不依赖任何任务编号**（见
  `l3-dispatcher/core-boundary` B2、B7）。按名分发是唯一的分发依据。

## 3. 生命周期钩子

> 技能通过钩子参与任务生命周期；未覆写的钩子使用模板基类的默认实现。

| 钩子 | 调用时机 | 默认语义 |
|------|----------|----------|
| `on_start` | 调用准入时 | 空 |
| `plan_tick` | 分发态每 tick，携带队首命令 | 返回 False（本技能不处理该命令） |
| `wait_action_tick` | 等待动作完成期间每 tick，在完成门判定之前 | 空 |
| `action_done_gate` | 等待动作完成期间 | 返回 None（无门，走通用判定） |
| `on_action_result` | 动作结果到达 | 返回 `IDLE` |
| `on_cancel` | 调用被取消 | 空 |
| `on_new_prompt_task` | 新任务准入 | 空 |
| `on_global_stop` | 全局停止（软停 / 硬停 / 任务覆盖） | 空 |
| `on_plan_cycle_reset` | 新的分发周期开始 | 空 |

- 新增钩子须先在模板基类提供默认实现，存量技能零改动。
- 技能可在装配期自建自己的订阅与发布端点；端点归属该技能，不进入 core。

## 4. 完成门与裁决

- **完成门**：等待动作完成期间，若技能返回非 None，则由技能裁决动作是否
  完成；返回 None 时回退到通用完成判定。
- **裁决**：动作结束后由技能返回四裁决之一，core 只机械执行：

| 裁决 | core 的执行 |
|------|-------------|
| `REPLAN` | 清理重规划标记，回到分发态，围绕同一条命令继续 |
| `ADVANCE` | 装载下一条命令；队空时上报完成 |
| `IDLE` | 上报任务完成，回到空闲态 |
| `NEW_ACTION` | 技能已自行武装并发布新动作，core 不介入 |

- 完成门与裁决归属于**发布该动作的技能实例**，不按技能名字符串解析。

## 5. 端口

> 技能与宿主之间只经端口交互；端口是唯一合法耦合面。

- 技能**不得**访问宿主私有属性，不得直接操作宿主的队列、状态机与发布器。
- 端口分三类：
  - **入站读取**：最新帧、快速通道图像、配置只读字段；
  - **出站动作**：动作武装、航点下发、规划器模式发布；
  - **生命周期**：相位上报、任务结果暂存、失败终止、代次守卫、队列机械操作。
- 传输原语保持通用：**塑形（偏航、限幅、簿记、模式脉冲）由调用方技能内联
  完成**，传输口不做技能专属塑形。

## 6. 注册即返回逆

> 技能持有的一切外部资源必须随技能生命周期释放。

- 注册技能时**必须返回 disposer**；反注册或宿主停止时调用它。
- 技能自建的订阅、发布、定时器、缓存句柄，全部登记在该 disposer 内。
- 释放顺序与获取顺序相反；异步释放必须被等待完成。
- 禁止"注册时不返回逆、靠后续统一清理"的形态——它使资源归属不可判定。

## 7. 端口清单

> 使用通用 SkillHost 的技能宿主必须提供以下端口；缺失即缺陷，由门禁判定。
> 基础飞行使用 §9 的独立能力协议，按其实际端口集合验收，不伪造无消费者的感知端口。

| 端口 | 类别 | 用途 |
|------|------|------|
| 最新帧读取 | 入站 | 获取当前感知帧 |
| 动作武装 | 出站 | 通用记账：归属快照、代次推进、切至等待完成态 |
| 航点下发 | 出站 | 构造并下发航点目标 |
| 规划器模式发布 | 出站 | 切换规划器模式 |
| 相位上报 | 生命周期 | 上报任务相位与终态 |
| 任务结果暂存 | 生命周期 | 技能暂存任务级结果 |
| 任务结果取出 | 生命周期 | 宿主在终态取走暂存结果 |
| 失败终止 | 生命周期 | 标记任务序列失败的唯一写入口 |
| 代次守卫 | 生命周期 | 阻塞调用前后做代次快照与有效性校验 |
| 队列机械操作 | 生命周期 | 消费队首、推进下一条 |

> 端口名以参考实现 `skill_api.py` 的 `SkillHost` 成员为准；本表按语义分组，一行可能对应多个成员（如"代次守卫"= `capture_task_generation` + `task_generation_valid`，"队列机械操作"= `consume_head_prompt` + `advance_prompt`）。门禁据此判定齐全性。

- 端口增减须先改本契约。
- 技能不得以"端口不存在"的方式降级运行；端口缺失是缺陷，不是运行分支。

## 8. 门禁

| 门禁 | 检查 |
|------|------|
| G13 | 每个技能声明 `name` / `requires_perception` / `synchronous`，且不声明或引用任务编号（§2） |
| G14 | 技能模块不访问宿主私有属性，引用集合是端口白名单的子集（§5） |
| G15 | 技能注册返回 disposer，且 disposer 覆盖该技能自建的全部端点（§6） |
| G16 | 技能之间无直接 import（§1） |
| G17 | 新增钩子在模板基类有默认实现（§3） |

## 9. 基础飞行能力端口

基础飞行使用独立的 FlightHost 宿主端口，成员集由本节定义，由
execution/skill_host 实现通用生命周期；planner 通信由 FlightPorts 承载
（定义于 execution/ports.py，与 VLA 共用）。FlightHost 端口成员为 state、
origin、start_goal、poll_result、cancel_execution、request_takeoff、
request_land、request_safety_stop、publish_phase、fail_sequence、
stash_task_result 和只读 config。它不模拟旧版 engine 属性，不再单独保留
Protocol 类型声明。

原点服务由新鲜 odometry 与显式配置的地面高度判定地面/升空；无地面配置时起飞/原点
不能伪造成功。基础飞行不要求视觉帧；在 cmd 边界内不引入 MAVROS 控制器依赖。

全局停止在清理通用动作状态前通知发布动作的技能实例；取消/覆盖由 dispatcher 推进批次并通过既有目标口发布保持意图，
不要求 planner 提供新增取消端口。技能注册返回幂等 disposer，只移除所注册实例，不误删后注册实例。

## 10. VLA 导航技能语义（navigation.vla_nav）

> 身份与裁决声明；参数 schema、完成语义与发现面归
> `l3-dispatcher/tool-plane` §1，迁移依据归当轮方案。

- **身份**：`name = "navigation.vla_nav"`、`requires_perception = False`
  （机上无需感知帧；odometry 新鲜度/坐标系/有限性由共享执行校验）、
  `synchronous = False`（入队经 DISPATCH 逐 tick 推进）。
- **端口**：使用 §7 通用 SkillHost 端口（最新帧、动作武装、航点下发、模式
  发布、相位上报、任务结果暂存、失败终止、代次守卫、队列机械操作），不新增
  飞行专属端口；航点塑形（高度限幅、mode 脉冲）由技能内联完成。机上不做
  VLM/bbox 推理，也不做几何解算——`waypoint_world` 由站端解算后随调用下行，
  技能不含几何原语源端口。
- **动作完成驱动**：`wait_action_tick` 逐主循环节拍驱动 `host.poll_result()`
  （与 FlightMotion 同构）；`action_done_gate` 返回 None，完成判定走壳通用路径。
- **三裁决**：`ADVANCE` / `IDLE` 沿用 §4 通用语义；`NEW_ACTION` 仅用于技能已
  自行武装并发布新动作的腿（如贴地腿），core 不替其调度。**不设 REPLAN**——
  一轮 DISPATCH 只消费一次 station waypoint：单次解算、单次下发、终态回报，
  无旋转、无重试。
- **fail-closed**：`waypoint_world` 缺失、非恰 3 项或非有限，或 `yaw` 非有限 →
  唯一结构原因 `invalid_station_waypoint`（经工具面 fail 词表贯通到
  `rpc_outcome.reason`）。
- **机上保留项**：高度界 clamp、goal 唯一写入口、取消/保持
  （`l3-dispatcher/execution-seam` §7）、独占与 owner 门、相位与 `rpc_outcome`。

## 11. 场景导航技能语义（scene_nav 家族）

> 身份与裁决声明；参数 schema、完成语义与发现面归
> `l3-dispatcher/tool-plane` §1；图模型、只读边界与能力端口归
> `l3-dispatcher/scenegraph`；迁移依据归当轮方案。

- **身份**（一个技能一个 `name`，逐项注册；`name` 与调用侧工具名一致）：

| `name` | `requires_perception` | `synchronous` | 领域流程 |
|--------|----------------------|---------------|----------|
| `scene.map_search` | `False` | `False` | 图投影与对象清单 |
| `scene.navigate` | `False` | `False` | `object_id_nav` |
| `scene_nav.graph.list` | `False` | `True` | 图查询 |
| `scene_nav.graph.select` | `False` | `True` | 图查询 |
| `scene_nav.graph.save` | `False` | `True` | 图编辑 |
| `scene_nav.graph.objects` | `False` | `True` | 图查询 |
| `scene_nav.graph.object_pose` | `False` | `True` | 图编辑 |

- **同步技能**（`scene_nav.graph.*`）：`synchronous = True`，在调用线程内直接完成，
  不进感知门、不入队（§2）；自建端点随 disposer 释放（§6）。
- **`scene.navigate` 的 object 级子状态**（技能自有，§1「技能持有该能力专属的子状态」）：
  目标对象身份、目标位置 [m]（= 对象所挂多面体中心，`l3-dispatcher/scenegraph` §5）、
  目标偏航 [rad]（= 该节点到对象的水平 bearing；水平重合时保留对象
  `orientation_xyzw` 锚点、无锚点则 0）、终态高度（对象派生的观测高度）、
  到达判据（位置 + 终端偏航双条件；到达半径度量到所挂拓扑节点，不是到对象）、
  任务级超时与重规划上限、目标所属多面体。
- **端口**：使用 §7 通用 SkillHost 端口；图数据经宿主注入的感知数据面端口只读获取
  （`l3-dispatcher/package-layout` §3 的感知单向流动）；航点塑形（近点跳过、巡航高度
  统一、限幅、偏航模式脉冲）由技能内联完成（§5），传输口不做技能专属塑形。
- **四裁决**：`scene.navigate` 在 `on_action_result` 内按自有状态判定并返回
  `ADVANCE`（续下一条命令）或 `IDLE`（收敛完成），**不读取宿主
  `ActionGate.pending_action` 等私有对象**（§5、G14）；`scene.map_search` 与同步技能
  在完成门内收敛后返回 `IDLE`。
- **终态原因词表**（对象级，`scene.navigate`）：`reached`、`unreachable`、`timeout`、
  `failed`；取消与覆盖的终态归 `l3-dispatcher/tool-plane` §5，技能不另造终态。
- **结果**：`scene.navigate` 的终态结果至少含对象身份、到达与否、最终位置 [m]、
  最终偏航 [rad]、原因；`scene.map_search` 的结果为对象清单（id / label / 位置 [m]）。
  结果经任务结果暂存端口上报、由宿主在终态取走（§5）。
- **fail-closed**：图未就绪、对象不存在、无通路、当前位置无法挂载，一律上报对应原因
  并收敛为失败终态；不得静默成功，不得以「航点批次结束」冒充到达
  （`l3-dispatcher/scenegraph` §6、§7）。
- **配置参数**：前缀 `~scene_nav/*`（家族名，规则归 `l3-dispatcher/package-layout` §2），
  唯一权威、键名不重复前缀、子组嵌套：

| 参数键 | 类型 | 默认 | 消费技能 |
|--------|------|------|----------|
| `~scene_nav/graph_json_topic` | `string` | `/scene_graph/json_text` | `scene.map_search` |
| `~scene_nav/planner_fsm_state_topic` | `string` | `/planner/fsm_state` | `scene.navigate` |
| `~scene_nav/json_wait_timeout_s` | `double` | `3.0` | `scene.map_search` |
| `~scene_nav/trigger_timeout_s` | `double` | `5.0` | `scene.navigate` |
| `~scene_nav/waypoint_skip_xy_distance_m` | `double` | `0.3` | `scene.navigate` |
| `~scene_nav/task_timeout_s` | `double` | `45.0` | `scene.navigate` |
| `~scene_nav/task_terminal_timeout_s` | `double` | `15.0` | `scene.navigate` |
| `~scene_nav/task_max_replans` | `int` | `1` | `scene.navigate` |
| `~scene_nav/require_final_yaw` | `bool` | `true` | `scene.navigate` |
| `~scene_nav/final_yaw_tolerance_deg` | `double` | `10.0` | `scene.navigate` |
| `~scene_nav/final_approach_max_attempts` | `int` | `6` | `scene.navigate` |
| `~scene_nav/replan/enable` | `bool` | `true` | `scene.navigate` |
| `~scene_nav/replan/stuck_yaw_rate_threshold_rad_s` | `double` | `0.1` | `scene.navigate` |
| `~scene_nav/replan/mode2_stuck_fallback_delay_s` | `double` | 装配层显式给出 | `scene.navigate` |

- 上表为**有意变更**，三项归一：
  1. **前缀**：旧库 `object_id_nav/*`、`object_id_nav_replan/*`、`scene_nav_*` 平铺键
     归一为家族前缀 `~scene_nav/*`，子组改嵌套（`replan/*`）；
  2. **宿主**：由 mission_executive 私有空间改为 dispatcher 私有空间；
  3. **键名**：补单位后缀（`_m`/`_s`/`_deg`/`_rad_s`）、缩写写全
     （`stuck_yaw_rate_thresh` → `stuck_yaw_rate_threshold_rad_s`）。
  新库部署配置由 P2 首次写入该组，无既有依赖需要兼容。
- **承载**：本表由 `tools/scene_nav/scene_nav_ports.py` 的 `SceneNavConfig`
  （`@dataclass(frozen=True)`）单类承载，字段名即键名；装配层经 `fields()` 批量派生
  `~scene_nav/<字段名>`，不得留裸关键字参数或第二份同名配置。
- 激活图名（旧库经全局参数 `fsm/scene_graph_load_name`、`/scene_graph/active_name`
  直读）**不作为参数**：经端口/共享状态提供（`l3-dispatcher/ros-adapter-boundary`
  R3/R5），技能不得直读全局参数。

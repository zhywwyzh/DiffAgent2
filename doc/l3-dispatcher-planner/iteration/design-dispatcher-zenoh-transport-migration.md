# Dispatcher Zenoh 传输迁移（旧版 → 新版）方案

> 摘要：把 DiffAgent2 旧版 dispatcher 的 zenoh 通信/工具运行时整体迁移到
> 新版内置子树 `l3-dispatcher-planner/`，恢复 tools 面、租约面与 agent_log
> 可靠上行；引擎侧预留缝（`zenoh_middleware`）随迁复活。范围：传输层 +
> 工具运行时七件套 + 引擎执行缝（分批）+ 启动入口；不迁技能族、不迁
> recording、不迁构建面。
>
> 依据：DiffAgent2 旧版
> `diff-dockers/drone_projects/l3-dispatcher-planner/ros_packages/dispatcher/`
> （下称 OLD），DiffAgent2 新版
> `l3-dispatcher-planner/ros_packages/dispatcher/`（下称 NEW）。

## 0. 元信息

| 项 | 值 |
|----|----|
| 日期 | 2026-09-11 |
| 目标路径 | `l3-dispatcher-planner/ros_packages/dispatcher/dispatcher/` |
| 状态 | done（代码面；环境验收项见 §11） |
| 关联文档 | `design-dispatcher-core-inference-migration.md`（决策 9：L203「中间件轮次迁入即复活」；L277 `bind_tool_middleware` 未迁恒 None）；`design-dispatcher-engine-narrow-core-trim.md`（L93 zenoh_middleware 为闭包保留壳属性） |

## 1. 背景与动机

旧版 dispatcher 的 zenoh 通信由 `ZenohTaskMiddleware`（zenoh_rpc.py）一族
承载：zenoh session（client 连 bootstrap router）、`lx/<stack-id>/tools/*`
任务面 + 租约面、agent_log 可靠上行、工具运行时准入/执行/取消。经窄 core
(`design-dispatcher-engine-narrow-core-trim.md`) 与 core-inference
(`design-dispatcher-core-inference-migration.md`) 两轮裁剪后，NEW 引擎只
保留了预留缝 `zenoh_middleware = None` 与其 None 守卫出口，中间件一族
整体未迁——`zenoh_middleware` 恒 None，l4 智能体无法经 zenoh 触达工具面。

本文档记录将 zenoh 通信/工具运行时从 OLD 迁入 NEW 的方案：迁什么、
为什么不能原样平迁（依赖缺口）、分批顺序与验收。

## 2. 现状事实（问题清单）

> 每条带「文件路径 + 行号」证据。

**NEW 侧预留缝（已就位，零手术可直接接上）**
- [x] `NEW/dispatcher/dispatcher/engine.py#L178` — `self.zenoh_middleware = None`
- [x] `NEW/dispatcher/dispatcher/engine.py#L343-L345` — `_publish_task_phase` 内
      `if self.zenoh_middleware is not None: self.zenoh_middleware.on_tool_phase(payload)`。
      迁入整套中间件后此出口自动复活，无需改行。
- [x] `NEW/dispatcher/dispatcher/engine.py#L188` — `_skills: dict = {}` 空表（P3
      注册表分发骨架，技能轮次填表；`start_tool_workflow` 依赖它做 `skill.on_start` 分发）。
- [x] `NEW/dispatcher/dispatcher/tools/model.py` — 传输无关工具模型
      `ToolCall`/`SkillCommand`/`ToolCommand`/`ToolSpec`/`ToolProtocolError` 已存在。

**NEW 侧缺失（需迁入）**
- [x] `NEW/…/dispatcher/` 无 `zenoh_rpc.py`、`connection_lease.py`、`rpc_plane.py`、
      `recording.py`（LS 实览仅 `__init__/config/engine/skill_api/slog/state` +
      `perception/` + `tools/{__init__,model}.py`）。
- [x] `NEW/…/dispatcher/tools/` 仅 `__init__.py` + `model.py`；缺
      `registry.py`/`runtime.py`/`executor.py`/`control_plane.py`。
- [x] `NEW/…/dispatcher/` 无 `dispatcher_node.py` 启动入口（Glob 零命中；
      `ros_packages/dispatcher/` 下也无 `setup.py`/`package.xml`/`launch`）。
- [x] OLD `engine.py#L867-L986` 的 6 个执行缝在 NEW `engine.py` 全部缺失
      （`bind_tool_middleware`/`_activate_tool_call`/`forward_takeoff_tool`/
      `forward_land_tool`/`forward_emergency_stop_tool`/`start_tool_workflow`/
      `cancel_tool_call`；grep 零命中）。

**OLD 侧依赖缺口（决定性事实：6 缝不能原样平迁）**
- [x] NEW `engine.py` grep 零命中：`_start_prompt_task`、`_handle_takeoff_land`、
      `_handle_global_control_command`、`task_action_client`、
      `current_task_id`、`latest_agent_prompt_frame_id`（仅 L322 注释残留）、
      `_active_tool_call`、`process_log_path`/`action_log_path`/`stop_log_path`、
      `_recording`、`TakeoffLand`、`_decision_chain_not_ready_reason`。
- [x] NEW `engine.py` 命中（可复用）：`task_generation`（L133/L452-L460）、
      `_enter_global_stop`（L462）、`_telemetry`、`_skills.get`、`_publish_task_phase`。
- [x] 结论：OLD 6 缝中 `forward_*_tool`/`start_tool_workflow` 依赖的
      `_handle_takeoff_land`/`_handle_global_control_command`/`_start_prompt_task`/
      `task_action_client` 属窄 core 已裁剪、归后续 P3 技能/任务注入轮次的部分；
      直接平迁会引入孤儿引用（违反「静态自洽」）。

**OLD 侧迁移源（已核实）**
- [x] `OLD/…/dispatcher/zenoh_rpc.py`（612 行）：
      `__init__` L52-L105（`LX_STACK_ID` 必需 L61-L63、`ZENOH_ROUTER` L64、
      `prefix=lx/<stack-id>`、registry/leases/runtime 装配、`rpc_plane=None` 预留、
      agent_log outbox）；`start()` L133-L186（client 模式 + 禁 multicast scouting
      L135-L138、agent_log publisher BLOCK+RELIABLE（TypeError 降级）L142-L160、
      4 个 queryable `complete=True` L161-L172、`RpcPlane` 恒启动 L174-L178、
      liveliness presence token L179、ROS 订阅/租约 watchdog/agent_log worker L180-L182）。
- [x] `OLD/…/dispatcher/tools/control_plane.py`（全文 86 行）：装配
      `ZenohTaskMiddleware(self._commands)` → `ToolExecutor(middleware.registry, host)`
      → `host.bind_tool_middleware(self.middleware)`；`start()` 起
      `tool-command-consumer` + `zenoh-tool-server`（`_serve` 5s 重连监督）。
- [x] `OLD/…/dispatcher/engine.py#L867-L986`：6 缝方法体（依赖明细见 §4 决策点）。
- [x] `OLD/…/dispatcher_node.py`（全文 48 行）：composition root——
      `rospy.init_node` → `create_dispatcher_engine(config_path)` →
      `ToolControlPlane(engine).start()` → `start_dispatcher_workers(engine)` →
      `rospy.spin()`；`control_plane.close()` 收尾。

**构建面**
- [x] NEW `l3-dispatcher-planner/` 顶层仅 `ros_packages/`（LS 实览），无
      `pyproject.toml`/`Dockerfile`/`launch`/`uv.lock`；OLD 侧依赖声明
      `eclipse-zenoh==1.5.1` 位于 OLD `pyproject.toml`、`docker/{amd64,arm64}/Dockerfile`、
      `docker/wheelhouse/requirements-*`。按 AGENTS.md，`docker_registry/`、
      `drone_projects/auto_deployer/` 等构建面内容暂不迁移——本方案只记录依赖
      版本契约，构建面声明由编排仓库后续轮次负责。

## 3. 目标与约束

- **目标**：
  1. 将 OLD 的 zenoh 传输层 + 工具运行时七件套按原实现迁入 NEW；
  2. 恢复引擎侧 `_publish_task_phase` → `on_tool_phase` 出口（零手术直连）；
  3. 迁入后可独立验证：session 打开、queryable/租约面声明、工具准入/取消、
     agent_log 上行（mock 或连真 router）。
- **Non-Goals**：
  - 不迁移技能族（`tools/flight`、`tools/grasp`、`tools/scene_nav`、`tools/vla`）
    及其直发语义（`_handle_takeoff_land`/`_handle_global_control_command`）——归后续
    P3 技能轮次；`forward_*_tool`/`start_tool_workflow` 的执行语义据此分批（§4 D5/D6）。
  - 不迁移 `recording.py` 与日志路径（agent_log snapshot 三流注册对 recording
    依赖做 None 容忍）；除非用户点名随迁。
  - 不激活 RpcPlane 之外的任何新锁步面；RpcPlane 随 OLD `start()` 语义原样迁入
    （OLD 即恒启动，见 `zenoh_rpc.py#L174-L178`）。
  - 不迁移构建面（pyproject/Dockerfile/wheelhouse）——依赖版本契约
    `eclipse-zenoh==1.5.1` 此处记录，声明由构建面轮次落。
- **硬边界**：
  - 禁止新设计转接器桥接新旧接口：直接用 OLD 实现，缺口处做「字段补初始化 /
    None 守卫 / 删除孤行」（§4），不新建 adapter 层。
  - 过期必删：本轮为迁入，不改 OLD；切流确认后在 OLD 侧删除对应模块（另行明确指令执行）。

## 4. 方案决策

- **目标目录树（新增/补齐后）**：

  ```
  ros_packages/dispatcher/
    dispatcher_node.py                 # 新增：composition root（copy + 适配）
    dispatcher/
      zenoh_rpc.py                     # copy：ZenohTaskMiddleware
      connection_lease.py              # copy：ConnectionLeaseManager
      rpc_plane.py                     # copy：RpcPlane（锁步面，OLD 恒启动）
      tools/
        __init__.py                    # retain（按需补导出）
        model.py                       # retain（已存在，核对差异）
        registry.py                    # copy：ToolRegistry + 默认工具规格
        runtime.py                     # copy：ToolRuntime
        executor.py                    # copy：ToolExecutor
        control_plane.py               # copy：ToolControlPlane
      engine.py                        # merge：首批 3 缝 + __init__ 补字段（§4 D3/D4/D6）
  ```

- **命名规范**：维持 OLD 命名原样（`ZenohTaskMiddleware`/`ToolControlPlane`/
  `ToolRuntime`/`ToolRegistry`/`ToolExecutor`/`ConnectionLeaseManager`/`RpcPlane`），
  不新建别名、不改名——避免在 NEW 引入第二套命名。

- **接口形态**：维持 OLD 契约不变——
  - composition root：`create_dispatcher_engine(config_path)` +
    `ToolControlPlane(engine).start()` + `start_dispatcher_workers(engine)`；
  - `ToolControlPlane(host)` 构造：`host.bind_tool_middleware(middleware)`；
  - 6 缝方法签名（`ToolCall`/`SkillCommand` 参数）与 OLD 一致。

- **决策点（需要确认/按默认值执行）**：

  | # | 决策 | 默认裁决 | 理由 |
  |---|------|---------|------|
  | D1 | 传输 + 运行时七件套（zenoh_rpc/connection_lease/rpc_plane/tools{registry,runtime,executor,control_plane}） | **原样 copy** | 相互依赖自洽（zenoh_rpc 引 registry/runtime/connection_lease/rpc_plane；control_plane 引 zenoh_rpc/executor），不依赖被裁引擎符号；可独立验证 |
  | D2 | `tools/model.py` | **retain 核对** | NEW 已存在且为传输无关模型；与 OLD 版本 diff 确认无字段缺失（尤其 `SkillCommand` 是否携带原生 `ToolCall`） |
  | D3 | `bind_tool_middleware` | **迁入 + 适配 2 行** | OLD L878 `self._recording._publish_latest_log_if_pending()` 与 L873-L877 `process/action/stop_log_path` 三件套依赖 recording——NEW 无；裁决：`middleware.agent_log_snapshot_files` 三流注册字段保留（middleware 侧已容忍 dict），engine 侧路径取自 `getattr(self, "_recording", None)` 守卫或删除，recording 轮次复活 |
  | D4 | `_activate_tool_call` | **迁入 + `__init__` 补字段** | OLD L880-L894 引用 `_active_tool_call`/`latest_agent_prompt_frame_id`/`current_task_id`（NEW 缺失）；裁决：在 NEW `__init__` 补 `self._active_tool_call = None`、`self.latest_agent_prompt_frame_id = "Null"`（与 OLD L568-L573 语义一致）、`self.current_task_id = 0` 初始化，不改方法体 |
  | D5 | `forward_takeoff_tool`/`forward_land_tool`/`forward_emergency_stop_tool` | **默认不迁（后续技能轮次）** | 依赖 `_handle_takeoff_land`/`_handle_global_control_command`/`task_action_client`/`TakeoffLand`（NEW 全部零命中，窄 core 已裁）；平迁即孤儿引用。若用户点名随迁，则连座迁 `_handle_takeoff_land` + `_handle_global_control_command` + `task_action_client` 初始化（超出 zenoh 通信面，需单独确认） |
  | D6 | `start_tool_workflow`/`cancel_tool_call` | **框架迁入，执行语义限界** | `start_tool_workflow`：`_skills.get`→`skill.on_start`（契约在，空表走通用路径）、`_publish_task_phase("planning")` 可跑；`_start_prompt_task` 调用行（OLD L960-L965）本轮以 `from dispatcher.engine import _start_prompt_task` 缺失为界——裁决：迁入方法体但保留 `_start_prompt_task` 调用（运行期此分支依赖空注册表命中即 return，不触发），或显式标注待任务注入轮次；`cancel_tool_call`：依赖 `_enter_global_stop`（存在）+ `task_action_client.cancel_all_goals()` 一行加 None 守卫 + `mark_cancelled`（middleware 侧） |
  | D7 | `dispatcher_node.py` | **copy（新增）** | OLD 全文可直接复用；import 路径不变（`dispatcher.tools.control_plane`）；NEW 尚无此入口，属本轮必迁项 |
  | D8 | `RpcPlane` 激活 | **随 OLD 原样（恒启动）** | OLD `zenoh_rpc.start()` L174-L178 即为恒启动；锁步采用与否是部署策略，非迁移范围 |
  | D9 | 工具默认规格中的异步工具分发 | **随 registry/executor 原样** | `ToolExecutor.execute`：三条直发调用 `host.forward_*_tool`（方法未迁则命中 `AttributeError` → 工具级报错而非崩溃，D5 后技能轮次复活）；其余走 `host.start_tool_workflow` |

- **旧接口 → 删除**：本轮无（纯迁入）；OLD 在切流确认前保留，不删、不注释桩。

## 5. 迁移映射表

> OLD → NEW → 动作。OLD 前缀：
> `diff-dockers/drone_projects/l3-dispatcher-planner/ros_packages/dispatcher/dispatcher/`；
> NEW 前缀：`l3-dispatcher-planner/ros_packages/dispatcher/dispatcher/`。

| OLD 路径/命名 | NEW 路径/命名 | 动作 | 备注 |
|---------------|---------------|------|------|
| `zenoh_rpc.py`（`ZenohTaskMiddleware`） | `zenoh_rpc.py` | copy（原样） | 唯一改动点留 §4 D3（snapshot 三流） |
| `connection_lease.py`（`ConnectionLeaseManager`） | `connection_lease.py` | copy（原样） | 无引擎依赖，自洽 |
| `rpc_plane.py`（`RpcPlane`） | `rpc_plane.py` | copy（原样） | 锁步面，OLD 恒启动 |
| `tools/registry.py`（`ToolRegistry`） | `tools/registry.py` | copy（原样） | `INVALID_PARAMS`/`METHOD_NOT_FOUND` 常量随迁 |
| `tools/runtime.py`（`ToolRuntime`） | `tools/runtime.py` | copy（原样） | `call_id_for_frame`/`cancel_active_for_lease_loss`/`issue_safety_stop` 等 |
| `tools/executor.py`（`ToolExecutor`） | `tools/executor.py` | copy（原样） | 直发 + 工作流分发（§4 D9） |
| `tools/control_plane.py`（`ToolControlPlane`） | `tools/control_plane.py` | copy（原样） | 装配 + 双守护线程 |
| `tools/model.py` | `tools/model.py` | retain（diff 核对） | NEW 已存在 |
| `engine.py` L867-L878（`bind_tool_middleware`） | `engine.py` | merge（§4 D3） | 适配 recording 依赖 |
| `engine.py` L880-L894（`_activate_tool_call`） | `engine.py` | merge（§4 D4） | `__init__` 补 3 字段 |
| `engine.py` L896-L920（三条 forward） | `engine.py` | 默认不迁（§4 D5） | 随技能轮次 |
| `engine.py` L922-L965（`start_tool_workflow`） | `engine.py` | merge（框架，§4 D6） | planning 入队待任务注入轮次 |
| `engine.py` L967-L986（`cancel_tool_call`） | `engine.py` | merge（§4 D6） | `task_action_client` 行 None 守卫 |
| `dispatcher_node.py` | `dispatcher_node.py` | copy（新增） | composition root，全文复用 |
| `recording.py` | — | 默认不迁（§3 Non-Goals） | agent_log snapshot 依赖先做容忍，recording 轮次补 |
| `pyproject.toml`/docker/wheelhouse（`eclipse-zenoh==1.5.1`） | 构建面 | 契约记录，声明轮次落地 | AGENTS.md：docker_registry/auto_deployer 暂不迁移 |
| OLD `tests/zenoh-bench`、`tests/tool-registry`、`tests/telemetry-bridge` | NEW tests（若存在测试目录） | copy（路径适配） | 迁移验证工具 |

## 6. 删除清单

> 本轮为迁入轮，无删除。约束备忘：
> - 切流确认后，OLD 侧对应模块与 `_handle_takeoff_land` 等被替代路径按
>   「过期必删」直接删除，不留转接口（另行显式指令）。
> - NEW 侧不因 D3/D4/D6 引入任何残留桩：不迁的方法（D5）不落空壳注释。

| 删除项 | 理由 |
|--------|------|
| （无） | 纯迁入轮；删除动作待切流指令 |

## 7. 实施步骤（P0/P1/P2/P3 分期）

> 每期：范围 + 行为不变式 + 验收 + 回退。

### P0 — 依赖与基线

- 范围：确认 `eclipse-zenoh==1.5.1`（与 OLD 锁定一致）可在 NEW 环境导入
  `import zenoh`；`py_compile` NEW 现有包；把 OLD 测试（tool-registry /
  zenoh-bench）拷入 NEW tests 并适配路径。
- 行为不变式：不触碰 `engine.py` 现有保留方法体。
- 验收：`python -c "import zenoh"` 通过；`py_compile` 全绿。
- 回退：删除测试副本即可，无代码残留。

### P1 — 传输 + 运行时七件套平迁

- 范围：copy `zenoh_rpc.py`/`connection_lease.py`/`rpc_plane.py`/
  `tools/{registry,runtime,executor,control_plane}.py`；diff 核对 `tools/model.py`；
  `tools/__init__.py` 补导出（`ToolProtocolError`/`ToolRegistry`/`ToolRuntime` 等，
  与 OLD 一致）。
- 行为不变式：模块级自洽——`python -c "import dispatcher.zenoh_rpc"` 可导入
  （session 未开，仅构造）；不依赖 engine 任何符号。
- 验收：OLD `tests/tool-registry`（connection_lease / rpc_plane_navigation）
  在 NEW 全绿；`ZenohTaskMiddleware.__init__` 缺 `LX_STACK_ID` 仍抛
  `RuntimeError`（等价 OLD L61-L63）。
- 回退：删新增文件 + 还原 `tools/__init__.py`。

### P2 — 引擎首批缝（D3/D4/D6 可独立部分）

- 范围：`bind_tool_middleware`（recording 行适配）、`_activate_tool_call`
  （`__init__` 补 `_active_tool_call/latest_agent_prompt_frame_id/current_task_id`）、
  `cancel_tool_call`（`task_action_client` 行 None 守卫）；`start_tool_workflow`
  迁入框架（空注册表下 `skill is None` → 走 planning 发布，`_start_prompt_task`
  调用行按 §4 D6 限界标注）。
- 行为不变式：`_publish_task_phase` 的 None 守卫出口零改行；
  新缝不改变现有 FSM 语义（`zenoh_middleware` 未绑定时行为与现状一致）。
- 验收：`py_compile` 通过；绑定 mock middleware 后调用
  `engine.cancel_tool_call(call, "test")` 不抛、走 `mark_cancelled`；
  `engine.bind_tool_middleware(mock)` 后 `_publish_task_phase` 触发
  `mock.on_tool_phase(payload)`。
- 回退：摘除新缝方法与 `__init__` 补字段（字段保留为壳亦可，等价决策 12 语境）。

### P3 — 启动入口与环境（D7）

- 范围：copy `dispatcher_node.py`；确认部署环境注入 `LX_STACK_ID`、
  `ZENOH_ROUTER`（默认 `tcp/public_zenohd_router:7447`）、ROS 订阅 topic
  （`/Instruct_res`、grasp_result_image、`/agent_scene_objects`）。
- 行为不变式：`ToolControlPlane.start()` 起两守护线程；
  `_serve` 5s 重连监督不阻塞主线程。
- 验收：环境就位后启动，日志见
  `[zenoh_rpc] rpc plane up: lx/<stack-id>/rpc via <router>`（等价 OLD L183-L186）；
  站侧 `verify_routing.py` 走通 tools 面/租约面。
- 回退：不部署该入口即可（NEW 原本无入口），无残留。

## 8. 验收标准

> 可执行判断。

- [ ] `py_compile` NEW 全部 `.py` 通过（含新缝/新模块）
- [ ] `import zenoh`（`eclipse-zenoh==1.5.1`）成功
- [ ] OLD `tests/tool-registry/test_connection_lease.py`、
      `test_rpc_plane_navigation.py`、`tests/zenoh-bench/verify_routing.py` 在
      NEW 全绿（路径适配后）
- [ ] `ZenohTaskMiddleware.__init__` 缺 `LX_STACK_ID` 抛 `RuntimeError`
      （等价 OLD zenoh_rpc.py L61-L63）
- [ ] 绑定 mock middleware：`_publish_task_phase` → `on_tool_phase(payload)`
      触发；`cancel_tool_call` → `mark_cancelled` 触发
- [ ] 真 router 冒烟：session 打开、4 个 queryable `complete=True` 声明成功、
      presence token 上线、agent_log publisher 声明（BLOCK+RELIABLE）
- [ ] `on_tool_phase` 的 `runtime.call_id_for_frame(frame_id)` 回退路径保留
      （等价 OLD L540：engine 只传 frame_id）
- [ ] slog 事件名 / topic / param 名与 OLD 字节级一致（`dispatcher_started`、
      `task_phase_published`、`tool_call_received` 等）

## 9. 风险与对策

| 风险 | 影响 | 对策 |
|------|------|------|
| 6 缝依赖符号在 NEW 大面积缺失（§2） | 原样平迁产生孤儿引用 | 分批：传输/运行时独立验证；缝按 D3-D6 适配（字段补初始化 + None 守卫），禁止造 adapter |
| `forward_*_tool` 未迁期间 executor 直发命中 `AttributeError` | 工具级 fail 事件而非崩溃 | 已在 control_plane `_consume` 的兜底 emit fail 内（OLD control_plane.py L59-L72 原样迁入）；D5 后技能轮次复活 |
| RpcPlane 锁步面消费端未就位 | 面上查询无应答 | 随 OLD 恒启动语义迁入，部署不启用即无消费；行为与 OLD 一致，非 NEW 新增行为 |
| zenoh router（ZeroTier 网络）不可达 | middleware start 失败阻塞 | `_serve` 内置 5s 重连监督（control_plane 原样迁入）；不阻塞 engine 主线程 |
| agent_log snapshot 依赖 recording（未迁） | snapshot 拉取 404 | `bind_tool_middleware` 对 `_recording` 引用做守卫/删除，`agent_log_snapshot_files` 字段容忍空（middleware 侧已是 dict 契约）；recording 轮次恢复三流注册 |
| OLD 工具默认规格含 vla/grasp 等未迁工具名 | 站端查到不存在的工具 | `ToolRegistry._specs()` 原样迁入即可（规格是传输契约，工具未实现时执行走 fail 事件，不 crash）；如需收窄规格属业务决策，另行确认 |

## 10. 修改点清单汇总

| 文件 | 动作 | 说明 |
|------|------|------|
| `l3-dispatcher-planner/ros_packages/dispatcher/dispatcher/zenoh_rpc.py` | 新增（copy） | D3：snapshot 三流注册处适配 |
| `…/dispatcher/connection_lease.py` | 新增（copy） | 原样 |
| `…/dispatcher/rpc_plane.py` | 新增（copy） | 原样 |
| `…/dispatcher/tools/registry.py` | 新增（copy） | 原样 |
| `…/dispatcher/tools/runtime.py` | 新增（copy） | 原样 |
| `…/dispatcher/tools/executor.py` | 新增（copy） | 原样 |
| `…/dispatcher/tools/control_plane.py` | 新增（copy） | 原样 |
| `…/dispatcher/tools/__init__.py` | 修改 | 补导出（对齐 OLD） |
| `…/dispatcher/tools/model.py` | 核对 | diff 确认与 OLD 一致 |
| `…/dispatcher/engine.py` | 修改 | 3+2 缝迁入（D3/D4/D6）；`__init__` 补 3 字段；D5 不迁 |
| `…/dispatcher_node.py` | 新增（copy） | composition root（D7） |
| tests（`zenoh-bench`/`tool-registry`/`telemetry-bridge`） | 新增（copy） | 路径适配 |
| 构建面（`eclipse-zenoh==1.5.1` 声明） | 契约记录 | 构建面轮次落地（AGENTS.md） |

## 11. 执行记录（2026-09-11）

### 11.1 完成情况

P0-P3 代码面全部落地，与 §10 清单一一对应：

- 七件套 + `dispatcher_node.py`：与 OLD `diff -q` 字节级一致；
- `tools/model.py`：diff 确认两侧本就一致，未改；
- `tools/__init__.py`：OLD 版本覆盖对齐导出；
- `engine.py`：两个 hunk——`__init__` 补 4 字段
  （`_active_tool_call=None`/`latest_agent_prompt_frame_id="Null"`/
  `current_task_id=0`/`task_action_client=None`）+ 4 缝方法迁入
  （`bind_tool_middleware`/`_activate_tool_call`/`start_tool_workflow`/
  `cancel_tool_call`）；D5 三条 forward 零代码零桩；
- tests 三目录（tool-registry/zenoh-bench/telemetry-bridge）copy；
  sys.path 相对推导与 NEW 结构天然一致，零适配；OLD 顶层 `conftest.py`
  （ros_stub）未迁——三个目录的测试不依赖它。

### 11.2 验证结果（本机）

- [x] `py_compile` NEW 全部 `.py`（含新模块/engine/入口/tests）全绿；
- [x] `pytest tool-registry`：`test_tool_registry.py` +
      `test_rpc_plane_basic_flight.py` **35 passed**；
      `test_rpc_plane_navigation.py` 非 scene_graph 部分 26 passed，
      6 个 scene_graph 测试因 `dispatcher.tools.scene_nav` 未迁（§3
      Non-Goals）失败——预期内；
- [ ] `import zenoh`：本机未装 `eclipse-zenoh==1.5.1`，
      `test_connection_lease.py` 因模块级 import 收集失败——**待部署
      环境确认**；
- [ ] 真 router 冒烟（session/queryable/presence/agent_log 声明）——
      **待部署环境**（需 `LX_STACK_ID`/`ZENOH_ROUTER`）。

### 11.3 deep-oracle 评审结论：PASS with notes（高置信）

5 项重点（缝与 FSM 兼容性/孤儿引用/守卫非 adapter/直发兜底/启动入口）
全部通过。评审发现的 N1/N2 已于当日修复（见 11.4）；遗留约束见 11.5。

### 11.4 评审修复（N1+N2，已落地并回归）

- **N1 悬空终态**：守卫 return 前补 `_publish_task_phase("fail", …,
  error={"code": "task_injection_not_migrated", …}, frame_id=call.frame_id)`——
  经 `on_tool_phase` 的 frame→call_id 回退（zenoh_rpc.py L544-L552）终态化
  并释放 runtime `_active_call_id`，站端不悬空；
- **N2 记账残留**：守卫整体前移至 `_activate_tool_call` 之前（能力预检 →
  记账 → 执行），缺失时不污染 `_active_tool_name`/
  `_active_task_frame_id`/`latest_agent_prompt_frame_id`；
- 修复后 `py_compile` + 35 测试回归全绿。

### 11.5 后续轮次必须处理项（评审遗留，按优先级）

| # | 事项 | 时限 |
|---|------|------|
| 1 | 急停工具 fail-before-execute：registry 广播 `flight.emergency_stop` 但 executor 直发命中 AttributeError（站端收 fail、实际无急停动作）——至少先迁 `forward_emergency_stop_tool` 一条 | 入口部署前 |
| 2 | 任务注入轮次迁 `_start_prompt_task` 时**连座** `_decision_chain_not_ready_reason`（否则守卫移除后 engine.py L494 变可达孤儿）+ 删除 hasattr 守卫（L461） | 任务注入轮次 |
| 3 | 技能轮次：`_notify_skills`（含 `on_global_stop` 钩子）、grasp 工作流线程、D5 三条 forward 连座迁入 | 技能轮次 |
| 4 | recording 轮次：恢复 snapshot 三流注册与 `_publish_latest_log_if_pending`（当前空 dict，`agent_log/snapshot` 返回结构化 resource_not_found，不崩溃可接受） | recording 轮次 |
| 5 | `_enter_global_stop` 与 OLD 三处行为差（record_stop_event/`_notify_skills`/hold 位置发布）随对应轮次对齐 | 对应轮次 |

### 11.6 其他披露

- **窗口期语义**：NEW 当前为「工具面完整广播、执行面半残」中间态——
  站端可见工具数多于可执行数，误调用产生 fail 事件（排障噪音集中在
  `_consume` 兜底日志）。部署文档应标注此窗口期。
- **pre-existing 改动**：`engine.py` 工作区 diff 中
  `@@ -283,19 +292,6 @@`（`_set_dispatcher_state` 内被注释的调试
  logwarn 块删除）为执行前已存在的未提交改动，非本方案所为，未触碰。
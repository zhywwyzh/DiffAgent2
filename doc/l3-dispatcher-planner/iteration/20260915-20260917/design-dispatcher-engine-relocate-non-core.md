# DispatcherEngine 非 core 职责迁出 + core 四通道适配落位（S3 执行版）方案

> 摘要：本方案是总纲 `design-dispatcher-architecture-stabilization.md` §4.7 **S3 期**的执行版，
> **服从总纲 §4.1 目标目录树与 §4.2 依赖矩阵**（不得自行改树）。做什么：把 `engine.py` 中
> 非 core 的协作职责迁入 `dispatcher/core/`，把四类 core 通道（急停 / `if_handle_yaw` /
> 命令内容监控 / 任务相位）的 **ROS 实现一次性落到** `dispatcher/ros_adapter/core_channels_ros.py`
> （**避免「先搬进 core、S4 再拆 ROS」的二次搬迁**），装配函数
> （`create_dispatcher_engine` / `start_dispatcher_workers`）入 `dispatcher_node.py`；
> 迁移后 `engine.py` 与 `dispatcher/core/` **零 `rospy`**（G7）。
> 范围：`l3-dispatcher-planner/ros_packages/dispatcher/` 内的 `engine.py`、新增
> `dispatcher/core/`、`dispatcher/ros_adapter/`、`dispatcher_node.py`。
> 依据：现状事实取自**本次实测**的当前工作区（`dispatcher/engine.py` 计 **1067 行**，`wc -l` 实测），
> 取代本文旧版（其证据基线为 1055 行版 engine，映射行号已过期——总纲 §2.B 已勘误）。
>
> 契约：`specs/implemented/l3-dispatcher.spec.md`（六态 / 无任务编号 / 收发集中 / 未注册即失败 /
> 终态唯一）；`specs/implemented/inner/l3-core-boundary.spec.md`（B1/B3/B4/B5/G2/G4）；
> `specs/implemented/inner/l3-ros-adapter-boundary.spec.md`（R1/R2/R4/R5/G7/G8/G9）；
> `specs/implemented/inner/l3-skill-contract.spec.md`（`SkillHost` 端口，不得增删）。
>
> 姊妹篇：总纲（约束权威）、前置 S2 `design-dispatcher-package-topology.md`、
> 后续 S4 `design-dispatcher-ros-adapter-split.md`（其余 ROS 面，另行负责）。

## 0. 元信息

| 项 | 值 |
|----|----|
| 日期 | 2026-09-12 |
| 目标路径 | `l3-dispatcher-planner/ros_packages/dispatcher/`：`dispatcher/engine.py`、新增 `dispatcher/core/`、新增 `dispatcher/ros_adapter/`、`dispatcher_node.py` |
| 状态 | done（2026-09-12 执行完毕；deep-oracle 放行，见 §11 附录） |
| 关联文档 | 总纲 `design-dispatcher-architecture-stabilization.md`（§4.1/§4.2/§4.3/§4.4/§4.5/§4.7/§5/§6/§7）；模板 `_TEMPLATE.md`；前置 S2 `design-dispatcher-package-topology.md`；后续 S4 `design-dispatcher-ros-adapter-split.md`；历史记录 `design-dispatcher-core-inference-migration.md`（done）、`-engine-narrow-core-trim.md`（done）、`-zenoh-transport-migration.md`（done），三者**不改写** |
| 契约依据 | 见摘要；门禁编号沿用契约 G1–G23，新增门禁沿用总纲 A1–A5 |
| 路径约定 | 全文一律**相对路径**；不写主机绝对路径与个人标识。`PKG = l3-dispatcher-planner/ros_packages/dispatcher/dispatcher`；`NODE = l3-dispatcher-planner/ros_packages/dispatcher/dispatcher_node.py`；`TESTS = l3-dispatcher-planner/tests/tool-registry` |

## 1. 背景与动机

- 总纲 §4.7 把本轮钉为 S3：**engine 非 core 职责迁出 + core 四通道适配落位**；前置 S2 完成后，
  包根只剩 `engine.py` + `__init__.py`，`utils/`、`tools/`、`perception/` 三层落位，
  `skill_api.py` 已在 `tools/skill_api.py`、`control_plane.py` 已在 `utils/control_plane.py`。
- 本文旧版（`proposed`，未执行）以 **1055 行版** engine 为证据基线；现值 **1067 行**（zenoh 轮注入
  工具执行缝后 +12 行）。旧映射行号已过期，须按实测重锚（本方案 §2/§5）。
- 总纲 §4.5 裁定 B3 ↔ R1/R4 冲突：**B3 是「对外通道数量的语义白名单」，不豁免 R1/R2/R4**——
  四类 core 通道的 ROS 实现必须落适配文件，**core 只持端口引用**。本方案据此设计：四类通道的
  `rospy.Publisher` / 消息类型 / 主题参数**一次落** `ros_adapter/core_channels_ros.py`，不进入 `core/`。
- 硬要求（本轮验收红线）：
  1. 迁移后 `engine.py` 与 `dispatcher/core/*.py` **零 `rospy`**（G7）、零 ROS 消息类型（G8 逐文件）；
  2. 四类通道的 topic 名与 payload **逐字不变**；
  3. **禁止二次搬迁**：四类通道适配在 S3 一次落位，S4 不再搬迁它们。

## 2. 现状事实（问题清单）

> 行号为**本次写作时实测**（`wc -l` 与逐行 `Read`/`Grep`），非沿用 1055 行基线。
> 每条 = 相对路径 + 实测行号 + 现象。§2 的行号在 S2 执行前的当前工作区测得；
> S2 只改写 `engine.py` 的 import 路径（如 `dispatcher.skill_api` → `dispatcher.tools.skill_api`），
> 若因此使 `engine.py` 行号平移，S3 执行时以**符号名重锚**（此平移与否**未核实**）。

### 2.1 启动装配（composition）——不在类内，属 composition root

- [ ] `PKG/engine.py#L1020-L1060` — 模块级 `create_dispatcher_engine(config_path)`：`load_yaml` /
  `merge_config_sections` / `merge_pointcloud_mode_params` / `set_ros_params` / `apply_config` 装配。
- [ ] `PKG/engine.py#L1063-L1067` — 模块级 `start_dispatcher_workers(node)`：起推理线程。
- [ ] `PKG/engine.py#L16` — `import threading` **仅**被 `#L1065` 使用。
- [ ] `PKG/engine.py#L27-L38` — `dispatcher.config` 符号（`CONFIG_KEY_ALIASES`、`UAV_POLICY_DEFAULTS`、
  `load_yaml`、`set_ros_params`、`set_defaults`、`apply_config`、`merge_config_sections`、
  `get_nested_config`、`flatten_leaf_params`、`merge_pointcloud_mode_params`）**仅**被上面两个模块级
  函数使用（`set_defaults`/`UAV_POLICY_DEFAULTS` 同时被 `#L86` 使用，迁出后此两符号仍需保留）。
- [ ] `NODE#L19-L22` / `#L33` / `#L38` — composition root 导入并调用这两个函数，本应自持装配。

### 2.2 engine 的 ROS 面（G7/G8 硬冲突，实测 47 处命中）

- [ ] `PKG/engine.py#L23` — `import rospy`。
- [ ] `PKG/engine.py#L24` — `from std_msgs.msg import String, Empty, Bool`（G8 逐文件冲突）。
- [ ] 参数读取（`rospy.get_param`）：`#L136`/`#L137`（`~telemetry/level`、`~telemetry/stdout_en`）、
  `#L151`（`~log_dir`）、`#L165`/`#L200`（`~headless`）、`#L205`（`~emergency_stop_topic`）、
  `#L221`（`~task_phase_topic`）；`#L135`（`rospy.get_name()`）。
- [ ] 日志面（`rospy.log*`）：`#L174`、`#L240`、`#L364`、`#L384`、`#L414`、`#L462`、`#L545`、
  `#L567`、`#L579`、`#L607`、`#L610`、`#L658`、`#L809`、`#L829`、`#L1013`；节流
  `rospy.logwarn_throttle`：`#L817`、`#L858`。
- [ ] 时钟 / 关停：`#L806`（`rospy.Rate(20)`）、`#L816`/`#L831`/`#L1007`（`rospy.is_shutdown()`）、
  `#L972`（`rospy.signal_shutdown(...)`）。

### 2.3 四类 core 通道（B3 白名单，待端口化）

- [ ] `PKG/engine.py#L204-L210` — 急停：`~emergency_stop_topic`（默认 `/command/emergency_stop`，
  `.strip() or "/command/emergency_stop"`）+ `rospy.Publisher(topic, Empty, queue_size=10)`；
  发布点 `#L624`、`#L853`（`publish(Empty())`）。
- [ ] `PKG/engine.py#L212-L214` — `if_handle_yaw`：`rospy.Publisher("if_handle_yaw", Bool, queue_size=10)`；
  发布点 `#L541-L543`（`Bool()` + `.data=enabled`）。
- [ ] `PKG/engine.py#L217-L219` — 命令内容监控：`rospy.Publisher("monitor/command_content", String, queue_size=10)`；
  发布点 `#L260-L265`（payload = `json.dumps([entry[0] for entry in command_content], ensure_ascii=False)`）。
- [ ] `PKG/engine.py#L220-L224` — 任务相位：`rospy.Publisher(rospy.get_param("~task_phase_topic",
  "/agent_task_phase"), String, queue_size=10)`；发布点 `#L355`
  （payload 见 §4.6，键序 `frame_id, phase, progress, detail[, message][, result][, error][, status]`）。
- [ ] `PKG/engine.py#L225` — `_task_phase_progress`（唯一读点 `#L400`，无自增点，实测）。

### 2.4 遥测 / 监控 / 诊断（observability，待迁）

- [ ] `PKG/engine.py#L134-L138` — `StructuredLogger` 构造（`rospy.get_name` + 2 参数）。
- [ ] `PKG/engine.py#L147` — `_active_task_frame_id`；`#L148` — `_task_result_stash`。
- [ ] `PKG/engine.py#L151-L155` — `log_root`/`log_dir`/`session_tag`。
- [ ] `PKG/engine.py#L158-L161` — `attach_trace(...)`（JSONL 决策轨迹落盘）。
- [ ] `PKG/engine.py#L162-L167` — `dispatcher_started` 首发事件（含 `headless`、`log_dir` 字段）。
- [ ] `PKG/engine.py#L170-L174` — `thinking_debug_dir` / `last_thinking_debug_dir`。
- [ ] `PKG/engine.py#L256-L258` — `_telemetry()` 薄封装；`#L260-L265` — `publish_command_content()`。
- [ ] `PKG/engine.py#L296-L299` — `_fmt_wait_age()`；`#L301-L313` — `_decision_chain_wait_diag()`
  （调用点 `#L820`、`#L861`；内部调用 `self.get_sensor_input_health()`，实现在
  `PKG/perception/base_policy.py#L1158`）。

### 2.5 任务相位桥（external protocol publishing，待迁）

- [ ] `PKG/engine.py#L315-L364` — `_publish_task_phase()`：payload 组装（`#L338-L351`）+
  `zenoh_middleware.on_tool_phase(payload)` 出口（`#L352-L354`）+ topic 发布（`#L355`）+
  `task_phase_published` 事件（`#L356-L362`）+ 异常兜底 `#L363-L364`。
  调用点：`#L398`、`#L466`、`#L496`、`#L503`。

### 2.6 技能注册表与分发（strategy dispatch，待迁）

- [ ] `PKG/engine.py#L191-L192` — `_current_plan_skill` / `_action_owner_skill`（动作归属快照）。
- [ ] `PKG/engine.py#L193-L197` — `_skills: dict = {}`（P3 技能注册表，当前恒空）。
- [ ] `PKG/engine.py#L410-L419` — `_validate_active_tool()`（未注册即 `logwarn` + `_advance_to_next_prompt`）。
- [ ] `PKG/engine.py#L547-L573` — `_handle_plan_tool()`（注册表 `plan_tick` 分发 + 未命中回退 `#L567-L573`）。
- [ ] `PKG/engine.py#L632-L636` — `pop_task_result()`（`SkillHost` 端口）。
- [ ] FSM 内散落查表：`#L646-L648`（`_action_done`）、`#L728-L730`（`_handle_post_action`）、
  `#L941-L943`（WAIT_ACTION_FINISH wait tick）。

### 2.7 工具执行缝（zenoh 轮注入，待迁）

- [ ] `PKG/engine.py#L177-L187` — 6 字段：`_active_tool_name`、`zenoh_middleware`、`_active_tool_call`、
  `latest_agent_prompt_frame_id`、`current_task_id`、`task_action_client`。
- [ ] `PKG/engine.py#L421-L430` — `bind_tool_middleware()`（外部 `ToolControlPlane.__init__` 调用）。
- [ ] `PKG/engine.py#L432-L446` — `_activate_tool_call()`。
- [ ] `PKG/engine.py#L448-L513` — `start_tool_workflow()`。
- [ ] `PKG/engine.py#L515-L534` — `cancel_tool_call()`。

### 2.8 动作执行细节（待迁）

- [ ] `PKG/engine.py#L536-L545` — `_set_if_handle_yaw()`（调用点 `#L553`）。
- [ ] `PKG/engine.py#L46-L72` — `PendingAction` dataclass（动作上下文载体）。

### 2.9 已知断裂 / 孤儿引用（登记，不臆造实现）

- [ ] `PKG/engine.py#L494` — `start_tool_workflow` 内调用 `self._decision_chain_not_ready_reason()`；
  全仓 grep 仅此一处调用、**零定义**（上轮 `narrow-core-trim` 已删除的定义）。
- [ ] `PKG/engine.py#L461` — `if not hasattr(self, "_start_prompt_task"):` 守卫；engine **无**
  `_start_prompt_task`，故 `#L462-L475` 早退，**`#L476-L513` 整段不可达**——其中
  `#L494`（孤儿调用）与 `#L508`（`self._start_prompt_task(...)`，另一处未定义调用）均不可达。
- [ ] 结论：这是既有断裂、非本轮引入；迁出 `start_tool_workflow` 时**逐字保留**守卫与不可达段，
  并登记待「任务注入轮次」迁入 `_start_prompt_task` 时一并处置（不得补造 `_decision_chain_not_ready_reason`）。

### 2.10 缺失的 host 缝（实测，与 §4.6/§4.7 接线相关）

- [ ] `PKG/tools/executor.py#L26-L34` — 直发缝 `forward_takeoff_tool` / `forward_land_tool` /
  `forward_emergency_stop_tool`；`#L39-L42` — `start_tool_workflow`；`#L44-L46` — `cancel_tool_call`。
- [ ] `PKG/tools/control_plane.py#L23` — `host.bind_tool_middleware(self.middleware)`；`#L56` — `host.cancel_tool_call`。
- [ ] `PKG/engine.py` **实测不含** `forward_takeoff_tool`/`forward_land_tool`/`forward_emergency_stop_tool`
  与 `stash_task_result`/`publish_phase`/`fail_sequence`/`capture_task_generation`/`task_generation_valid`/
  `consume_head_prompt`/`advance_prompt`/`arm_action`/`send_task_goal`/`publish_mode_burst`/
  `latest_frame`/`get_fast_rgb`/`_notify_skills`（全仓 grep 仅 `PKG/skill_api.py` 契约工件命中）。
  → 本轮**不补齐**这些端口/缝（总纲 §4.6：端口与技能族同轮落地；直发缝属任务注入轮次），
  只把**已存在**的三缝（`bind_tool_middleware`/`start_tool_workflow`/`cancel_tool_call`）迁入 `core/workflow.py`。

### 2.11 测试中的 duck-typed host 证据

- [ ] `TESTS/test_tool_registry.py#L187-L204` — `FakeHost` 仅实现 `start_tool_workflow`
  （+ 三条直发缝 raise），`#L205` `ToolExecutor(registry, host)`。
- [ ] `TESTS/test_tool_registry.py#L257-L276` — `FakeHost` 实现 `forward_takeoff_tool`/`forward_land_tool`/
  `forward_emergency_stop_tool`/`start_tool_workflow`。
- [ ] 结论：host 契约是 **duck-typed 三缝 + 三条直发缝**；迁移后由 `core/workflow.py` 的
  `ToolWorkflowHost` 充当 host 传给 `ToolControlPlane`/`ToolExecutor`，`FakeHost` 无需改动。

### 2.12 契约硬冲突锚点

- [ ] `specs/implemented/inner/l3-core-boundary.spec.md#L31-L32` — B3 允许 core 持有四类发布器；
  `specs/implemented/inner/l3-ros-adapter-boundary.spec.md#L27-L28`（R1 收发集中）、`#L38-L40`（R4 出站经端口）、
  `#L78-L79`（G7/G8）——两条叶契约表面冲突，**总纲 §4.5 已裁定**：B3 为语义白名单，四类通道的 ROS 实现落
  `ros_adapter/core_channels_ros.py`，core 只持端口引用（S1 会上契约措辞，本轮按其结论设计）。
- [ ] `specs/implemented/inner/l3-core-boundary.spec.md#L60` — G2 第二子句「core 的 `def` 数不超过约定阈值」
  数未定（S1 改写为可判定方法集）；本方案 §4.2 给出候选集合，**最终白名单以 S1 定稿为准（未核实）**。

### 2.13 包树现状（实测）

- [ ] `PKG/` 包根现有：`engine.py`、`skill_api.py`、`state.py`、`config.py`、`slog.py`、
  `connection_lease.py`、`zenoh_rpc.py`、`rpc_plane.py`、`__init__.py`，以及 `tools/`、`perception/`。
- [ ] `PKG/utils/` 目录**已存在但为空**（非 S2 产物）；`PKG/core/`、`PKG/ros_adapter/` 尚不存在（S3 新建）。

## 3. 目标与约束

- **目标**：
  1. `engine.py` 回到窄核心：**FSM 主循环 + 全局状态 + 任务编排 + 动作裁定**；
  2. 外围职责迁入 `dispatcher/core/` 协作模块，engine 以**组合**方式调用；
  3. 四类 core 通道的 ROS 实现**一次落** `dispatcher/ros_adapter/core_channels_ros.py`，engine 只持端口引用；
  4. 装配函数入 `dispatcher_node.py`（composition root）；
  5. 迁移**零语义变更**：slog 事件名/键集、topic 名与 payload、状态迁移 reason、等待诊断串格式、
     启动序列**字节级不变**。
- **Non-Goals**（明确不做）：
  - 不改 FSM 语义（状态集合、转移、四裁决落地）；
  - 不实现技能族（`tools/vla|scene_nav|flight|grasp`）、不迁任务注入轮次（`_start_prompt_task`/`arm_action`）；
  - 不补齐 `SkillHost` 的 11 端口与三条直发缝（§2.10；总纲 §4.6 同轮落地原则）；
  - 不改对外协议（slog 事件名/键、zenoh topic/queryable、ROS topic/param/消息字段名、`SkillHost` 端口签名）；
  - 不动 `PendingAction`（留 engine，§4.9 的 D3）。
- **明确划归 S4**（本方案只做**登记**与**接口衔接说明**，由 `design-dispatcher-ros-adapter-split.md` 负责）：
  - `config.py` 的 ROS 私有参数面：`PKG/config.py#L15`（`import rospy`）及其 `set_ros_params` 等 → `ros_adapter/params_ros.py`；
  - 装配 / 传输面的 rospy 关停与日志：`PKG/tools/control_plane.py#L45`、`#L75`（局部 `import rospy`），
    `PKG/zenoh_rpc.py#L307-L320`、`#L428` → `ros_adapter/clock_ros.py`；
  - 感知层收发：`PKG/perception/base_policy.py#L18`、`#L24-L30`、`#L451`、`#L513`、`#L517`、`#L543`、
    `#L548`、`#L552`、`#L557`、`#L564`、`#L585`、`#L598`、`#L612` 与
    `PKG/perception/pointcloud_accumulator.py#L12-L14`、`#L122`、`#L125` → `ros_adapter/perception_ros.py`（评估后执行）。
  - **衔接说明**：engine 仍继承 `PKG/perception/base_policy.py` 的 `BasePolicyNode`（无行为改动）；
    其 `get_frame_snapshot`（`#L767`）、`get_sensor_input_health`（`#L1158`）等由 S4 处理其 rospy，
    本方案对其调用点（`#L816`、`#L823`、`#L838`、`#L850`、`#L861`）**保持不变**。
    `dispatcher_node.py`（composition root）在 S3 仍可含 `rospy`（`init_node`/`spin`/`get_param`）；
    其 `rospy` 收敛由 S4 的 `clock_ros.py`/`params_ros.py` 承接（A2 对 composition root 的判定留待 S4）。
- **硬边界**（AGENTS.md + 总纲 §3）：
  - **禁止转接器**：不为桥接新旧位置新造 adapter；engine 直接持有并使用新协作对象/端口。
  - **过期必删**：逻辑迁出后 engine 内**不留同名薄封装桩、不注释保留**（§6）。
  - **禁止二次搬迁**：四类通道适配 S3 一次落位，S4 不再搬迁。
  - **零 rospy**：迁移后 `engine.py` 与 `core/*.py` 零 `rospy`、零 ROS 消息类型。
  - **契约优先**：§2.12 的 B3↔R1 结论以总纲 §4.5 为准；G2 白名单以 S1 定稿为准。
  - 先方案后改码；不 commit（等显式指令）。

## 4. 方案决策

### 4.1 目标目录树（服从总纲 §4.1；★ = S3 新建）

```
l3-dispatcher-planner/ros_packages/dispatcher/
  dispatcher_node.py                 # composition root：吸收 create_dispatcher_engine /
                                     #   start_dispatcher_workers；构造并注入端口
  dispatcher/
    __init__.py
    engine.py                        # core 门面：FSM 主循环 + 全局状态 + 任务编排 + 动作裁定（零 ROS）
    core/                      ★ S3  # core 私有协作模块（领域逻辑，零 ROS）
      __init__.py              ★ S3
      telemetry.py             ★ S3  # RunTelemetry：slog / trace / 监控 / 等待诊断 / 日志
      task_phase.py            ★ S3  # TaskPhaseBridge：相位事件组装与上报（含 on_tool_phase 出口）
      skill_router.py          ★ S3  # SkillRouter：技能注册表 / 分发 / 归属快照 / 结果暂存
      actuators.py             ★ S3  # PlannerActuators：planner 动作面指令（yaw 模式）
      workflow.py              ★ S3  # ToolWorkflowHost：工具执行缝（3 缝 + 6 字段）
      ports.py                 ★ S3  # 端口 Protocol（ROS 收发面与运行面的抽象）
    ros_adapter/               ★ S3  # 唯一允许 rospy / ROS 消息类型的位置（R1）
      __init__.py              ★ S3
      core_channels_ros.py     ★ S3  # 四类 core 通道的 ROS 实现 + 最小运行端口实现
    utils/                           # S2 支撑平面（state/config/slog/.../control_plane）
    tools/                           # S2 执行平面（protocol/model/registry/runtime/executor/skill_api）
    perception/                      # 感知层（位置不变；其 rospy 归 S4）
```

- **不得改树**：`core/` 与 `ros_adapter/` 的落点、文件命名由总纲 §4.1 唯一规定；本方案不自行增删模块。
- S3 **不创建** `ros_adapter/{params_ros,clock_ros,perception_ros}.py`（S4 职责，见 §3）。

### 4.2 保留边界清单（engine 迁移后的方法集合，G2 白名单候选）

> engine 迁移后只保留下列 `def`（加 `PendingAction.clear`）。**与 G2 白名单对齐**：待 S1 把
> `l3-core-boundary` G2 第二子句从「约定阈值」改写为该可判定方法集后判绿（**S1 未定稿，未核实**）。

| 保留项 | 实测现状行号 | 定位 |
|---|---|---|
| `__init__` | `#L81-L225` | 全局状态字段（扣除迁出块：遥测/相位/技能/缝/动作面） |
| `sync_task_buffers_from_prepare` | `#L229-L251` | 任务缓存同步 |
| `_set_dispatcher_state` | `#L267-L294` | 全局状态迁移 + 留痕（O2） |
| `_handle_get_pre_command` | `#L366-L388` | 任务编排 |
| `_load_next_prompt` | `#L390-L408` | 任务编排 |
| `_bump_task_generation` | `#L576-L584` | 全局状态控制 |
| `_enter_global_stop` | `#L586-L630` | 全局停止（急停经端口发布） |
| `_action_done` | `#L638-L683` | 动作完成判定（机械执行） |
| `_advance_to_next_prompt` | `#L685-L703` | 动作裁定 |
| `_reset_plan_cycle_if_needed` | `#L705-L712` | 动作裁定 |
| `_handle_post_action` | `#L714-L754` | 四裁决机械执行 |
| `_run_inference_loop` | `#L759-L979` | FSM 主循环 |
| `_recover_inference_after_exception` | `#L981-L998` | 异常自愈 |
| `run_inference` | `#L1000-L1017` | 推理线程守护 |
| `PendingAction` + `clear` | `#L46-L72` | 动作上下文载体（D3 暂留 engine） |

- `DISPATCHER_STATE` 成员数 = 6（`PKG/state.py#L25-L31`），G2 第一子句不动。
- `_handle_post_action` / `_action_done` / WAIT_ACTION_FINISH 内的技能 gate/verdict/owner 查表是
  **FSM 的机械执行**，保留在 engine；仅把「查表」委托给 `self.skills`（§2.6）。
- engine 迁出 `threading`、`rospy`、`std_msgs`、`config`（装配符号）后，保留仍被类内使用的
  `set_defaults`/`UAV_POLICY_DEFAULTS`（`#L86` 需要）等符号。

### 4.3 迁出清单（engine.py → core/ 与 ros_adapter/）

| 迁出块 | 实测行号 | 目标 |
|---|---|---|
| 启动装配（`create_dispatcher_engine` / `start_dispatcher_workers`）+ `threading`/`config` import | `#L1020-L1060`、`#L1063-L1067`、`#L16`、`#L27-L38` | `NODE` |
| 遥测初始化 / `_telemetry` / `publish_command_content` / `_fmt_wait_age` / `_decision_chain_wait_diag` / `thinking_debug` | `#L134-L138`、`#L151-L155`、`#L158-L174`、`#L256-L265`、`#L296-L313` | `core/telemetry.py` |
| 任务相位桥（`_publish_task_phase` + 3 字段） | `#L147`、`#L220-L225`、`#L315-L364` | `core/task_phase.py` |
| 技能注册表 / 归属快照 / 结果暂存 / 分发 | `#L148`、`#L191-L197`、`#L410-L419`、`#L547-L573`、`#L632-L636` | `core/skill_router.py` |
| 工具执行缝（3 缝 + 6 字段） | `#L177-L187`、`#L421-L430`、`#L432-L446`、`#L448-L513`、`#L515-L534` | `core/workflow.py` |
| 动作面（`_set_if_handle_yaw`） | `#L536-L545` | `core/actuators.py` |
| 四类通道的 ROS 实现 | `#L204-L210`、`#L212-L214`、`#L217-L219`、`#L220-L224` | `ros_adapter/core_channels_ros.py` |
| 运行面（Rate/关停/日志） | `#L806`、`#L816`、`#L831`、`#L1007`、`#L972` 及全部 `rospy.log*` | `ros_adapter/core_channels_ros.py`（运行端口） |

### 4.4 命名规范表（服从总纲 §4.3；仅列本轮涉及）

| 类型 | 规范 | 本轮示例 |
|---|---|---|
| 平面目录 | 小写单词，层级即平面 | `core/`、`ros_adapter/` |
| 适配文件 | `*_ros.py`；仅此命名可含 `rospy` 与 ROS 消息类型 | `core_channels_ros.py` |
| core 协作模块 | 小写下划线，按职责角色 | `telemetry.py`、`task_phase.py`、`skill_router.py`、`actuators.py`、`workflow.py`、`ports.py` |
| 类 | 大驼峰，职责名词 | `RunTelemetry`、`TaskPhaseBridge`、`SkillRouter`、`PlannerActuators`、`ToolWorkflowHost`、`RosCoreChannels` |
| 函数 / 方法 | snake_case；**位置迁移一律沿用原名**（迁移非重构） | `publish_command_content`、`pop_task_result` |
| engine 属性 | 协作对象用职责名 | `self.runlog`、`self.task_phase`、`self.skills`、`self.tools`、`self.actuators`、`self.clock`、`self.channels` |

### 4.5 端口形态：`core/ports.py`（Protocol 集合与签名草案）

> 只声明**端口**，不含实现、不含 `rospy`、不含 ROS 消息类型（R2）。端口命名与 `SkillHost`
> （`PKG/tools/skill_api.py`，S2 后路径）的端口**不重名、不增删**（§2.10）。

```python
# PKG/core/ports.py（草案）
from __future__ import annotations
from typing import Protocol

class CoreChannels(Protocol):
    """四类 core 通道（B3 语义白名单）的 ROS 出站端口。"""
    def publish_emergency_stop(self) -> None: ...                 # Empty → ~emergency_stop_topic
    def publish_if_handle_yaw(self, enabled: bool) -> None: ...    # Bool  → if_handle_yaw
    def publish_command_content(self, payload: str) -> None: ...   # String→ monitor/command_content
    def publish_task_phase(self, payload: str) -> None: ...        # String→ ~task_phase_topic

class Ticker(Protocol):
    def sleep(self) -> None: ...

class RuntimeClock(Protocol):
    """节律与关停判定（O1 / STOP 所需的最小运行端口）。"""
    def rate(self, hz: float) -> Ticker: ...
    def is_shutdown(self) -> bool: ...
    def request_shutdown(self, reason: str) -> None: ...

class LogSink(Protocol):
    """日志端口：为让 engine/core 零 rospy 而必需（否则 rospy.log* 仍命中 rospy\\.）。"""
    def info(self, msg: str, *args: object) -> None: ...
    def warn(self, msg: str, *args: object) -> None: ...
    def err(self, msg: str, *args: object) -> None: ...
    def warn_throttle(self, period: float, msg: str, *args: object) -> None: ...
```

- **端口集合的边界**：四类通道（`CoreChannels`）是 B3 白名单的端口化；`RuntimeClock`（`rospy.Rate`
  节律 + `is_shutdown`/`signal_shutdown` 关停判定）与 `LogSink` 是**使 `engine.py`/`core/` 零 `rospy`
  所必需的最小非领域端口**。除此之外**不新增端口**（不投机设计）。
- **`zenoh_middleware.on_tool_phase(payload)` 出口**：**不是 ROS 通道**，不进 `CoreChannels`。它是
  zenoh 传输协作对象（非 rospy），由 `TaskPhaseBridge` 持有引用（经 `bind_tool_middleware` 设置），
  在 payload 组装后**先**调用 `on_tool_phase(payload)`、**再**经 `CoreChannels.publish_task_phase`
  发到 topic（与现状 `#L352-L355` 的先后一致）。
- **主题参数归属**：`~emergency_stop_topic`、`~task_phase_topic` 由 `ros_adapter/core_channels_ros.py`
  自读（属该通道的 ROS 配置面）；`~telemetry/level`、`~telemetry/stdout_en`、`~log_dir`、`~headless`
  与节点名由 composition root 解析为**普通值**注入（见 §4.7）。

### 4.6 `ros_adapter/core_channels_ros.py` 实现面（topic 名与 payload 逐字不变）

> 该类是四类通道的**唯一合法落点**（总纲 §4.5）。以下常量/表达式与 `engine.py` 现状**逐字一致**。

| 通道 | 主题（逐字） | 消息类型 | 队列 | 发布表达式（逐字等价） |
|---|---|---|---|---|
| 急停 | `~emergency_stop_topic`，默认 `/command/emergency_stop`；`.strip() or "/command/emergency_stop"` | `std_msgs/Empty` | `queue_size=10` | `pub.publish(Empty())` |
| `if_handle_yaw` | `if_handle_yaw`（相对名，随节点 ns 解析） | `std_msgs/Bool` | `queue_size=10` | `msg = Bool(); msg.data = enabled; pub.publish(msg)` |
| 命令内容监控 | `monitor/command_content` | `std_msgs/String` | `queue_size=10` | `pub.publish(String(data=payload))` |
| 任务相位 | `~task_phase_topic`，默认 `/agent_task_phase` | `std_msgs/String` | `queue_size=10` | `pub.publish(String(data=payload))` |

- **payload（逐字）**：
  - 命令内容：`payload = json.dumps([entry[0] for entry in command_content], ensure_ascii=False)`
    （`command_content` 为 `(prompt, SkillCommand)` 元组队列，取 `entry[0]`；组装留在 `core/telemetry.py`）。
  - 任务相位：dict **键序** `frame_id, phase, progress, detail`，其后**按存在性**追加
    `message, result, error, status`；`payload = json.dumps(payload_dict, ensure_ascii=False)`
    （组装留在 `core/task_phase.py`，`effective_frame` 缺省取 `_active_task_frame_id`/`"Null"`）。
- 该类同时承载**最小运行端口实现**（`RosRuntimeClock`：`rospy.Rate`/`is_shutdown`/`signal_shutdown`；
  `RosLogSink`：`rospy.loginfo`/`logwarn`/`logerr`/`logwarn_throttle`）——因为 S3 必须自包含地
  使 engine/core 零 rospy，且**禁止二次搬迁**。S4 的 `clock_ros.py` 只服务**装配/传输面**
  （`control_plane.py`/`zenoh_rpc.py`）的 rospy，**不得**再迁本文件的运行端口（见 §9 风险）。
- 包标记：`ros_adapter/__init__.py`、`core/__init__.py` 新建为空包标记。

### 4.7 端口注入方式裁决（唯一裁决：composition root 注入）

- **裁决**：由 **composition root（`dispatcher_node.py`）** 构造端口实现并注入 `DispatcherEngine`。
  engine 只依赖 `core/ports.py` 的 Protocol。
  ```python
  # NODE（示意，非最终代码）
  channels = RosCoreChannels()          # ros_adapter/core_channels_ros.py（四类通道）
  clock    = RosRuntimeClock()          # 同一适配文件的最小运行端口
  log      = RosLogSink()
  engine = DispatcherEngine(config=<plain values>, channels=channels, clock=clock, log=log)
  ```
- **理由**：
  1. **依赖倒置（总纲 §4.2）**：`core/` 只声明端口、`ros_adapter/` 实现端口；`core/` 与其消费者
     **不 import `ros_adapter/`**。engine 自建适配器会引入 `dispatcher.ros_adapter` 包内边，违反 A1；
  2. **G7 零 rospy**：适配器构造本身是 ROS API 使用，只能出现在 `ros_adapter/`；
  3. **可测性**：core 可用 fake 端口脱离 ROS 单测；
  4. **单一组合点**：与 `dispatcher_node.py` 的 composition root 定位一致（`NODE#L35` 已持有 host 组合职责）。
- **否决项**：**engine 自建适配器**（engine 直接 `import` 适配文件/构造 Publisher）——违反 §4.2 依赖方向与 A1。
- **params 解析**：composition root 解析 `~telemetry/level`、`~telemetry/stdout_en`、`~log_dir`、
  `~headless` 与 `rospy.get_name()`，以**普通值**（str/bool/Path）注入；一般 ROS 参数装载器
  （`params_ros.py`）归 S4。

### 4.8 装配函数与启动序列（P0）

- `create_dispatcher_engine` / `start_dispatcher_workers` 移入 `NODE`；`NODE#L19-L22` 的 import 删除。
- `create_dispatcher_engine` 内部流程**逐行等价**：`load_yaml` → 组装 `ros_params` → `set_ros_params`
  →（新增）解析私有参数 + 构造端口 → `DispatcherEngine(...)` → `apply_config(...)` ×2 →
  `sync_task_buffers_from_prepare()` → 返回。
- `main()` 启动序列**逐行等价**：`init_node` → `create_dispatcher_engine` →
  `ToolControlPlane(engine)` → `control_plane.start()` → `start_dispatcher_workers` → `spin` →
  `join` → `close`；host 由 `engine` 换成 `engine.tools`（`ToolWorkflowHost`，duck-typed 三缝不变）。

### 4.9 已知断裂 / 孤儿处置裁决（§2.9）

- `start_tool_workflow` 迁入 `core/workflow.py` 时，**逐字保留** `#L461` 的 `hasattr` 守卫、
  `#L462-L475` 早退、`#L476-L513` 不可达段（含 `#L494` 孤儿调用与 `#L508` 未定义调用）——
  行为不变（现状不可达）。
- **不补造** `_decision_chain_not_ready_reason`；在 §9/§10 登记为「既有断裂，待任务注入轮次
  （迁入 `_start_prompt_task`）一并处置」，符合总纲 §2.B「须登记处置而不臆造实现」。
- **D3**：`PendingAction` 暂留 engine（当前仅 engine 读），随 `arm_action` 轮次再迁动作面；避免投机设计。

### 4.10 与 S6 的接口衔接（消解接口悬空，供 S6 引用）

> S6（分发失败语义）需要"未命中一律 fail"的落点；S3 之后"未命中"判定发生在 `core/skill_router.py`，而 FSM 状态控制仍在 `engine`。为免两方案各自假设，接口冻结如下：

| 接口 | 归属 | 语义 | 返回 |
|---|---|---|---|
| `SkillRouter.dispatch_plan(cmd, skill_command)` | `core/skill_router.py` | 注册表查表并推技能 `plan_tick` | `True`=已处理（engine `continue`）；**`False`=未命中，不自行推进、不发任何相位** |
| `SkillRouter.validate_active_tool(call, active_name)` | `core/skill_router.py` | 校验 DISPATCH 是否来自已注册运行时 | `True`=通过；**`False`=未命中**（不推进） |
| `_fail_unregistered_dispatch(*, tool_name, frame_id)` | `engine.py` | 未命中的唯一失败处理：上报 `fail` 相位（载荷含工具名，满足 O3）→ 置 `_task_sequence_failed=True`、`if_plan=False` → 停 `WAIT_FOR_MISSION`；**不得排空队列后报 done** | — |

- engine 侧调用形态：`if not self.skills.dispatch_plan(cmd, skill_command): self._fail_unregistered_dispatch(tool_name=..., frame_id=...); continue`
- 与 S1 白名单的关系：`_fail_unregistered_dispatch` 已列入 S1 §4.2 的 G2 白名单（其插入片段为 `l3-core-boundary` 新增 §4.1）；`SkillRouter` 的方法集合（含 `dispatch_plan` / `validate_active_tool`）是该白名单的取值来源，须在 S1 定稿时同批对齐。
- 不变量：本接口只改"未命中"的对外结果（done → fail，属 S1 已登记的有意变更）；正常 `ADVANCE` 与队尽 `done` 路径不受影响。

## 5. 迁移映射表（旧行号 → 新位置 → 动作）

> 旧行号 = `PKG/engine.py`（1067 行版，本次实测）。动作：move / move+rename / retain / delete。

| 旧位置（实测行号） | 新位置 / 命名 | 动作 | 备注 |
|---|---|---|---|
| `#L1020-L1060` `create_dispatcher_engine` | `NODE` 同名函数 | move | 增端口构造/注入 |
| `#L1063-L1067` `start_dispatcher_workers` | `NODE` 同名函数 | move | |
| `#L16` `import threading` | `NODE` | move | engine 去依赖 |
| `#L27-L38` `dispatcher.config` 符号 | `NODE`（`set_defaults`/`UAV_POLICY_DEFAULTS` 留 engine） | move | 按符号拆分 |
| `#L134-L138` `StructuredLogger` 构造 | `core/telemetry.py` `RunTelemetry.__init__` | move | 参数由注入值提供 |
| `#L151-L155` log_root/log_dir/session_tag | `core/telemetry.py` | move | `~log_dir` 值注入 |
| `#L158-L161` attach_trace | `core/telemetry.py` | move | |
| `#L162-L167` `dispatcher_started` | `core/telemetry.py` | move | 键含 `headless`/`log_dir` 不变 |
| `#L170-L174` thinking_debug | `core/telemetry.py` | move | |
| `#L256-L258` `_telemetry` | `core/telemetry.py` `RunTelemetry.emit` | move+rename | 调用点改 `self.runlog.emit` |
| `#L260-L265` `publish_command_content` | `core/telemetry.py` `publish_command_content`（经 `channels`） | move | payload 组装留 telemetry |
| `#L296-L299` `_fmt_wait_age` | `core/telemetry.py` `fmt_wait_age` | move | 静态方法 |
| `#L301-L313` `_decision_chain_wait_diag` | `core/telemetry.py` `wait_diag(health)` | move | health 由外部传入 |
| 全部 `rospy.log*`（§2.2） | `core/telemetry.py`（经 `LogSink`） | move | `self.runlog.info/warn/err/warn_throttle` |
| `#L147` `_active_task_frame_id` | `core/task_phase.py` | move | |
| `#L220-L224` `task_phase_pub` | `ros_adapter/core_channels_ros.py` | move | 端口化 |
| `#L225` `_task_phase_progress` | `core/task_phase.py` | move | 死字段如实保留 |
| `#L315-L364` `_publish_task_phase` | `core/task_phase.py` `publish` | move+rename | 调用点改 `self.task_phase.publish(...)` |
| `#L148` `_task_result_stash` | `core/skill_router.py` | move | |
| `#L191-L192` owner 快照 | `core/skill_router.py` | move | |
| `#L193-L197` `_skills` | `core/skill_router.py` | move | |
| `#L410-L419` `_validate_active_tool` | `core/skill_router.py` `validate_active_tool` | move | 无效回退回调留 engine |
| `#L547-L573` `_handle_plan_tool` | `core/skill_router.py` `dispatch_plan` | move+rename | yaw 设置经 `self.actuators` |
| `#L632-L636` `pop_task_result` | `core/skill_router.py` | move | `SkillHost` 端口 |
| `#L646-L648` / `#L728-L730` / `#L941-L943` owner 查表 | `core/skill_router.py` `owner_skill` | move | FSM 仅调用查询 |
| `#L177-L187` 6 工具缝字段 | `core/workflow.py` | move | |
| `#L421-L430` `bind_tool_middleware` | `core/workflow.py` | move | 同步 `task_phase.set_middleware` |
| `#L432-L446` `_activate_tool_call` | `core/workflow.py` | move | 写 `task_phase.set_active_frame` |
| `#L448-L513` `start_tool_workflow` | `core/workflow.py` | move | 逐字保留守卫/孤儿（§4.9） |
| `#L515-L534` `cancel_tool_call` | `core/workflow.py` | move | 经回调触发全局停止 |
| `#L212-L214` `if_handle_yaw_pub` | `ros_adapter/core_channels_ros.py` | move | 端口化 |
| `#L536-L545` `_set_if_handle_yaw` | `core/actuators.py` `set_if_handle_yaw` | move | 经 `channels` 发布，守卫逻辑不变 |
| `#L204-L210` `emergency_stop_topic`+pub | `ros_adapter/core_channels_ros.py` | move | 端口化；`#L624`/`#L853` 改 `channels.publish_emergency_stop()` |
| `#L217-L219` `command_content_pub` | `ros_adapter/core_channels_ros.py` | move | 端口化 |
| `#L806`/`#L816`/`#L831`/`#L1007`/`#L972` 时钟关停 | `ros_adapter/core_channels_ros.py`（`RosRuntimeClock`） | move | engine 改 `self.clock.*` |
| `#L46-L72` `PendingAction` | （留 engine） | retain | D3 |

## 6. 删除清单（engine 旧位置直接删除，不留薄封装/注释桩）

| 删除项（`PKG/engine.py` 旧位置） | 理由 |
|---|---|
| `#L1020-L1060`/`#L1063-L1067` 两装配函数，`#L16` `threading`，`#L27-L38` `config` 装配符号 | 装配归 composition root |
| `#L23` `import rospy`、`#L24` `from std_msgs.msg import ...` | G7/G8；ROS 面迁适配层 |
| `#L204-L210`/`#L212-L214`/`#L217-L219`/`#L220-L224` 四个 Publisher 与 `emergency_stop_topic` 字段 | 迁 `ros_adapter/core_channels_ros.py`（端口化） |
| `#L256-L258`/`#L260-L265`/`#L296-L299`/`#L301-L313` 遥测/监控/诊断方法，`#L134-L138`/`#L151-L174` 遥测初始化块 | 迁 `core/telemetry.py` |
| `#L147`/`#L220-L225`/`#L315-L364` 相位桥与字段 | 迁 `core/task_phase.py` |
| `#L148`/`#L191-L197`/`#L410-L419`/`#L547-L573`/`#L632-L636` 注册表/归属/结果暂存/分发 | 迁 `core/skill_router.py` |
| `#L177-L187`/`#L421-L430`/`#L432-L446`/`#L448-L513`/`#L515-L534` 工具缝与 6 字段 | 迁 `core/workflow.py` |
| `#L536-L545` `_set_if_handle_yaw` | 迁 `core/actuators.py` |
| 全部 `rospy.log*` 直调、`rospy.Rate`/`is_shutdown`/`signal_shutdown` 直调 | 经 `LogSink`/`RuntimeClock` 端口 |

- engine 内**不得**保留任何同名薄封装（如 `self._telemetry = ...` 转发）或注释掉的方法。

## 7. 实施步骤（P0 … P6）

> 每期：范围 + 行为不变式 + 验收 + 回退。原则：先建端口与四通道（P1），再逐个迁协作对象。
> P0 与 P1 建议**原子提交**（P0 需要 P1 的端口构造）。

### P0 — 装配迁出

- 范围：`create_dispatcher_engine`/`start_dispatcher_workers` 移至 `NODE`；`NODE` import 改写；
  `create_dispatcher_engine` 增端口构造与注入。
- 行为不变式：启动序列（`init_node` → create → control_plane → workers → spin）逐行等价；
  `ros_params` 装载顺序与取值不变。
- 验收：`py_compile` 全绿；`NODE` 可导入；现有测试全绿。
- 回退：还原函数与 import。

### P1 — 端口 + 四通道适配落位

- 范围：新建 `core/ports.py`、`ros_adapter/core_channels_ros.py`（四类通道 + 运行端口）、
  两个 `__init__.py`；engine 四通道调用改端口（`self.channels.*`），`rospy.Rate`/关停/日志改
  `self.clock.*`/`self.runlog.*`；composition root 注入。
- 行为不变式：四类 topic 名/payload 逐字不变；`monitor/command_content`、`/agent_task_phase`、
  `if_handle_yaw`、急停的发布内容与触发时机不变。
- 验收：G7 命令对 `engine.py` 零命中（§8）；四 topic 抓包逐字节对比（§8）。
- 回退：还原调用点 + 删新增文件。

### P2 — 遥测 / 监控 / 诊断迁出

- 范围：新建 `core/telemetry.py`（`RunTelemetry`）；§2.4 块迁出；调用点改 `self.runlog.*`。
- 行为不变式：slog 事件名/键、trace 文件格式、`dispatcher_started` 键、
  `monitor/command_content` payload、等待诊断串格式（`channel=topic:age`，`never` 语义）字节级一致。
- 验收：启动后 stdout/`trace_*.jsonl` 含 `dispatcher_started`；`dispatcher_wait_cloud` 串格式一致。
- 回退：还原方法体与调用点。

### P3 — 任务相位桥迁出

- 范围：新建 `core/task_phase.py`（`TaskPhaseBridge`）；`#L147`/`#L220-L225`/`#L315-L364` 迁出；
  调用点改 `self.task_phase.publish(...)`；`_activate_tool_call` 迁出后改 `set_active_frame`。
- 行为不变式：`/agent_task_phase` payload 键序/取值、`on_tool_phase` 触发时机与先后、
  `task_phase_published` 事件字节级一致。
- 验收：mock middleware 下 `publish` 触发 `on_tool_phase(payload)`；payload 键序断言。
- 回退：还原。

### P4 — 技能注册表迁出

- 范围：新建 `core/skill_router.py`（`SkillRouter`）；§2.6 块迁出；FSM 三处 owner 查表改
  `self.skills.owner_skill(...)`；`_validate_active_tool`/`_handle_plan_tool` 委托。
- 行为不变式：空注册表下回退路径（未注册 logwarn + advance、post_action 默认 verdict）与现状等价。
- 验收：空表场景 `dispatch_plan` 返回 True 且走 `_advance_to_next_prompt`。
- 回退：还原。

### P5 — 工具执行缝迁出 + 接线

- 范围：新建 `core/workflow.py`（`ToolWorkflowHost`）；3 缝 + 6 字段迁出；
  `NODE` 改 `ToolControlPlane(engine.tools)`；`bind` 时同步 `task_phase.set_middleware`；
  逐字保留孤儿守卫（§4.9）。
- 行为不变式：`_publish_task_phase` 的 middleware 出口零改行；未绑定 middleware 时行为一致；
  `cancel_tool_call` 的 `task_action_client` None 守卫保留。
- 验收：`TESTS/` 全绿（`FakeHost` 不改）；绑定 mock 后 `cancel_tool_call` → `mark_cancelled`；
  `start_tool_workflow` 空注册表走 planning/fail 分支与现状一致。
- 回退：还原 3 缝 + 字段 + `NODE` 接线。

### P6 — 动作面迁出

- 范围：新建 `core/actuators.py`（`PlannerActuators`）；`#L536-L545` 迁出并改经 `channels` 发布。
- 行为不变式：`if_handle_yaw` topic 名与发布值、变更守卫（`getattr(..., True)==enabled` 早退）不变。
- 验收：`py_compile`；`self.actuators.set_if_handle_yaw` 调用点检查。
- 回退：还原。

## 8. 验收标准

> 命令用相对路径；`PKG`/`NODE`/`TESTS` 见 §0。

- [ ] 编译：`python3 -m py_compile` 对 `PKG/**/*.py` 与 `NODE` 全绿（A5）。
- [ ] 分级 import 冒烟：L1（零 ROS 子集）必过；L2/L3 依主机 ROS 环境判定，不可用时回退静态验收并记录（不得因环境缺失判失败）。
- [ ] 测试：`pytest l3-dispatcher-planner/tests/tool-registry` 全绿；`test_rpc_plane_navigation` 的
  scene_graph 用例维持「因技能族未迁而失败」的既有预期。
- [ ] **G7（engine/core 零 rospy）**：
  `grep -nE 'rospy\.|ros::|Publisher\(|Subscriber\(|SimpleActionClient' PKG/engine.py PKG/core/*.py`
  → **零命中**。
- [ ] **G8（逐文件零消息类型）**：
  `grep -nE 'from (std_msgs|geometry_msgs|sensor_msgs|nav_msgs|quadrotor_msgs|visualization_msgs)|import rospy' PKG/engine.py PKG/core/*.py`
  → 零命中。
  > **局部保留红**：engine 的 **import 闭包**仍经 `PKG/perception/base_policy.py` 命中 `*_msgs`（`#L24-L30`），
  > 属感知层，**归 S4**；本轮只保证 `engine.py`/`core/*.py` **自身**零 `*_msgs`。
- [ ] **A1（依赖方向）**：
  `grep -rnE 'dispatcher\.(utils|perception|core|ros_adapter)' PKG/tools/` → 零命中；
  `grep -rnE 'dispatcher\.ros_adapter' PKG/engine.py PKG/core/` → 零命中；
  `grep -rnE 'dispatcher\.engine' PKG/utils/ PKG/core/ PKG/perception/` → 零命中。
- [ ] **A2（适配面）**：
  `grep -rnE 'import rospy|^\s*from .*_msgs' PKG/engine.py PKG/core/` → 零命中（本轮范围）。
  > **全局 A2 留红**：`config.py`/`control_plane.py`/`zenoh_rpc.py`/`perception/*`/`NODE` 仍有 `rospy`，
  > 由 **S4** 收敛（登记于 §3）。
- [ ] **G2/G4**：`DISPATCHER_STATE` 成员数 == 6（`PKG/state.py#L25-L31`）；engine `def` 集合 ⊆ §4.2 白名单
  （最终白名单以 S1 定稿为准，**未核实**）；四类通道发布器对象仅存在于 `ros_adapter/core_channels_ros.py`。
- [ ] **字节级 slog**：脚本化跑同一 prompt 序列，改前/改后各存一份运行日志的 `trace/trace_*.jsonl`
  （存相对忽略目录）；对比命令（键集与事件名相等，`seq`/`ts_ns` 除外）：
  `diff <(jq -c 'del(.seq,.ts_ns)' before/trace.jsonl) <(jq -c 'del(.seq,.ts_ns)' after/trace.jsonl)`
  → 期望无差异（`dispatcher_started`、`dispatcher_state_transition`、`task_phase_published`、
  `tool_call_received`、`prompt_parsed`、`prompt_advanced` 等键集一致）。
- [ ] **字节级 topic**：对 `/agent_task_phase`、`monitor/command_content`、`if_handle_yaw`、急停主题，
  改前/改后各抓一帧（`rostopic echo -n1`，存相对忽略目录）逐字节 `diff` → 期望无差异；
  `/agent_task_phase` 需覆盖含 `message`/`result`/`error`/`status` 的相位，验证**键序**一致。
- [ ] **状态迁移 reason / 等待诊断串**：`dispatcher_state_transition` 的 `reason` 与
  `dispatcher_wait_cloud context=... channel=topic:age`（含 `never`）格式字节级一致。
- [ ] **启动序列**：`NODE` 启动期不新增/减少任何 ROS pub/sub；`init_node`→create→control_plane→workers→spin 顺序不变。
- [ ] **无残留桩**：`grep -nE 'self\._telemetry|self\._publish_task_phase|self\._handle_plan_tool|self\._set_if_handle_yaw|create_dispatcher_engine|start_dispatcher_workers' PKG/engine.py`
  → 不应命中（迁出后仅 `NODE` 命中）。

## 9. 风险与对策

| 风险 | 影响 | 对策 |
|---|---|---|
| S2 前置未落地（`utils/` 为空、`skill_api.py` 仍在包根） | S3 目标路径/import 前提不成立 | 严格以「S2 先于 S3」为执行前提；执行时按 S2 产物路径（`tools/skill_api.py` 等）重锚 import |
| S2 改写 engine import 导致行号平移 | 本方案行号失准 | §2 行号为 S2 前实测；执行时以**符号名**重锚（平移与否**未核实**） |
| `engine.py` 仍继承 `BasePolicyNode`（感知层含 rospy/`*_msgs`） | G8 闭包对 engine 判红 | 本轮只保证 engine/core **逐文件**归零；闭包级 G8 归 S4 感知拆分（登记 §3/§8） |
| `RuntimeClock`/`LogSink` 落在 `core_channels_ros.py` 而非 S4 的 `clock_ros.py` | 命名面混淆、被误当二次搬迁 | §4.6 明示：本文件承载四类通道 + 最小运行端口；S4 `clock_ros.py` 只服务装配/传输面，**不得**再迁本文件端口 |
| `_decision_chain_not_ready_reason` 孤儿 + `_start_prompt_task` 未定义调用被保留 | 任务注入轮次迁入后 `AttributeError` | 逐字保留不可达段（行为不变）+ 显式登记（§4.9/§10），不臆造实现 |
| 协作对象回引 engine 造成 core→engine 边 | 违反 §4.2、A1 判红 | `core/workflow.py` 等经**注入回调/协作者**工作，不 import engine；全局停止经回调 |
| `on_tool_phase` 出口被误并入 ROS 端口 | zenoh 传输混入适配层、先后顺序变化 | `on_tool_phase` 留 `core/task_phase.py`（非 ROS），`publish_task_phase` 仅发 topic；保持「先 middleware 后 topic」 |
| 四通道 payload 键序漂移 | 站端消费失败 | §4.6 固化键序；§8 topic 逐字节对比 |
| `_task_phase_progress` 无自增点 | 迁移后仍为死字段 | 如实保留桥内字段，不臆造自增（属技能轮次） |

## 10. 修改点清单汇总

| 文件 | 动作 | 说明 |
|---|---|---|
| `PKG/engine.py` | 修改 | 删除 §6 旧位置；改为组合 `self.runlog/task_phase/skills/tools/actuators/clock/channels`；保留 §4.2 方法集 |
| `PKG/core/__init__.py` | 新增 | 空包标记 |
| `PKG/core/ports.py` | 新增 | 端口 Protocol：`CoreChannels`/`RuntimeClock`/`Ticker`/`LogSink` |
| `PKG/core/telemetry.py` | 新增 | `RunTelemetry`（§2.4） |
| `PKG/core/task_phase.py` | 新增 | `TaskPhaseBridge`（§2.5） |
| `PKG/core/skill_router.py` | 新增 | `SkillRouter`（§2.6） |
| `PKG/core/actuators.py` | 新增 | `PlannerActuators`（§2.8） |
| `PKG/core/workflow.py` | 新增 | `ToolWorkflowHost`（§2.7） |
| `PKG/ros_adapter/__init__.py` | 新增 | 空包标记 |
| `PKG/ros_adapter/core_channels_ros.py` | 新增 | 四类通道 + 最小运行端口的 ROS 实现（§4.6） |
| `NODE` | 修改 | 吸收装配函数；构造并注入端口；host 改 `engine.tools` |
| `PKG/tools/skill_api.py` | 核对 | `SkillHost` 端口与 `SkillRouter` 契约一致性（**不新增/删减端口**，§2.10） |
| `TESTS/*` | 核对 | host duck-typed 三缝兼容（`FakeHost` 无需改） |

## 11. 附录：执行记录

### 2026-09-12 执行（S3 置 done）

- **执行者**：code-fixer 子智能体执行 P0+P1（原子）→P2→P3→P4→P5→P6；SOLO Agent 独立复验门禁；deep-oracle 独立评审。
- **快照**：`/tmp/diffagent2-s3-snapshot-20260912-163932`（engine 1067 行版 + tests）。
- **产物**：`engine.py` 1067→**754** 行；新增 `core/{__init__,ports,telemetry,task_phase,skill_router,actuators,workflow}.py` 与 `ros_adapter/{__init__,core_channels_ros}.py`（90 行）；`dispatcher_node.py` 48→139 行。
- **门禁实测（主 Agent 独立复跑）**：G7/G8 零命中；A1 三向零命中；残留桩零命中；py_compile 全绿；pytest 44 通过/6 既有失败（基线一致，TESTS 零改动）；**G2 AST 判定 GREEN**——7 文件 def 集合逐项 ⊆ `l3-core-boundary.spec.md` §4.1 白名单（engine 16 项含 `PendingAction.clear`，`_fail_unregistered_dispatch` 留白合法归 S6）；`DISPATCHER_STATE`=6。
- **deep-oracle 评审结论**：**放行置 done**（置信度高）。10 项复核全 PASS：四通道 topic/payload 逐字等价、slog 事件面零漂移、§4.10 冻结接口合规（二态返回/不推进不发相位）、依赖方向合规、孤儿与不可达段逐字保留、组合接线等价、G2 白名单逐项一致、tools/utils/perception 20 文件指纹零污染、三点裁决（unhandled_prompt 并入/无读点属性/LogSink 绑定）合规、spec 四处在位。
- **字节级验收的环境回退（R9）**：运行时 topic 抓包与 trace diff（§8）因本机 cv2×NumPy2 二进制不兼容无法起节点——静态逐字比对已覆盖全部 payload 表达式与事件键集；**登记：随下次带 ROS 环境联调补做 §8 的 topic/trace 逐字节 diff 作事后确认**。
- **R7 事件记录**：执行中发现 `specs/implemented/inner/l3-core-boundary.spec.md` 的 B3/G2/§4.1 白名单三处 S1 修订被外部进程回滚（B7 幸存）；已用**整文件原子写入**恢复并两次回读校验存活（md5 `0c80fb23…`）。
- **登记的后续轮次待办（CONCERN，不阻断）**：A `plan_tick()` 返回 False 语义已并入未注册回退（S6 裁决）；B `RunTelemetry` 四日志方法为实例属性绑定（建议 spec §4.1 补注，并入下一次 spec 触点）；C `if_handle_yaw` 双源状态（随 arm_action 轮次统一）；D 等待诊断 try 范围扩大（触发概率极低，备注）；E Publisher 创建时序前移（无状态副作用，备注）；`ToolWorkflowHost` 缺三条直发缝（既有断裂，归任务注入轮次）；`snapshot_owner`/`stash_task_result`/`register` 暂无调用方（待技能族/arm_action 轮次接入）。

> 注：本附录曾于 2026-09-12 回写后被外部进程（Trae IDE 陈旧缓冲）回滚丢失，2026-09-13 依据会话记录重建，内容与首次回写一致。

**登记的后续轮次（不在本轮）**：`SkillHost` 11 端口 + 三条直发缝（`forward_*`）与技能族同轮落地；
任务注入轮次（`_start_prompt_task`/`arm_action`）处置 §4.9 断裂；S4 承接 `config.py` ROS 参数面、
`control_plane.py`/`zenoh_rpc.py` 的 rospy 关停与日志、`perception/*` 收发。

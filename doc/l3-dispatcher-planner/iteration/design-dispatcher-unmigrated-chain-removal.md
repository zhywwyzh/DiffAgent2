# dispatcher 未迁入链路删除方案

> 摘要：用户明确允许将未迁入能力整链删除，后续整体重构。先删除已确认无实现的场景导航链；其他未实现工具是否同时移除，依据用户对范围的补充选择执行。

## 0. 元信息

| 项 | 值 |
|----|----|
| 日期 | 2026-09-15 |
| 目标路径 | `l3-dispatcher-planner/ros_packages/dispatcher/` |
| 状态 | done |
| 关联文档 | `l3-core-boundary.spec.md`、`l3-tool-plane.spec.md`；本轮核心边界落实与两份结构方案 |

## 1. 背景与动机

对外声明能力必须有对应实现。场景图导航当前仅有元数据、旧 RPC 参数转换和测试，实际模块不存在；继续保留会误导发现面并掩盖能力缺失。

## 2. 现状事实（问题清单）

- `l3-dispatcher-planner/ros_packages/dispatcher/dispatcher/tools/registry.py:57` 注册场景查询、导航及五项图编辑工具，实际技能目录不存在。
- `l3-dispatcher-planner/ros_packages/dispatcher/dispatcher/utils/rpc_plane.py:126` 动态导入不存在的 `scene_nav.graph_source`。
- `l3-dispatcher-planner/ros_packages/dispatcher/dispatcher/utils/zenoh_rpc.py:583` 写场景缓存，无读取方。
- `l3-dispatcher-planner/ros_packages/dispatcher/dispatcher/ros_adapter/feedback_ros.py:46` 订阅场景对象，只写上述无读取方缓存。
- `l3-dispatcher-planner/tests/tool-registry/test_rpc_plane_navigation.py:117` 测试替换不存在的模块，导致六项基线失败。
- `l3-dispatcher-planner/ros_packages/dispatcher/dispatcher/tools/executor.py:27` 飞行直发宿主方法也未实现；其余工作流受缺失任务注入入口阻断。

## 3. 目标与约束

- 目标：删除未实现能力的整条生产链路，旧请求按未注册拒绝；保留已实现的连接、事件、通用调度基础设施。
- 非目标：补造缺失技能，保留兼容别名、空实现或未迁入提示桩。
- 硬边界：先修改相关发现面契约；不为测试全绿而隐藏失败；通用测试改用明确注入的测试能力，不再把缺失能力当作生产实现。

## 4. 方案决策

保持 `tools/`、`utils/`、`core/`、`ros_adapter/` 平面职责布局及既有小写下划线命名。场景链删除覆盖注册项、RPC 别名和对象解析、ROS 订阅、无读取方缓存、无消费者配置及专属正例测试。补充旧入口拒绝负例，确保无任务入队。

工具发现集合与哈希在 `l3-tool-plane.spec.md` 同步缩减。删除范围若扩展到全部未实现工具，默认生产注册面为空；通用注册表、生命周期账本与队列机制以独立测试能力验证。

## 5. 迁移映射表

| 旧路径/命名 | 新路径/命名 | 动作 | 备注 |
|----|----|----|----|
| 场景工具注册与别名 | 无 | delete | 缺失能力不对外声明 |
| 场景对象解析、订阅与缓存 | 无 | delete | 实现缺失或无消费者 |
| 场景成功调用测试 | 已删除入口拒绝测试 | rewrite | 验证实际边界 |

## 6. 删除清单

| 删除项 | 理由 |
|----|----|
| `scene.map_search`、`scene.navigate`、五项 `scene_nav.graph.*` 注册 | 无对应实现 |
| `navigation.scene_graph_nav` 别名与 `_resolve_scene_object_id` | 依赖不存在模块 |
| 场景对象反馈订阅及缓存 | 无读取方 |
| 场景专属默认配置与装载入口 | 无消费方 |
| 六项依赖缺失模块的场景成功测试及专属辅助数据 | 被能力删除替代 |

## 7. 实施步骤

### P0 — 场景链删除

- 范围：上述完整链路与发现面契约。
- 不变式：连接租约、终态唯一、通用核心方法不变。
- 验收：删除项生产代码零残留；入口拒绝且不入队；核心与工具面回归。
- 回退：仅恢复本方案差异。

### P1 — 按确认范围扩展

- 范围：依据用户补充选择删除其他未实现工具。
- 不变式：保留通用机制，不伪装能力已实现。
- 验收：生产发现集合与 spec 一致；通用机制用测试能力验证。
- 回退：仅恢复扩展差异。

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
| 调用方仍使用旧能力 | 请求失败 | 明确未注册拒绝，同步删除发现声明 |
| 所有能力都未接入完整实现 | 删除后可能没有生产工具 | 已明确向用户说明并请求范围选择 |
| 误删通用机制测试 | 丢失回归覆盖 | 使用测试自有能力验证通用机制 |

## 10. 修改点清单汇总

| 文件 | 动作 | 说明 |
|----|----|----|
| `tools/registry.py`、`utils/rpc_plane.py` | 修改 | 删除能力注册及入口解析 |
| `utils/zenoh_rpc.py`、`ros_adapter/feedback_ros.py` | 修改 | 删除无消费反馈链 |
| `utils/config.py`、`dispatcher_node.py` | 修改 | 删除无消费配置 |
| `tests/tool-registry/` | 修改 | 删除专属旧测试，补充拒绝验证 |
| `specs/implemented/inner/l3-tool-plane.spec.md` | 修改 | 同步发现集合、哈希和原因集合 |


执行范围确认：用户明确要求删除所有未迁入链路。P1 执行范围为全部 14 项生产工具元数据、所有飞行与导航 wire 别名/参数转换、三条飞行直发分支、工作流的缺失任务注入守卫及不可达实现，以及无来源的抓取反馈/查询、场景缓存、记录服务上行/快照链。`SkillHost` 的缺失记录服务和 VLM 属性删除；实际存在的感知服务、几何算法、planner 与通用端口协议保留。默认注册面为空，测试能力只定义在测试目录。

通用核心任务入口通过已存在的 PromptQueue/StateLedger/SkillRouter 接线，删除对不存在方法的调用，不引入工具能力或旧接口转接。租约丢失直接调用注入的全局停止端口，不再伪造已删除急停工具；端口缺失或执行异常保持 fail-closed。连接类旧 queryable 测试同步到现行单 RPC 契约。

行为变更登记：生产工具集合变为空；旧工具及别名请求拒绝为 method_not_found；删除资源主题 `grasp_result/*`、`agent_log`、`agent_log/snapshot` 及 ROS 反馈 `/agent/grasp_result_image`、`/agent_scene_objects`、`/Instruct_res`；保留 `sim/reset`、`health` 和连接 RPC。记录上行无调用方，删除其后台线程；租约 watchdog 保留。


无调用方复核：AST 检索属性、注解和动态读取字符串后，另删除无生产读取方配置：`nav_tools`、`segment_nav_enabled`、`search_thinking_enabled`、`task_generation_guard_enabled`、`return_publish_mode`、`return_start_timeout_s`、`return_finish_timeout_s`、`sleep_for_turn`、`action_reach_threshold`、`search_success_distance_thresh`、`if_safe_mode`、`max_yaw_search`、`search_rot_yaw`、`max_z_search`、`search_pos_z`、`d_side`、`d_forward`、`bypass_dist`、`reacquire_interval`、`partial_bbox_recenter_enabled`、`partial_bbox_edge_margin_px`、`partial_bbox_max_attempts`、`partial_bbox_max_yaw_step_deg`、`llm_stamp_match_tolerance`、`planner_mode_topic`、`planner_mode_repeat`、`planner_mode_interval`、`start_yaw_deg`。保留通用宿主端口声明中的配置字段及感知实际使用字段。


补充删除：`COMMAND_TYPE` 中无任何读取方的旧命令枚举删除，仅保留核心使用的 WAIT/STOP。租约立即安全停后，消费线程用 runtime.can_execute 拒绝已终态、取消或被抢占的队列调用，避免重新执行已失效任务。


验收链删除补充：`tests/zenoh-bench/verify_routing.py:17` 起的矩阵只验证已删除的飞行/VLA/场景工具，其启动脚本、launch 和 mock 均无其他调用方，删除整个专属目录中的六个文件。`tests/telemetry-bridge/verify_telemetry.py:105` 启动未迁入的 `ros_packages/bridges/scripts/drone_bridge.py`，仓库不存在该实现，删除两份专属验证/启动文件。保留本轮真实核心与通用控制面回归。


最终交付记录：结构拆分、核心契约修复与用户追加的全部未迁入链路删除合并交付。`engine.py` 从开始时约 784 行缩为 373 行。`workflow.py` 在重命名阶段逐字迁移，后续通用入口接线与缺失链删除由 `design-dispatcher-unmigrated-chain-removal.md` 接管，故最终文件内容不再与旧版本逐字相同；无旧路径兼容入口。

结构理由已归档至 `specs/implemented/architecture/2026-09-15-dispatcher-core-and-capability-pruning.md`。工作区未提交、未推送。最初既有工具面基线为 52 通过、7 失败；删除无实现链路并将旧连接 queryable 断言对齐现行单 RPC 契约后，最终回归全绿。

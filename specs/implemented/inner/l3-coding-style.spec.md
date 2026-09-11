# Coding Style

Status: implemented
Contract-ID: development-workflow/l3-coding-style
Parent: specs/implemented/development-workflow.spec.md

> 适用于 `ros_packages/` 下的全部 C++。新代码必须合规；遗留代码遵循
> 迁移策略（§7）。`mission_executive` 包已在采纳提交中整体迁移。

> 范围：命名、Doxygen/单位标注、头文件布局、格式化。工程向的 Doxygen
> 模板是基线；本 spec 在它之上扩展出下面的单位标注与命名规则。

## 1. Naming

> 类型、函数、变量、成员与常量统一遵循同一套命名方案，缩写受白名单限制。

### 1.1 类型、类、结构体、枚举

> 类型式名称用 PascalCase；枚举值用大写蛇形命名。

- PascalCase：`MissionCore`、`FSMData`、`MISSION_FSM_STATE`。
- 枚举值：`UPPER_SNAKE_CASE`（`WAIT_TRIGGER`）。

### 1.2 函数 / 方法

> 动作使用动词开头的 camelCase，accessor 遵循固定的 get / is / set 前缀方案。

- camelCase，动作语义时动词开头：`transitionToState`、
  `publishLocalGoalWindow`、`selectAndPublishNextWaypoint`。
- Accessor 使用固定的三类前缀方案（每个 `MissionCore` accessor 都合规）：
  - Getter：`get` 前缀 + 完整单词名词：`getState()`、`getData()`、
    `getMission()`、`getDroneId()`、`getParams()`（可变配置 accessor 也在此列）。
  - 布尔谓词（is-问句）：`is` 前缀：`isExecutionFinished()`、
    `isResetPending()`。
  - Setter：`set` 前缀：`setDroneId()`、`setTargetCmd()`、
    `setPriorKnowledge()`。

### 1.3 变量与参数

> 变量与参数使用全词的 camelCase，命名表达领域含义而非类型。

- 全词 camelCase。不得自造缩写。参数命名表达它在领域里“是什么”，
  而非类型或存储：可见性查询用 `source`/`target`，修复点用 `midpoint`，
  航点用 `waypoint`。
- 单字母参数禁止，3 行作用域内的循环索引（`i`、`k`）除外。

### 1.4 成员变量

> 成员变量带尾下划线，单位标注在注释里而非名字里。

- 尾下划线：`odometry_position_`、`waypoint_batch_sequence_`。
- 单位标注在 Doxygen 注释里，不在名字里；一个例外：当成员本身就是
  协议/参数字段名时，单位后缀是名字的一部分（`timeout_s` 镜像 ROS 参数）。

### 1.5 常量

> 常量用 k 前缀 + PascalCase。

- `k` + PascalCase：`kYawModeNormal`、`kPromptTypeDfDemo`。

### 1.6 缩写策略（白名单）

> 只允许白名单内的缩写；其它一律写全。

允许直接使用：

| Token | Notes |
| --- | --- |
| `yaw`/`pitch`/`roll` | 姿态术语 |
| `odom` / `odometry` | 二者皆可，新代码优先 `odometry` |
| `topo` | topology（场景图术语） |
| `poly`/`polyhedron` | polyhedron（场景图术语里 `poly` 允许） |
| `skeleton` | 场景图术语 |
| `df_demo` | DF-demo 领域流程 |
| `object_id_nav` | object-id 导航领域流程 |
| `panorama` | 领域流程 |
| `waypoint` | 领域术语 |
| `stuck` | 卡住检测领域术语 |
| `dwell` | 到达驻留领域术语 |
| `sg_`/`map_`/`vis_` | 接口组前缀（仅 MissionPorts） |

禁止（必须写全）：

| Forbidden | Written in full |
| --- | --- |
| `cur` | `current` |
| `inx` | `index` |
| `thr` | `threshold` |
| `dis` | `distance` |
| `aim` | `target`（场景图 “aim” 术语除外） |
| `mid` | `midpoint` |
| `mtx` | `mutex` |
| `pos` | `position` |
| `vel` | `velocity` |
| `acc` | `acceleration` |
| `pt` | `point` |
| `seq` | `sequence` |
| `init` | `initialize`（动词） |
| `inited` | `initialized` |
| `cmd` | `command` |
| `arg`/`args` | `argument(s)` |
| `param` | `parameter` |
| `traj` | `trajectory` |

### 1.7 缩写映射表

> 此表是 mission_executive 迁移后的权威旧→新重命名映射。

| Old | New |
| --- | --- |
| `md_` | `mission_data_` |
| `fp_` | `params_` |
| `fd_` | `data_` |
| `mtx_` | `mutex_` |
| `odom_pos_` / `odom_vel_` / `odom_orient_` / `odom_yaw_` | `odometry_position_` / `odometry_velocity_` / `odometry_orientation_` / `odometry_yaw_` |
| `path_res_` / `path_inx_` | `planned_path_` / `path_index_` |
| `aim_pos_` / `aim_yaw_` / `local_aim_pos_` | `target_position_` / `target_yaw_` / `local_target_position_` |
| `ego_exec_finished_` | `planner_execution_finished_` |
| `wp_batch_*` / `wp_window_*` | `waypoint_batch_*` / `waypoint_window_*` |
| `pubLocalGoal` | `publishLocalGoalWindow` |
| `transitState` | `transitionToState` |
| `stashCurStateAndTransit` | `stashStateAndTransition` |
| `getAndPublishNextAim` | `selectAndPublishNextWaypoint` |
| `isInited` | `isInitialized` |
| `visRepairMid` | `visRepairMidpoint` |
| `state` | `getState` |
| `data` | `getData` |
| `mission` | `getMission` |
| `activeTaskId` | `getActiveTaskId` |
| `activeSessionId` | `getActiveSessionId` |
| `droneId` | `getDroneId` |
| `params` | `getParams` |
| `resetPending` | `isResetPending` |

任何迁移都在同一提交里更新此表。

## 2. Doxygen comments

> 公共 API、数据成员与枚举值需要按带单位模板写 Doxygen 注释。

- 必需：公共/接口 API（每个 `MissionPorts` 方法、每个公共
  `MissionCore` 方法、节点入口）、数据成员、枚举值。
- 可选：私有方法（物理/数学不显然时鼓励写）。
- 模板（扩展了单位）：

```cpp
/**
 * 函数物理含义的单句描述。
 *
 * @param[in]  name  带单位的描述 [m]
 * @param[out] name  带单位的描述 [rad]
 * @return 带单位的描述 [m/s]
 */
```

- `@param` 必须带方向（`[in]`/`[out]`/`[inout]`）；`@return` 必须带单位。
  4–6 行；不用 `@brief`。

## 3. Unit annotation

> 单位标注在 Doxygen 方括号里，绝不在参数名或成员名里。

- 单位标注在 Doxygen 方括号里：`[m]`、`[rad]`、`[s]`、`[m/s]`、
  `[rad/s]`，无量纲用 `[--]`。
- 参数/成员名不带单位（不用匈牙利式后缀），协议字段名（`timeout_s`）除外。

## 4. Header layout

> 头文件保留既有的 include guard、include 顺序与 namespace 包裹约定。

- Guard：`_<PACKAGE>_<FILE>_H_`（既有约定，保留）。
- Include 顺序：先本包头，再其它工作区包，再第三方，再系统。
- `namespace mission_executive { ... }` 包裹整个 API。

## 5. Formatting (clang-format)

> 格式化遵循项目根 `.clang-format`；重新格式化时直接运行 clang-format。

- 项目根 `.clang-format`（LLVM 基座、2 空格缩进、120 列上限、左指针、
  include 排序关闭）。
- 重新格式化时直接运行 `clang-format`；编译镜像不含 clang-format。

## 6. Behavior contract

> 重命名绝不改变 slog 事件、迁移原因，或 topic、参数、消息字段名。

- 重命名绝不得改变：slog 事件名、`transitionToState` 原因字符串、
  topic/param 名、消息字段名。这些是行为契约；字符串级 diff 是迁移验证。

## 7. Migration strategy

> 新代码立即合规，被触及的文件在同一提交里改名，包级迁移使用专用提交。

1. 新代码 / 新文件从一开始就必须合规。
2. 被功能改动触及的文件应在同一提交里改名合规（仅改名，不改逻辑）。
3. 包级迁移在大型重构窗口期用专用 `refactor:` 提交完成，随后跟一个专用
   `style:` clang-format 提交。两个提交分开以便评审。
4. 每次迁移的验证：`make compile` 干净 + 字符串契约 diff（slog 事件 /
   迁移原因 / topic 保持不变）。

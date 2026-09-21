# dispatcher 场景图能力迁移方案

> 摘要：把 DiffAgent2 旧版的场景图（几何骨架 + 对象层 + 区域聚类 + 图存储/画廊）
> 迁入新版，落为 `ros_packages/scene_graph/` 的 C++ 共享几何能力、
> `dispatcher/perception/` 的图投影数据面、`dispatcher/tools/scene_nav/` 的技能家族。
> **在线建图链与 mission_executive 侧对象导航不迁**，按 `rest/` 台账登记。
> 本方案是过程材料，非权威；契约以 `specs/` 为准。

## 0. 元信息

| 项 | 值 |
|----|----|
| 日期 | 2026-09-20 |
| 目标路径 | `l3-dispatcher-planner/ros_packages/scene_graph/`；`l3-dispatcher-planner/ros_packages/dispatcher/dispatcher/{perception,tools/scene_nav,ros_adapter}/`；`specs/` |
| 状态 | proposed |
| 关联文档 | 姊妹篇：`20260915-20260917/design-dispatcher-unmigrated-chain-removal.md`（场景链删除取证）、`design-dispatcher-vla-migration.md`（几何归属先例）、`design-dispatcher-vla-waypoint-executor-migration.md`（几何上移先例）、`design-dispatcher-package-layout-and-naming-unification.md`（平面划分）；台账：`../rest/dispatcher-deferred-dependencies.md`、`../../../doc/rest/task-id-to-tool-name-deferred.md`；契约：`l3-execution-seam`、`l3-skill-contract`、`l3-ros-adapter-boundary`、`l3-package-layout`、`l3-migration-protocol` |

## 1. 背景与动机

新版早前把场景导航链按「实际模块不存在」整链删除，理由是当时只有元数据、旧 RPC 参数
转换与测试。本轮要迁的不是那条空壳，而是旧库里**确实存在**的实现：一个 C++ 几何骨架库
（自由空间凸多面体分解 + 拓扑 A* + 对象层 + 区域聚类 + 图存储）与消费它的场景导航技能。

同时必须承认两个前提：

1. 旧库该 C++ 库的**在线建图能力已被摘除**（失去 `map_interface` 依赖），当前只能承担
   「读图 → 搜路 → 对象查询」，这一点决定了本轮迁移范围（§2、§3）。
2. 旧库真正的对象导航执行体在 `mission_executive`，而 `l3-execution-seam` §1 与门禁 G10
   明令该包不得迁入。因此**对象导航下行必须重新设计归属**，不能原样搬运
   （`l3-migration-protocol` §2 裁决顺序、§4 禁止转接器）。

为什么现在做：`doc/rest/task-id-to-tool-name-deferred.md` 已登记 `navigation.scene_graph_nav`
为「技能未迁入时拒绝调用；**不据此登记为永久删除**」；`rest/spec-history-and-log-migration.md`
把「场景导航日志生产者」裁决给 dispatcher 工具及工具状态机，并注明「场景工具迁入时逐项核验」。
即：能力身份已被保留登记，本轮是把它真正落地的一轮。

## 2. 现状事实（问题清单）

> 路径约定：`OLD/` = `<old-repo-root>/diff-dockers/drone_projects/l3-dispatcher-planner/ros_packages/`；
> `NEW/` = `l3-dispatcher-planner/ros_packages/`。行号仅作锚点，以符号为准。

### 2.1 旧库可迁的实现面

- [ ] `OLD/scene_graph/src/skeleton_generation.cpp`（2090 行）— 骨架生成：球面采样 → raycast
      → quickhull 凸包 → facet → frontier 聚类 → 增量扩张（`expandSkeleton` L317-L409、
      `initNewPolyhedron` L456-L536、`generateFrontiers` L538-L763、`processAValidFrontier` L864-L916）。
- [ ] `OLD/scene_graph/src/skeleton_astar.cpp` — 多面体图上的 A*（两处 `astarSearch` 重载，
      `skeleton_generation.cpp` L169-L229）。
- [ ] `OLD/scene_graph/src/skeleton_cluster.cpp`（900 行）— `SpectralCluster`（谱聚类）与
      `AreaHandler`（Leiden/CPM 社区发现，`incrementalUpdateAreas` L422 起）。
- [ ] `OLD/scene_graph/src/object_factory.cpp`（1423 行）— 分割掩码 → 反投影 → OBB → CLIP 特征
      → 空间/语义相似度融合（`object_map_`）。
- [ ] `OLD/scene_graph/src/scene_graph_map_io.cpp`（53 KB）— 图持久化：`scene_graph.json`
      （`format_version: 1`）+ `manifest.json` + `objects/*.pcd`（save 段 L790-L818、load 段 L823 起）。
- [ ] `OLD/scene_graph/include/scene_graph/data_structure.h` — 领域数据结构（`ObjectNode` L153、
      `Vertex` L235、`Facet` L277、`Polyhedron` L324、`PolyhedronFtr` L400、`Edge` L458、
      `PolyhedronCluster` L499）。
- [ ] `OLD/scene_graph/include/scene_graph/skeleton_generation.h` L22-L57、L64-L75 — `INFO_MSG*`
      流宏与 KD 树别名（日志面待按 `observability-log` 改造）。
- [ ] `OLD/scene_graph/src/scene_graph_bridge_node.cpp` — 7 个 srv 的 ROS 宿主（`load_map`/
      `save_map`/`path_to_object`/`object_info`/`set_target_knowledge`/`vis_tick`/`vis_path`，L69-L77）。
- [ ] `OLD/scene_graph/src/cloud_fov_limit.cpp` — 前向 FOV 点云裁剪节点（`/cloud_fov_limited`）。
- [ ] `OLD/scene_graph/src/scene_graph.cpp` L21-L59、L95-L187、L760-L788 — `initSceneGraph` /
      `updateSceneGraph` / `getPathToObjectWithId` / `mountCurPoly` / `refreshLoadedMapVisualization`。
- [ ] `OLD/dispatcher/dispatcher/tools/scene_nav/`（7 个 py）— 消费侧技能家族：
      `scene_nav_skill.py`（28.7 KB，`name="scene_nav"`，`scene.map_search`/`scene.navigate`）、
      `graph_skill.py`（`name="scene_graph_edit"`，`synchronous=True`）、`graph_source.py`
      （canonical 目录投影 + mtime 缓存）、`graph.py`、`config.py`（`INSTRUCTION_TYPE`）、`chain_log.py`。

### 2.2 旧库的退化与外部依赖（决定本轮范围）

- [ ] `OLD/scene_graph/src/skeleton_generation.cpp` L52-L53 — `SkeletonGenerator(ros::NodeHandle&)`：
      构造函数**不再接收** `ego_planner::MapInterface::Ptr`；同文件 L1684-L1719 的 `rayCast`
      只剩 facet 碰撞（返回 `0`/`-2`），`-1`（撞占据）/`-3`（z 向虚拟墙）分支已删；
      L1722-L1734 的 `searchPathInRawMap` 已是 stub（直接返回直线 `true`）。
      → **在线建图不可用**，迁入也无法恢复（工作区内其他 `planner/scene_graph` 副本的构造函数
      仍持有 `map_interface_`，可作对照基线）。
- [ ] `OLD/scene_graph/CMakeLists.txt` L14-L29 — `find_package(catkin ...)` 已无 `map_interface`
      组件（对照副本同处含该组件）。
- [ ] `OLD/scene_graph/include/scene_graph/skeleton_generation.h` L282 — `map_inflate_sub_` 是死成员；
      L392-L398 的扩张耗时看门狗整段注释，`_expand_time_limit` 不生效。
- [ ] `OLD/mission_executive/src/handlers/mission_core_object_nav.cpp`、`mission_fsm_ros.cpp`、
      `mission_executive/handlers/object_nav.py` — 对象导航的实际执行体（mount + path + 下发）
      **在 mission_executive 内**，受 `l3-execution-seam` §1/G10 禁止迁入。
- [ ] 同上文件 L11-L59、L93-L140、L167-L216、L445-L489 — **object 级语义全部在此状态机内**，
      planner 侧只收航点批次、**从不知道 `object_id`**：到达判据为位置 + 终端偏航双条件
      （`pos_finish && yaw_finish && final_topo_stage`）、任务级 deadline 与重规划上限、
      重规划订阅 `/object_id_nav_replan`；参数命名空间 `object_id_nav/*`
      （`waypoint_skip_xy_distance` 0.3、`task_timeout` 45.0、`task_terminal_timeout` 15.0、
      `task_max_replans` 1、`require_final_yaw` true、`final_yaw_tolerance_deg` 10.0、
      `final_approach_max_attempts` 6，`mission_fsm_ros.cpp` L85-L97、L131）。
- [ ] 终态原因词表（同上文件）：`kTaskReasonReached` / `kTaskReasonUnreachable` /
      `kTaskReasonTimeout` / `kTaskReasonFailed` / `kTaskReasonPreempted`
      （`mission_core_object_nav.cpp` L66/L123/L137/L216/L462）。
- [ ] `OLD/utils/quadrotor_msgs/msg/Instruction.msg` L41-L45 — `TURN_OBJECT_ID_NAV=2` 与
      `TURN_WAYPOINT_NAV=7` 并存，且同消息携带 `nav_waypoint[]`/`nav_yaw[]`：
      旧链的对象语义靠上层状态机、下行靠航点字段，二者不在 planner 内合流。
- [ ] `OLD/utils/quadrotor_msgs/msg/Instruction.msg` — 旧链以 `Instruction(instruction_type=2
      TURN_OBJECT_ID_NAV, target_obj_id)` 驱动 planner；`NEW/utils/quadrotor_msgs/msg/` 只有
      7 个 msg（`EgoStateTrigger`/`LocalGoalSet`/`PiecewisePolynomial`/`PlannerResult`/
      `PositionCommand`/`TakeoffLand`/`WaypointProgress`），**无 `Instruction.msg`**；
      `NEW/planner/` 全树 `object_id_nav` 零命中。
- [ ] `OLD/dispatcher/dispatcher/tools/scene_nav/scene_nav_skill.py` L37、L208-L224、L473-L513 —
      消费侧同时依赖 `rospy`（`/scene_graph/json_text`、`/planner/fsm_state`）、
      `rospy.get_param("/scene_graph/active_name")`、`fsm/scene_graph_load_name`、
      `dispatcher.tools.scene_nav.graph_source`；后者为**延迟导入**。
- [ ] `OLD/dispatcher/dispatcher/tools/scene_nav/config.py` L10-L18 — `INSTRUCTION_TYPE` 常量表
      （`TURN_OBJECT_ID_NAV=2`、`SCENE_GRAPH_REQUEST=11`）：本轮只保留图相关取值，导航取值随
      §4.1 裁决 6 处置。

### 2.3 新库现状

- [ ] `NEW/dispatcher/dispatcher/perception/`、`.../support/` — **空目录**（`l3-package-layout` §1
      已把 `perception/` 定义为「感知」平面，但无行为契约、无文件）。
- [ ] `NEW/dispatcher/dispatcher/tools/` — 只有 `flight/`、`vla/`；无 `scene_nav/`。
- [ ] `NEW/dispatcher/dispatcher/ros_adapter/` — 5 个文件（`clock_ros`/`core_channels_ros`/
      `feedback_ros`/`params_ros`/`planner_execution_ros`）；无场景图适配文件。
- [ ] `NEW/dispatcher/dispatcher/tool_plane/registry.py` L36-L41 — `ToolRegistry.default()`
      只汇入 `flight_specs()` + `vla_specs()`；发现面 = 六个 `basic_flight.*` + `navigation.vla_nav`。
- [ ] `NEW/dispatcher/dispatcher/tools/vla/` — 家族文件形态基线：`__init__.py`、`catalog.py`、
      `ports.py`、`vla_skill.py`、`vla_geometry.py`（`design-dispatcher-vla-geometry-rename-*.md` §3 定的
      `geometry.py → vla_geometry.py` 改名）。
- [ ] `NEW/dispatcher/dispatcher/execution/` — `ports.py`/`skill_host.py`/`waypoint.py`/`composition.py`。
- [ ] `NEW/dispatcher/dispatcher_node.py` — 装配根（位于 ROS 包根，与 `dispatcher/engine.py` 同责）。
- [ ] 既有删除事实：`20260915-20260917/design-dispatcher-unmigrated-chain-removal.md` L43-L55 —
      `scene.map_search`/`scene.navigate`/五项 `scene_nav.graph.*` 注册、`navigation.scene_graph_nav`
      别名与 `_resolve_scene_object_id`、场景对象反馈订阅及缓存均已删除；同文 L104 声明
      「实际存在的感知服务、几何算法、planner 与通用端口协议保留」。
- [ ] 悬空引用：`NEW/dispatcher/dispatcher/tool_plane/` 与测试中仍有对
      `dispatcher.tools.scene_nav.graph_source` 的字符串 patch/延迟引用
      （`design-dispatcher-package-topology.md` L122/L144/L555 登记为「技能族未迁」）。

## 3. 目标与约束

- **目标**：
  1. 把场景图的**只读几何能力**迁入新版，成为 dispatcher 可复用的共享几何能力；
  2. 恢复 `scene.map_search`（取图/投影）与 `scene.navigate`（到对象的航点链）两个对外能力；
  3. 恢复 `scene_nav.graph.*` 五项图查询/编辑工具（同步技能）；
  4. 让 `NEW/` 全树对 `dispatcher.tools.scene_nav.*` 的引用不再悬空。
- **Non-Goals**：
  - **不迁在线建图链**（`expandSkeleton`/`generateFrontiers`/`processAValidFrontier`/frontier/gate
    全套、`initSceneGraph`/`updateSceneGraph`、`cloud_fov_limit`）——旧库已无 `map_interface`
    依赖，迁入后不可用（§2.2），且在线 builder 另有归属，不在本契约范围。
  - **不迁 mission_executive 及其对象导航执行体**（`l3-execution-seam` §1、G10）。
  - **不迁 `Instruction.msg` / `TURN_OBJECT_ID_NAV` / `object_id_nav` 下行**（§4.1 裁决 6）。
  - 不迁可视化面（`/scene_graph/vis`、`/skeleton_vis`、`/skeleton/cluster_vis`、
    `visualizeSceneGraph` 等）——无站端消费者，按 §4.1 裁决 7 处置。
  - 不迁 `CountingSceneGraph`、VLA prompt/LLM 编排面（`sendPrompt`/`*PromptGen`/`handle*Result`）、
    `SpectralCluster`（被 Leiden/CPM 取代的旧路径）。
  - 不迁任务编号相关的一切（`l3-core-boundary` B2/B7/B8、`l3-migration-protocol` §4）。
- **硬边界**：
  - 禁止新设计转接器来转接新旧接口（除非用户明确允许）；
  - 被替代的旧接口必须删除，不得保留为转接口，也不得仅注释掉；
  - 契约先行：P0 未落地前不动代码（`l3-migration-protocol` §1、§3、G18）；
  - 契约只写在 `specs/` 下（`specs/README.md` 规则 2）。

## 4. 方案决策

### 4.1 归属裁决（`l3-migration-protocol` §2 顺序，命中即止）

| # | 待迁单元 | 命中条款 | 裁决 | 落点 |
|---|----------|----------|------|------|
| 1 | `skeleton_astar`、`skeleton_cluster`、`scene_graph_map_io`(读)、`data_structure`、`ikd_Tree`、`quickhull` | §2-③ 跨多任务共享的几何能力 → 共享服务；形态按 `l3-execution-seam` §3「高密度几何/拓扑搜索 → C++，经 pybind 暴露为执行缝的一个能力端口」 | **迁**（只读能力） | `ros_packages/scene_graph/`（`scene_graph_core` 无 ROS + ROS 外壳） |
| 2 | `object_factory`（对象层：OBB/特征/融合） | §2-③ 共享几何/感知能力 | **迁**（在线检测线程不迁，只保留图内对象的读/融合数据结构） | 同上（`scene_graph_core`） |
| 3 | 图投影与对象匹配（读 canonical 目录 → `{objects:[{id,label,pos}]}`） | §2-③ 共享感知数据面；`l3-package-layout` §1 `perception/` = 感知 | **迁** | `dispatcher/perception/` |
| 4 | `scene.map_search`、`scene.navigate` | §2-② 只在某一任务流程中被调用 → 技能 | **迁** | `dispatcher/tools/scene_nav/` |
| 5 | `scene_nav.graph.{list,select,save,objects,object_pose}` | §2-② → 技能（旧库 `synchronous=True`，`l3-skill-contract` §2 有对应声明） | **迁** | `dispatcher/tools/scene_nav/` |
| 6 | 对象导航下行（`mountCurPoly` + A* + `Instruction(TURN_OBJECT_ID_NAV)` + planner `object_id_nav`） | §2-⑦ 对应任务上游尚未实现（mission_executive 禁迁、planner 无该模式） | **不迁，登记** | `../rest/dispatcher-deferred-dependencies.md` 新增条目（R09） |
| 7 | 可视化面（`/scene_graph/vis` 等）、`CountingSceneGraph`、prompt/LLM 编排面 | §2-⑥ 无调用方/调试残留 | **不迁，删除** | 见 §6 |
| 8 | 在线建图链（`expandSkeleton` 全套、`initSceneGraph`/`updateSceneGraph`、`cloud_fov_limit`） | §2-⑥ 迁入后无调用方且能力已失效；在线 builder 另有归属 | **不迁** | §6 + 台账登记触发条件 |
| 9 | `SpectralCluster` | §2-⑥ 被 `AreaHandler` 的 Leiden/CPM 取代 | **不迁** | §6 |

> 裁决 6 是本轮唯一需要用户/契约确认的开放项（`l3-migration-protocol` §2「裁决不明时补契约，
> 不得凭当轮执行者的判断默认放行」）。两个候选见 §4.4「对象导航下行的替代形态」。

### 4.2 目标目录树与文件职责

**A. C++ 共享几何能力包**

```
l3-dispatcher-planner/ros_packages/scene_graph/
  CMakeLists.txt                     # 三个 target：scene_graph_core(STATIC,无ROS) /
                                     #   scene_graph(ROS外壳) / scene_graph_py(pybind11)
  package.xml
  include/scene_graph_core/          # 领域核心：零 ROS 类型（ros-adapter-boundary X4/R2）
    scene_graph_data.hpp             # Vertex/Facet/Polyhedron/PolyhedronFrontier/Edge/
                                     #   PolyhedronCluster/ObjectNode（原 data_structure.h，去 ROS）
    skeleton_astar.hpp               # 拓扑图 A*（无 ROS）
    skeleton_cluster.hpp             # AreaHandler：Leiden/CPM 区域聚类（无 ROS）
    scene_graph_graph.hpp            # 图容器：拓扑/边界/对象三层 + 区域挂载（原 scene_graph.h 去 ROS 部分）
    scene_graph_map_io.hpp           # 只读：manifest/scene_graph.json → 内存图
    object_layer.hpp                 # 对象层：OBB/位置/标签/父多面体（在线检测不迁）
    ikd_Tree.hpp                     # 增量 KD 树（纯 C++，原样迁入）
  src/                               # 与上面同名 .cpp
  libs/quickhull/                    # 凸包 vendor（原样迁入，不动）
  libs/libleidenalg/                 # 社区发现 vendor（原样迁入，不动）
  include/scene_graph/               # ROS 外壳头（端口面 + 适配面）
    scene_graph_ports.hpp            # 端口声明：能力面 = 绑定面（X1）
    scene_graph_ros.hpp              # ROS 适配：srv 宿主 + 话题
  src/scene_graph_ros.cpp            # 适配实现（R1 收发集中 / R4 出站经端口 / R5 无决策）
  src/scene_graph_bridge_node.cpp    # 桥节点（srv 名不变；集合按 §6 裁剪）
  pybind/scene_graph_py.cpp          # pybind11：Eigen↔numpy、整块进出（X2/X3）
  msg/ srv/                          # 只保留实际使用项（见 §6）
  test/                              # 纯 C++ 单测（门禁 G12 要求）
```

**B. dispatcher 侧**

```
l3-dispatcher-planner/ros_packages/dispatcher/dispatcher/
  perception/
    __init__.py                      # 一行定义 + 契约归属（l3-package-layout §4）
    scene_graph_projection.py        # canonical 目录 → 最小投影 {objects:[{id,label,pos}]}
                                     #   + mtime 缓存（原 graph_source.py 去 rospy）
    scene_graph_model.py             # 纯 Python 图数据模型（快照字段、对象、区域）
  tools/scene_nav/
    __init__.py                          # 不导出家族（l3-package-layout §4）
    catalog.py                           # 7 项 ToolSpec（家族基础设施，无家族前缀）
    scene_nav_ports.py                   # 家族专属宿主端口 + SceneNavConfig（@dataclass，字段名=键名）
    scene_nav_map_search_skill.py        # SceneNavMapSearchSkill（异步，入队）
    scene_nav_navigate_skill.py          # SceneNavNavigateSkill（object_id_nav，异步）
    scene_nav_graph_list_skill.py        # SceneNavGraphListSkill（同步）
    scene_nav_graph_select_skill.py      # SceneNavGraphSelectSkill（同步）
    scene_nav_graph_save_skill.py        # SceneNavGraphSaveSkill（同步）
    scene_nav_graph_objects_skill.py     # SceneNavGraphObjectsSkill（同步）
    scene_nav_graph_object_pose_skill.py # SceneNavGraphObjectPoseSkill（同步）
    scene_nav_config.py                  # 图相关常量（原 config.py；常量非参数）
    scene_nav_chain_log.py               # 链日志/图快照落盘（原 chain_log.py，改 slog）
  ros_adapter/
    scene_graph_ros.py               # 订阅 /scene_graph/json_text、/planner/fsm_state；
                                     #   实现 scene_graph_ports 端口；写共享状态（S1 单一写入方）
```

**C. specs**

```
specs/proposed/inner/l3-scenegraph.spec.md        # 新增叶契约（P0）
specs/implemented/inner/l3-package-layout.spec.md # 补 §1 家族行 / §3 依赖行（P0）
specs/implemented/inner/l3-execution-seam.spec.md # 补 §3 能力端口（P0）
specs/implemented/inner/l3-tool-plane.spec.md     # 补 §1 工具集合与 revision（P2）
specs/implemented/inner/l3-skill-contract.spec.md # 补 scene_nav 身份/端口（若偏离 §7 通用集）
```

### 4.3 命名规范表

| 类型 | 规范 | 本轮取值 | 依据 |
|------|------|----------|------|
| C++ 头/源 | snake_case | `scene_graph_core/*.hpp`、`scene_graph/*.hpp` | `l3-coding-style` §4 |
| C++ 类型 | PascalCase | `Polyhedron`、`PolyhedronFrontier`、`SkeletonAstar` | `l3-coding-style` §1.1 |
| C++ 方法 | camelCase 动词开头；accessor `get`/`is`/`set` | `getPathToObject()`、`isGraphReady()` | `l3-coding-style` §1.2 |
| C++ 成员 | 尾下划线，单位进 Doxygen | `polyhedron_map_`、`local_box_max_` | `l3-coding-style` §1.3/§1.4/§3 |
| C++ 常量 | `k` + PascalCase | `kFrontierCreationThreshold` | `l3-coding-style` §1.5 |
| 允许缩写 | 白名单 | `topo`/`poly`/`skeleton`/`object_id_nav`/`sg_`/`map_`/`vis_` | `l3-coding-style` §1.6（已含场景图术语） |
| Python 家族模块 | 家族前缀（`__init__` 除外） | `scene_nav_navigate_skill.py` | `l3-package-layout` §2 |
| Python 家族基础设施模块 | 领域名词，不带家族前缀 | `catalog.py`、`scene_nav_ports.py` | `l3-package-layout` §2 |
| Python 技能类 | 一技能一 `name`、一文件一类 | `SceneNavNavigateSkill.name = "scene.navigate"` | `l3-skill-contract` §2、`execution/composition.py` 的 `register(skill.name, skill)` |
| Python 类 | PascalCase，不重复平面名 | `SceneNavMapSearchSkill` | `l3-package-layout` §2 |
| Python 函数 | snake_case 动词开头 | `project_scene_graph()` | `l3-package-layout` §2 |
| ROS 适配文件 | `*_ros.py` / `Ros<职责>` | `scene_graph_ros.py` | `l3-ros-adapter-boundary` §2 |
| 工具名 | 与调用侧一致，无任务编号 | `scene.map_search`、`scene.navigate`、`scene_nav.graph.list` … | `l3-tool-plane` §2、`l3-core-boundary` B7 |

> 命名权威只有一处：`l3-package-layout` §2（源自 `design-dispatcher-package-layout-and-naming-unification.md`
> §4.2，经其 §12/§13 两轮用户裁决修正）。**不存在「vla 单独一套方案」**；现有两家族实践不一致：
> `tools/vla/` 的 `vla_skill.py`/`vla_geometry.py` 符合家族前缀，`tools/flight/` 的
> `takeoff_skill.py`/`motion.py`/`session.py` 均无 `flight_` 前缀。
> 本轮已在 P0 给 §2 补「家族基础设施模块」一行（使 `catalog.py`/`ports.py` 合法），
> scene_nav 家族按契约取值；**flight 家族的偏差登记为待办，本轮不顺手改**（`l3-migration-protocol`
> §5：实现未跟上契约时修实现，不得改契约迁就现状）。

### 4.4 接口形态

**能力端口（`scene_graph_ports.hpp`，即 pybind 绑定面，X1）** —— 只暴露能力面，不暴露内部方法：

| 端口 | 输入 | 输出 | 用途 |
|------|------|------|------|
| `loadGraph` | 目录名 [--]、数据根 [--] | 成功与否 [--] | 载入 canonical 图（只读） |
| `isGraphReady` | — | 就绪与否 [--] | 就绪判定（替代旧 `skeleton_gen_->ready()`） |
| `getPathToObject` | 对象 id [--]、当前位置 [m]、偏航 [rad] | 航点序列 [m]、目标位置 [m]、目标偏航 [rad] | 对象导航路径（原 `mountCurPoly` + `getPathToObjectWithId` 合并为一次调用） |
| `getObjectInfo` | 对象 id [--] | 存在与否、位置 [m]、父多面体中心 [m] | 对象三查询（原 `sgObjectInfo` 聚合） |
| `listGraphs` / `selectGraph` | 数据根 [--] / 图名 [--] | 图名列表 + 当前激活名 | 画廊（只读侧） |
| `setTargetKnowledge` | 目标文本、先验知识 | — | 图内对象语义上下文（仅当 l4 决策仍需要；否则删除） |

- 全部为**整块进出**（X2）：一次调用传一个快照/一个航点序列，禁止逐点往返。
- 输入输出使用自有结构（X3），不传 ROS 消息类型。

**对象导航下行的形态（裁决 6，2026-09-20 修订为 A′）**：

先纠正一个前提（§2.2 取证）：**旧链里 planner 从来不知道 `object_id`**。object 级语义
（到达判据、终端偏航、任务 deadline、重规划、终态原因）全部在 mission_executive 的
`object_nav_` 状态机里；planner 只收航点批次。因此「用 A 就处理不了结果」不成立——
真正的问题是 **A 必须把那个状态机一并落到技能里**，否则确实会退化成「只上报航点走完」。

- **A′（采纳）**：`scene.navigate` 技能持有 object 级子状态与终态，按
  `l3-migration-protocol` §2-② 落为技能（不是搬运 mission_executive 代码，是按
  `l3-skill-contract` 重新实现）：
  1. 能力端口只给**几何事实**：骨架路径 [m]、目标位置 [m]、目标偏航 [rad]；
  2. 技能内联**任务塑形**：近点跳过（`waypoint_skip_xy_distance`）、巡航高度统一、限幅、
     偏航模式脉冲（`l3-skill-contract` §5「塑形由调用方技能内联完成」）；
  3. 技能持有**到达判据**（位置 + 终端偏航双条件）与**任务级守卫**（deadline、重规划上限）；
  4. 终态必须回答 object 级问题：哪个对象、到没到、最终位姿与偏航、失败原因；原因词表
     承接旧库语义（`reached` / `unreachable` / `timeout` / `failed`，取消归 `cancelled`）；
  5. 结果经 `stash_task_result` 暂存、壳在终态取走上行；完成语义声明为
     `workflow_result`（`l3-tool-plane` §9），**不是** `action_result`；
  6. 下行经 `l3-execution-seam` §4 的通用动作端口 + `l3-skill-contract` §5 航点下发端口，
     **不引入 `Instruction.msg`、不引入 planner 侧 `object_id_nav` 模式、不新增 planner 接口**。
- **B（不采纳）**：只解析「object_id → 目标位置」交给既有飞行动作能力——丢失沿拓扑骨架飞行
  与终端偏航语义，且无法回答 object 级失败原因。
- **C（不采纳，登记为 planner 侧备选）**：把 object 语义移回 planner（恢复 `object_id_nav`
  模式 + 携带 object 的下行消息）。属运动规划范围（`l3-migration-protocol` §2-⑤），需 planner
  契约先行，且与「object 语义归技能」相冲突，本轮不做。

**旧接口 → 删除**：

| 旧接口 | 处置 |
|--------|------|
| `scene_nav_skill.py` 内 `dispatcher.tools.scene_nav.graph_source` 延迟导入 | 删除；改由 `perception/scene_graph_projection` 经端口提供 |
| `rospy.get_param("/scene_graph/active_name")`、`fsm/scene_graph_load_name` | 删除直读；激活名经端口/共享状态（`l3-ros-adapter-boundary` R3/R5） |
| `INSTRUCTION_TYPE` 的导航取值（`TURN_OBJECT_ID_NAV` 等） | 按裁决 6 删除或保留（P0 定） |
| `CountingSceneGraph`、`sendPrompt`/`*PromptGen`/`handle*Result` | 删除（无调用方） |
| `visualizeSceneGraph`、`/scene_graph/vis`、`/skeleton_vis`、`/skeleton/cluster_vis`、`refreshLoadedMapVisualization` | 删除（无站端消费者） |
| `SpectralCluster` | 删除（被 `AreaHandler` 取代） |
| `map_inflate_sub_`、`_sampling_density`、注释掉的看门狗 | 删除（死成员/死参数/死分支） |
| `INFO_MSG*` 流宏 | 删除；改 `slog` 结构化事件（`observability-log`） |

### 4.5 程序内流转（端到端）

```text
l4 station (cloud)
  │ zenoh RPC  lx/<stack-id>/rpc   {"method","params"}(context=连接身份三元组)
  ▼
tool_plane/control_plane.py ── ToolRegistry.tool_for_name(name)   # 未注册 → tool_not_registered
  │                              ToolIntake 准入（call_id / schema / 租约 owner 门）
  ▼
core/engine.py  六态 FSM: INIT → WAIT_FOR_MISSION → DISPATCH → WAIT_ACTION_FINISH
  │                                                    → POST_ACTION → STOP
  │ DISPATCH 态：SkillRouter.dispatch_plan(skill_command)   按名分发，不做语义分支
  ▼
tools/scene_nav/scene_nav_skill.py :: plan_tick(cmd)
```

**分支 1：`scene.map_search`（取图 + 投影）**

1. 技能经 `scene_nav_ports` 请求 `ros_adapter/scene_graph_ros` 建立 `/scene_graph/json_text`、
   `/planner/fsm_state` 订阅（端点归技能，disposer 登记，`l3-skill-contract` §6）。
2. 技能经端口向 `perception/scene_graph_projection` 取 canonical 图投影
   （数据根下 `<active>/scene_graph.json` → `{objects:[{id,label}]}` + 摘要；mtime 作缓存键）。
3. 投影/摘要经 `stash_task_result` 暂存；壳在终态 `pop_task_result` 取走并上报 `done`
   （`l3-skill-contract` §5 任务结果暂存/取出）。
4. 失败路径 fail-closed：无激活图/文件不可读/JSON 非法 → 上报 `fail`，不静默成功
   （`l3-migration-protocol` §4 禁止假成功）。

**分支 2：`scene.navigate(object_id)`（到对象的航点链，候选 A）**

1. 技能从 `call.arguments` 取 `object_id`（本地不解析/不匹配）。
2. 技能经执行缝能力端口 → `scene_graph_py` → `scene_graph_core::getPathToObject`：
   一次跨语言调用（X2），内部完成「挂载当前多面体 → 拓扑 A* → 终点步到对象位置 →
   中间航点统一到当前巡航高度 → 目标偏航」。
3. 技能内联塑形（高度限幅、偏航模式脉冲），`arm_action(owner=self)` 记账，
   经 `航点下发` 端口 → `ros_adapter/planner_execution_ros.py` → `/planner/local_goal`。
4. 反馈 `/planner/waypoint_progress` → 适配层写共享状态（S1 单一写入方、S2 完整快照、
   S3 带时间戳）→ 技能 `action_done_gate` 裁决完成 → `on_action_result` 返回
   `ADVANCE`（续下一条）或 `IDLE`（收敛完成）。
5. 取消/全局停止：清理技能会话与等待门；旧动作失效；不假报停止
   （`l3-execution-seam` §7、`l3-tool-plane` §5）。

**分支 3：`scene_nav.graph.*`（同步技能，`synchronous=True`）**

1. `l3-skill-contract` §2 同步技能**不入队、不进感知门**，在调用线程内直接完成。
2. `graph.list`/`graph.objects`/`graph.object_pose` → 经 `perception/scene_graph_projection` 读投影。
3. `graph.select` → 经 `scene_graph_ros` 调桥节点（只读侧；executor 只读，写图归 builder）。
4. `graph.save` → **本轮不实现**（builder 独占写）；按裁决登记，不建占位。

**静态依赖方向**（`l3-package-layout` §3 + `l3-ros-adapter-boundary` §1）：

```text
ros_adapter/scene_graph_ros.py ──实现──▶ scene_nav_ports（技能声明）
                                        ▲
tools/scene_nav/scene_nav_skill.py ─────┘  （只经端口，不碰宿主私有属性）
        │ 只 import：本家族、tools/skill_api.py、execution/ports.py
        ▼
execution/（共享执行：航点下发、记账、取消）──▶ ros_adapter/planner_execution_ros.py ──▶ planner
perception/scene_graph_projection.py ── 纯数据面（无 ROS、无技能依赖）
scene_graph_core（C++）── 零 ROS 类型；仅经 pybind 端口被执行缝调用
```

### 4.6 需先补的契约（P0，`l3-migration-protocol` §3 / G18）

1. **新增** `specs/proposed/inner/l3-scenegraph.spec.md`，`Parent: specs/implemented/l3-dispatcher.spec.md`，
   拥有：图数据模型（拓扑/边界/对象三层字段）、只读约束（executor 只读、写归 builder）、
   canonical 目录契约、能力端口清单（§4.4）、失败词表、门禁条目。
2. **`l3-package-layout.spec.md`**：§1 增 `tools/scene_nav/` 家族行与 `perception/` 职责细化；
   §3 依赖表增补 `tools/<family>/` 与 `perception/` 的合法通路（现表未覆盖，属裁决不明，必须补）。
3. **`l3-execution-seam.spec.md`**：§3 增补「场景图能力端口」为执行缝能力端口之一
   （现有 §3 只写「几何、拓扑搜索、走廊与轨迹优化 → C++ 经 pybind」的通用形态）。
4. **`l3-tool-plane.spec.md`**：§1 工具集合增 3 组名 + `revision` 重算；`scene.navigate`
   的完成语义声明为 `workflow_result`，其 `outputSchema` 承载 object 级结果
   （对象身份、到达与否、最终位姿与偏航、失败原因）；§3 裁决 `navigation.scene_graph_nav`
   是否保留为 wire 归一（只作用于名字解析，不产生第二注册面）。
5. **`l3-skill-contract.spec.md`**：增补 `scene_nav` 家族条目——身份三声明、
   **object 级子状态**（目标身份、到达判据、任务级 deadline/重规划上限）、
   终态原因词表、结果暂存端口用法；若家族端口偏离 §7 通用集一并声明。
6. **`../rest/dispatcher-deferred-dependencies.md`**：新增 R09（对象导航下行 + 在线建图链）
   与触发条件、验收、可删除条件；同步 `rest/README.md` 索引与
   `doc/rest/task-id-to-tool-name-deferred.md` 的触发行。

> **起草状态（2026-09-20）**：1–6 已全部落盘——`l3-scenegraph` 为新增 `proposed` 叶；
> `l3-package-layout` 补 §1 家族行/`perception/` 职责、§2 家族基础设施行与**配置参数命名规则**、§3 感知单向流动；
> `l3-execution-seam` 增 §3.1 能力端口登记；`l3-tool-plane` 增目标集合与 G24 限定；
> `l3-skill-contract` 增 §11 家族条目（含 `~scene_nav/*` 参数表）；台账新增 R09 并同步两个索引。
> 参数命名的旧库取证与逐项映射见 §4.8。

### 4.7 旧接口 → 删除（不保留）

见 §4.4 表与 §6 清单。特别声明：**新库不得以任何形式恢复**
`dispatcher.utils.*` / `services.*` / `toolplane.*` / `skills.*` / `rpc.*` 前缀
（`l3-package-layout` §5、G32），也不得为旧调用方保留 `navigation.scene_graph_nav`
以外的兼容入口（`l3-migration-protocol` §4 禁止遗留垫片）。

### 4.8 配置参数命名归一（2026-09-20 追加）

**旧库实测：参数命名没有统一规范**，四处混乱均有证据：

| # | 混乱形态 | 证据 |
|---|----------|------|
| 1 | yaml 分组与键名前缀**双重重复** | `bringup/config/vla/real.yaml` L46-L53：`policy.scene_nav` 组内的键又叫 `scene_nav_json_wait_timeout_s`、`scene_nav_trigger_timeout_s` |
| 2 | 平级连写前缀 vs 嵌套子组**混用** | `bringup/launch/includes/mission_backend.xml` L63-L71：`object_id_nav_replan/enable` 与 `object_id_nav/task_timeout` 并存（应为 `object_id_nav/replan/*` 或统一平级） |
| 3 | 参数存在但被**白名单静默丢弃** | `AGENTS.md` L266-L272 记录：`scene_nav_trigger_timeout_s` 曾因不在 engine defaults 白名单被 `apply_config` 丢掉 |
| 4 | 跨节点**全局参数直读**、无归属声明 | `scene_nav_skill.py` L240 直读 `fsm/scene_graph_load_name`（mission 写的全局参数）；`graph_source.py` L40 直读 `/scene_graph/active_name` |

**新库规则**（已落 `l3-package-layout` §2）：参数键形如 `~<前缀>/<子组?>/<键名>`，
**前缀 = 消费它的家族/平面目录名**；仅跨家族参数才用流程名或顶层键；键名不重复前缀；
子组用嵌套；每组声明唯一权威；参数名是行为契约（`l3-coding-style` §6、R6），
改名须登记有意变更；装载不得经白名单静默丢弃。

**本轮的逐项映射**（全表见 `l3-skill-contract` §11；全部登记为**有意变更**）：

| 旧键（宿主） | 新键（宿主） |
|---|---|
| `object_id_nav/waypoint_skip_xy_distance`（mission 私有） | `~scene_nav/waypoint_skip_xy_distance_m`（dispatcher 私有） |
| `object_id_nav/task_timeout`、`task_terminal_timeout`、`task_max_replans` | `~scene_nav/task_timeout_s`、`task_terminal_timeout_s`、`task_max_replans` |
| `object_id_nav/require_final_yaw`、`final_yaw_tolerance_deg`、`final_approach_max_attempts` | 同名键，前缀改 `~scene_nav/` |
| `object_id_nav_replan/enable`、`stuck_yaw_rate_thresh`、`mode2_stuck_fallback_delay` | `~scene_nav/replan/enable`、`stuck_yaw_rate_threshold_rad_s`、`mode2_stuck_fallback_delay_s` |
| `policy.scene_nav/{scene_nav_json_wait_timeout_s,scene_nav_trigger_timeout_s}` | `~scene_nav/{json_wait_timeout_s,trigger_timeout_s}` |
| `policy.scene_nav/{scene_graph_json_topic,planner_fsm_state_topic}` | `~scene_nav/{graph_json_topic,planner_fsm_state_topic}` |
| `fsm/scene_graph_load_name`、`/scene_graph/active_name`（全局） | **删除**：激活图名经端口/共享状态（R3/R5），技能不直读全局参数 |

归一规则（已落 `l3-package-layout` §2）：前缀 = 消费它的家族名；键名不重复前缀；
子组嵌套（`replan/*`，非平级连写 `scene_nav_replan/*`）；**带单位后缀**
（`_m`/`_s`/`_deg`/`_rad_s`，无量纲计数与开关不加）；缩写写全
（`thresh`→`threshold`、`dis`→`distance`）。承载为 `SceneNavConfig`
（`@dataclass(frozen=True)`，`tools/scene_nav/scene_nav_ports.py`）单类，
字段名即键名，装配层 `fields()` 批量派生，不留裸关键字参数。

**兼容处置**：该组参数在新库尚未存在，部署配置（`bringup/config/*.yaml`）由 P2 首次写入，
无既有部署依赖需要兼容；旧库 mission 侧同名参数随 mission_executive 禁迁一并消失。

## 5. 迁移映射表

| 旧路径/命名（`OLD/`） | 新路径/命名（`NEW/`） | 动作 | 备注 |
|---|---|---|---|
| `scene_graph/include/scene_graph/data_structure.h` | `scene_graph/include/scene_graph_core/scene_graph_data.hpp` | rewrite | 去 ROS：删 `ros/ros.h`/`EncodeMask.h`，`ros::Time`→`double` epoch 秒，删 `blocked_stamp_` |
| `scene_graph/src/skeleton_astar.cpp` | `scene_graph/src/skeleton_astar.cpp` | rename | 去 ROS（`ros::Time`→double） |
| `scene_graph/src/skeleton_cluster.cpp` | `scene_graph/src/skeleton_cluster.cpp` | rewrite | 删 `SpectralCluster`，保留 `AreaHandler` |
| `scene_graph/src/scene_graph_map_io.cpp` | `scene_graph/src/scene_graph_map_io.cpp` | rewrite | 只保留 load/画廊；删 save（builder 独占写） |
| `scene_graph/src/object_factory.cpp` | `scene_graph/src/object_layer.cpp` | rewrite | 只保留图内对象数据结构与融合读；删在线检测线程与 ROS 订阅 |
| `scene_graph/src/scene_graph.cpp` | `scene_graph/src/scene_graph_graph.cpp` | rewrite | 只保留 `loadMap`/`getPathToObject`/`mountCurPoly` 等价能力；删 `initSceneGraph`/`updateSceneGraph`/可视化/prompt |
| `scene_graph/src/skeleton_generation.cpp` | — | **delete** | 在线建图链不迁（§4.1 裁决 8） |
| `scene_graph/src/cloud_fov_limit.cpp` | — | **delete** | 建图专用 FOV 裁剪，无消费者 |
| `scene_graph/src/counting_scene_graph.cpp` | — | **delete** | 无调用方 |
| `scene_graph/src/scene_graph_bridge_node.cpp` | `scene_graph/src/scene_graph_bridge_node.cpp` | rename | srv 名不变；集合按 §6 裁剪 |
| `scene_graph/libs/quickhull/`、`libs/libleidenalg/`、`ikd_Tree.*` | 同名 | 原样 | vendor / 纯 C++ |
| `dispatcher/tools/scene_nav/scene_nav_skill.py`（`scene.map_search` 部分） | `dispatcher/tools/scene_nav/scene_nav_map_search_skill.py` | split+rewrite | 一名一技能；去 `rospy` 直读、去 `graph_source` 延迟导入；端口化 |
| `dispatcher/tools/scene_nav/scene_nav_skill.py`（`scene.navigate` 部分） | `dispatcher/tools/scene_nav/scene_nav_navigate_skill.py` | split+rewrite | 一名一技能；object 级子状态与终态随迁（§4.4 A′） |
| `dispatcher/tools/scene_nav/graph_skill.py` | `dispatcher/tools/scene_nav/scene_nav_graph_{list,select,save,objects,object_pose}_skill.py` | split+rename | 一名一技能（5 项）；均 `synchronous=True` |
| `dispatcher/tools/scene_nav/graph_source.py` | `dispatcher/perception/scene_graph_projection.py` | rewrite | 去 `rospy.get_param` 直读，改端口/共享状态 |
| `dispatcher/tools/scene_nav/graph.py` | `dispatcher/perception/scene_graph_model.py` | rewrite | 纯数据模型，无 ROS |
| `dispatcher/tools/scene_nav/config.py` | `dispatcher/tools/scene_nav/scene_nav_config.py` | rewrite | 只保留图相关取值（导航取值按裁决 6） |
| `dispatcher/tools/scene_nav/chain_log.py` | `dispatcher/tools/scene_nav/scene_nav_chain_log.py` | rewrite | 改 `slog` 结构化事件（`observability-log`） |
| `mission_executive/src/handlers/mission_core_object_nav.cpp`、`handlers/object_nav.py` | — | **不迁** | `l3-execution-seam` §1/G10；登记 R09 |

## 6. 删除清单

| 删除项 | 理由 |
|--------|------|
| `expandSkeleton`/`initNewPolyhedron`/`generateFrontiers`/`verifyFrontier`/`adjustFrontier`/`processAValidFrontier`/`findNewTopoConnection`/`findLoopbackConnectionFromCandidate`/`checkConnectivityBetweenPolyhedrons`/`rayCast`/`searchPathInRawMap`/`generatePolyVertices`/`insertPolyhedronAt`/`registerLoadedPolyhedron` | 在线建图链：旧库已失 `map_interface` 依赖，迁入不可用；在线 builder 另有归属（§2.2、§4.1-8） |
| `SceneGraph::initSceneGraph` / `updateSceneGraph` / `visualizeSceneGraph` / `refreshLoadedMapVisualization` / `updateObjectToSceneGraph` 的区域预测标记段 | 无调用方 / 可视化无站端消费者 |
| `CountingSceneGraph`（`counting_scene_graph.h/.cpp`、`/counting_scene_graph/json_text`） | 无调用方（§2-⑥） |
| `SceneGraph::sendPrompt` / `allRoomPredictionPromptGen` / `singleRoomPredictionPromptGen` / `newAreaPredictionPromptGen` / `chooseAreaToGoPromptGen` / `chooseTerminateObjIdPromptGen` / `DFDemoPromptGen` / `vlaSearchPromptGen` / `handle*Result` / `parseVlaSearchPromptResult` | VLA/LLM 编排面已由 `navigation.vla_nav` 与站端接管，无调用方 |
| `SpectralCluster`（`calSimilarityMatrix`/`calDegreeMatrix`/`calLaplacianMatrix`/`calLaplacianEigen`/`kmeans`） | 被 `AreaHandler` 的 Leiden/CPM 取代 |
| `skeleton_generation.h` 的 `INFO_MSG*` 宏、`visualize*` 全套、`drawFacets`/`drawPoints` | 日志面改 `slog`；可视化无消费者 |
| `map_inflate_sub_`、`_sampling_density`、注释掉的耗时看门狗、`_MAP_TYPE_*` 宏分支 | 死成员/死参数/死分支（§2-⑥） |
| `EncodeMask.msg`（若无 `object_factory` 在线检测） | 对象在线检测不迁 |
| `PromptMsg.msg`、`WordVector.msg`、`VLASearchObservation.msg` | prompt/LLM 面不迁 |
| `SgVisTick.srv`、`SgVisPath.srv` | 可视化面：`vis_*` 无消费者 |
| `SgSetTargetKnowledge.srv` | 随 prompt 面裁；仅当 l4 决策仍需语义上下文时保留并在 §4.4 端口表登记 |
| `instruction_type` 导航常量、`Instruction.msg` 引用 | 裁决 6 |

## 7. 实施步骤

> 每期：范围 + 行为不变式 + 验收 + 回退。分期之间不并行，P0 未完成不动代码。

### P0 — 契约先行与台账登记

- 范围：§4.6 的 6 项契约/台账改动；确认裁决 6 的候选 A/B。
- 行为不变式：零代码改动；`l3-tool-plane` §1 集合与 `revision` 在本期**不变**（能力未注册）。
- 验收：G18（目标契约 `proposed` 及以上）满足；`l3-package-layout` §3 依赖表已覆盖新通路；
  台账新增 R09 并同步两个索引。
- 回退：`git checkout` 还原文档。

### P1 — C++ 共享几何能力迁入

- 范围：`ros_packages/scene_graph/` 建包；`scene_graph_core`（无 ROS）+ ROS 外壳 + `pybind`；
  迁 `data_structure`/`skeleton_astar`/`skeleton_cluster`/`scene_graph_map_io`(读)/`object_layer`/vendor；
  `test/` 纯 C++ 单测（G12）。
- 行为不变式：canonical 目录布局、`manifest.json`/`scene_graph.json` 字段名与
  `format_version: 1` 字节级不变（`l3-coding-style` §6）；srv 名不变（按 §6 裁剪的除外，
  属有意变更须登记）。
- 验收：`make compile` 干净；`ros_packages/` 无 `mission_executive`（G10）；
  领域层零 `ros::`/`*_msgs`（G7/G8）；每个 pybind 端口有纯 C++ 单测（G12）。
- 回退：删除新包；不影响 dispatcher。

### P2 — dispatcher 侧技能家族与数据面

- 范围：`perception/`（投影 + 模型）、`tools/scene_nav/`（3 组技能 + catalog）、
  `ros_adapter/scene_graph_ros.py`、`tool_plane/registry.py::default()` 汇入
  `scene_nav_specs()`、`l3-tool-plane` §1 集合与 `revision` 更新。
- 行为不变式：`navigation.vla_nav` 与六个 `basic_flight.*` 元数据字节级不变
  （`revision` 仅因新增工具而变）；`scene.map_search` 的投影输出与旧库
  `graph_source.scene_model_json()` 的 `{objects:[{id,label}]}` 形态一致。
- 验收：G13–G17（技能声明/disposer/无互调）、G29–G32（平面集合与依赖方向）、
  G24（发现面集合与 `revision` 一致）；`dispatcher.tools.scene_nav.*` 悬空引用零命中。
- 回退：反注册 `scene_nav_specs()` 并还原 `revision`。

### P3 — 端到端接线与台账关门

- 范围：`scene.navigate` 按候选 A 接航点端口；`scene_nav.graph.*` 接桥节点 srv；
  链日志改 `slog`；R09 按实际结果更新。
- 行为不变式：`l3-skill-contract` §10 同款的 fail-closed 语义（无 object_id / 图未就绪 →
  明确失败原因，不静默回落）；终态唯一（G28）。
- 验收：静态验收（引用闭包无未解析符号、删除项零残留）+ 运行时验收（链路可达时端到端）；
  若不可运行，在本文显式登记「本轮结束时不可运行」与恢复轮次（`l3-migration-protocol` §6）。
- 回退：`scene.navigate` 退回 P2 的「只注册 map_search + graph.*」状态。

## 8. 验收标准

> **统一声明**：除非使用者明确许可，否则跳过验收测试工作（`AGENTS.md` 硬性约束 §9）。

- [ ] G18：`specs/proposed/inner/l3-scenegraph.spec.md` 存在且 `Status: proposed`；
      `l3-package-layout`/`l3-execution-seam`/`l3-tool-plane` 已按 §4.6 更新。
- [ ] G19：迁入的每个符号都有活调用方；无调用方项已在 §6 删除或在台账登记。
- [ ] G20：旧实现已删除，无转接口、无注释桩（`expandSkeleton` 全套、`CountingSceneGraph`、
      `SpectralCluster`、`INFO_MSG*` 在 `NEW/` 零命中）。
- [ ] G21：行为契约字符串级 diff——topic/param/srv 名、消息字段名、slog 事件名，
      除本文登记的有意变更外保持一致。
- [ ] G22：不存在「未注册即静默成功」路径（图未就绪、对象不存在、无 object_id 均上报失败）。
- [ ] G23：零任务编号标识符；`INSTRUCTION_TYPE` 导航常量未出现在 `NEW/`。
- [ ] G24：发现面集合 == 契约 §1 集合，`revision` == 契约记录值。
- [ ] G29–G32：`dispatcher/` 子包集合恰为七平面；依赖方向禁列零命中；`__init__` 自述齐全；
      退役前缀零命中。
- [ ] G7–G9、G12：领域层零 ROS 类型；端口有适配实现；pybind 端口有纯 C++ 单测。
- [ ] `dispatcher.tools.scene_nav` 悬空引用零命中（含 tests 的字符串 patch）。

## 9. 风险与对策

| 风险 | 影响 | 对策 |
|------|------|------|
| 裁决 6 未确认（对象导航下行归属） | `scene.navigate` 无合法下游，强行实现即造转接器/占位 | P0 明确候选 A/B；未确认前只登记不实现（§2-⑦） |
| `perception/` 平面无行为契约、依赖表未覆盖与 tools/execution 的通路 | 新文件一落地即违 G30 或成第二权威 | P0 先补 `l3-package-layout` §1/§3，再动代码 |
| 旧库 `rayCast`/`searchPathInRawMap` 已退化，误当作可用能力迁入 | 迁入后静默产出无约束骨架与假路径 | 本轮**不迁**该链；台账登记触发条件（恢复需先接回 map_interface 并补契约） |
| `ros_packages/` 包级布局无归属契约 | 新包位置无据可依，后续再迁 | P0 在 `l3-scenegraph` 契约中固定包位置与 target 划分 |
| canonical 目录 hostPath 归属漂移 | 图读不到 | P0 在契约中声明数据根与 `L3_SCENE_GRAPH_DIR` 的等价关系，并与 drone-host 侧 hostPath 契约对齐 |
| 「旧图 `format_version: 1`」与「spec 的 v3 快照」两套格式混淆 | 读写错格式 | 契约明确：executor 只读 `scene_graph.json`（`format_version: 1`）；v3 快照归 builder，本轮不消费 |
| 图编辑工具与「builder 独占写」冲突 | 双写/双权威 | `graph.save` 不实现；`graph.select` 只调 load；契约写明只读边界 |
| 悬空引用与测试字符串 patch 反复 | 基线噪声掩盖真实缺口 | P2 收口时统一清理并在台账留证 |
| 参数前缀归一被当作纯改名而漏登记 | 部署配置与运维手册不一致、G21 判负 | §4.8 全表登记为有意变更；`l3-skill-contract` §11 参数表为唯一权威；P2 首次写入部署配置 |
| 参数装载沿用「白名单静默丢弃」旧习 | 参数存在但读不到（旧库已发生过） | `l3-package-layout` §2 明确：缺失或未声明即显式失败或留痕 |
| flight/vla 现有参数字段名单位后缀不一致（`safe_dis_radius_m` 有、`behind_dist`/`state_timeout` 无） | 新家族照抄会延续不一致 | 规则已入 `l3-package-layout` §2；既有字段名属行为契约，登记为待办，不顺手改 |
| `VlaHostConfig` 的 `publish_planner_mode`（回调）与配置同处一表 | 参数面混入非配置项 | 装配层已显式排除（`dispatcher_node.py` L178）；scene_nav 家族不设此类字段 |

## 10. 修改点清单汇总

| 文件 | 动作 | 说明 |
|------|------|------|
| `specs/proposed/inner/l3-scenegraph.spec.md` | create | 新叶契约：图模型、只读边界、能力端口、失败词表、门禁 |
| `specs/implemented/inner/l3-package-layout.spec.md` | edit | §1 家族行 + `perception/` 职责；§3 依赖通路 |
| `specs/implemented/inner/l3-execution-seam.spec.md` | edit | §3 增补场景图能力端口 |
| `specs/implemented/inner/l3-tool-plane.spec.md` | edit | §1 工具集合 + `revision`；§3 wire 归一裁决 |
| `specs/implemented/inner/l3-skill-contract.spec.md` | edit | `scene_nav` 身份/端口（若偏离 §7） |
| `doc/l3-dispatcher-planner/rest/dispatcher-deferred-dependencies.md` | edit | 新增 R09（对象导航下行、在线建图链） |
| `doc/l3-dispatcher-planner/rest/README.md` | edit | 索引增 R09 行 |
| `doc/rest/task-id-to-tool-name-deferred.md` | edit | 更新 `navigation.scene_graph_nav` 处置行 |
| `ros_packages/scene_graph/**` | create | C++ 包：`scene_graph_core` + ROS 外壳 + pybind + test |
| `dispatcher/perception/{__init__,scene_graph_projection,scene_graph_model}.py` | create | 图投影与纯数据模型 |
| `dispatcher/tools/scene_nav/{__init__,catalog,scene_nav_ports,scene_nav_config,scene_nav_chain_log}.py` + 7 个 `scene_nav_*_skill.py` | create | 技能家族（一名一技能） |
| `dispatcher/ros_adapter/scene_graph_ros.py` | create | 订阅/服务调用/共享状态写入 |
| `dispatcher/tool_plane/registry.py` | edit | `default()` 汇入 `scene_nav_specs()` |
| `ros_packages/utils/quadrotor_msgs/msg/` | 不动 | 不新增 `Instruction.msg`（裁决 6） |
| `ros_packages/planner/**` | 不动 | 不新增 `object_id_nav` 模式（裁决 6） |

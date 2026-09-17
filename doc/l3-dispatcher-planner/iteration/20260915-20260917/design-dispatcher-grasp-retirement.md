# dispatcher grasp 退役登记方案（不迁移）

> 摘要：评估旧库（DiffAgent2 旧版）GRASP 抓取感知是否迁移到本库并回答「grasp 是否与 vla、scene_nav 平级」的质疑。结论：**grasp 从来不是注册工具，也不是与 vla/scene_nav 平级的 skill，仅是旧库 engine 持有的 latent 感知子工作流**；按 `l3-migration-protocol` §2-⑥（无调用方或调试残留 → 不迁移）判定为**不迁移，仅登记为删除项**。本方案只产出文档（方案 + rest 台账登记），不修改任何代码。

## 0. 元信息

| 项 | 值 |
|----|----|
| 日期 | 2026-09-16 |
| 目标路径 | `doc/l3-dispatcher-planner/iteration/`、`doc/l3-dispatcher-planner/rest/`（文档级交付，不涉及生产代码） |
| 状态 | proposed（本方案即 P0 交付物；用户确认后视为 done） |
| 关联文档 | 判据：`specs/implemented/inner/l3-migration-protocol.spec.md`、`specs/implemented/inner/l3-tool-plane.spec.md`、`specs/implemented/inner/l3-skill-contract.spec.md`；姊妹篇：`iteration/design-dispatcher-unmigrated-chain-removal.md`；台账：`rest/dispatcher-deferred-dependencies.md`、`rest/README.md` |

## 1. 背景与动机

用户要求评估旧库 grasp 功能是否迁移到本库，并质疑两点：grasp 是否适合继续放在 `tools/` 下？它是否真的是与 vla、scene_nav 平级的 tool？

用户决策（选择器确认）：**不迁移，仅登记为删除项**；发现面**暂时不新增 grasp**，留在文档中作为删除项。

用户硬性约束：**先出文档，不得直接修改代码**。因此本方案只做两件事：① 落盘本方案文档；② 在 `rest/` 台账补一条 grasp 条目并同步索引。不新增代码、不动生产发现面、不改 spec、不动测试。

## 2. 现状事实（问题清单）

> 标记：`N/` = 新版 `l3-dispatcher-planner/`；`O/` = 旧版 `drone_projects/l3-dispatcher-planner/`（快照提交 `1b5fef5`）。

### A. 旧库 grasp 的形态：engine 持有的 latent 感知子工作流，不是工具

- [ ] `O/tools/grasp/workflow.py:3-10` — docstring 自证：“The task queue currently has no in-repo producer (latent vendored workflow)”。
- [ ] `O/tools/grasp/workflow.py:27-34` — `GraspWorker.__init__(engine)` 持有 `self._eng`、私有 `_geometry = GeometryService(engine)`、`_grasp_queue = queue.Queue(maxsize=1)`。
- [ ] `O/tools/grasp/__init__.py:1` — 仅一行模块 docstring，无任何注册逻辑。
- [ ] `O/engine.py:292-293` — engine 持 `grasp_task_timeout_s`（默认 45.0）与 `self._grasp_wf = GraspWorker(self)`。
- [ ] `O/engine.py:2138-2139` — `start_dispatcher_workers` 以 daemon 线程启动 `node._grasp_wf.run`。
- [ ] `O/engine.py:395-396` — `grasp_result_image_pub` 发布 `/agent/grasp_result_image`（CompressedImage，queue_size=2）。
- [ ] `O/zenoh_rpc.py:37-38, 91-93` — `_GRASP_IMAGE_MAX = 128`；`_grasp_images`/`_grasp_results`/`_grasp_lock` 图像与结果 latch。
- [ ] `O/zenoh_rpc.py:122, 170` — `queryable_suffixes()` 含 `grasp_result/*` 并注册 `_on_grasp_result`。
- [ ] `O/zenoh_rpc.py:330-332, 475-501, 590-612, 626-632` — 订阅 `/agent/grasp_result_image`、`_on_grasp_result`/`_on_grasp_result_image`、`grasp_image`/`grasp_result` 访问器。
- [ ] `O/engine.py:1113, 1120` — `_is_aggregated_task_id()` 把 `TASK_ID.GRASP` 并入 task-phase 聚合上报。

### B. grasp 不是工具、不是 skill：注册面与技能契约点全部缺失

- [ ] `O/tools/config.py:23-25` — 旧库自己的注释：“GRASP / LOOK_AROUND 机制仍在引擎中，但 registry 未放行（spec-gated）”，且 `GRASP = 11`。
- [ ] `O/tools/registry.py:248-261` — `ToolRegistry.default()` = `_specs()` 返回 **14 个 ToolSpec**（vla_reach、map_search、navigate、飞行六项、scene_nav.graph 五项），**无 grasp**；`list_tools()` 只出自该注册面。
- [ ] `O/tools/registry.py:263-271` — `tool_for_name()` 未命中抛 `ToolProtocolError(METHOD_NOT_FOUND, …, {"reason": "tool_not_registered"})`。
- [ ] `O/engine.py:324-337` — 技能注册表 `_skills` 只含 `SceneNavSkill`、`VlaSkill`、`FlightSkill` 等实例；`O/engine.py:949/982/997-1003` 按 `call.name` 查 `_skills` 分发、逐 hook 通知。
- [ ] 旧库兄弟技能均有完整技能身份三声明：
  - `O/tools/vla/vla_skill.py:82-87` — `class VlaSkill(SkillBase)`，`name = "vla"`，`requires_perception = True`，`synchronous = False`。
  - `O/tools/flight/flight_skill.py:41-46` — `name = "flight"`，`requires_perception = False`，`synchronous = False`。
  - `O/tools/scene_nav/scene_nav_skill.py:53-58` — `name = "scene_nav"`，`requires_perception = False`，`synchronous = False`。
  - `O/tools/scene_nav/graph_skill.py:29-34` — `name = "scene_graph_edit"`，`synchronous = True`。
- [ ] **grasp 无上述任何契约点**：不继承 `SkillBase`、无 `name/requires_perception/synchronous` 三声明、不进 `_skills`、无 `ToolSpec`、不被 executor 分发。
- [ ] 旧库 spec 仲裁：`O/specs/archived/agent-station-tools.spec.md:177-179` — “Resource reads do not register GRASP as an executable tool”；`O/specs/archived/agent-station-tools.spec.md:495-497` — “A reserved label such as GRASP (11) remains non-executable… The station must not invent a tool or fall back to VLA to execute it”。
- [ ] 旧库 spec 站读模型：`O/specs/implemented/inner/agent-station-channels.spec.md:543-596`（§3.10）— GRASP 是 reserved station plan/history label；`:581-583` 浏览器 MUST NOT 直连 `/api/v1/grasp_result/...`。
- [ ] 旧库另一个 spec 自认实现缺失：`O/specs/implemented/inner/flight-result-metrics.spec.md:62` — `grasp_trigger` 事件“缺失，P0 核心工程”。

### C. 旧库 grasp 静态不可运行 + 任务队列零生产者

- [ ] `O/tools/grasp/workflow.py:14-21` — 仅 import `queue/threading/time/rospy/ToolCall/GeometryService`；正文使用 `cv2`（`:182/:194/:204`）、`np`（`:399-400`）、`CompressedImage`（`:209`）、`MISSION_TYPE`（`:342`）均**未导入** → 一旦执行即 NameError。
- [ ] `O/tools/grasp/workflow.py:57` — `target=self._eng._handle_grasp_task`；`O/engine.py` 全文件 grasp 命中仅 9 处（`:79/:292/:293/:395/:396/:1113/:1120/:2138/:2139`），**无该方法** → 投递即 AttributeError。
- [ ] `O/tools/grasp/workflow.py:132-140` — `self._eng._latest_prompt_frame`、`self._eng._serve_search`；`_serve_search` 唯一定义在 `O/tools/vla/vla_skill.py:622`（VlaSkill 类内）→ engine 上不存在。
- [ ] `O/tools/grasp/workflow.py:159/348/354` — `self._eng._compute_grasp_geometry`、`_grasp_waypoint_body`、`_compare_grasp_geometry_sources` 三个方法实际都定义在 `GraspWorker` 自身（`:320/:394/:368`）→ **方法归属错位**，经 `self._eng.*` 调用全部落空。
- [ ] 旧库全仓 `_grasp_queue.put` **0 命中** → grasp 任务队列零生产者，与 docstring 自述 “no in-repo producer” 吻合。
- [ ] 站端无生效消费者：`O/station_projects/l4-agent/src/copaw/app/routers/flight.py:188-204` — `/grasp-result/...` 与 `/image` 恒 `raise HTTPException(404)`；`O/station_projects/l4-agent/console/src/pages/Chat/ExecutionPlanCard/index.tsx:804` — `const graspImageUrl = null;` 硬编码空；保留的仅是无读模型的前端类型与文案（`console/src/api/types/flight.ts:31-36`、`console/src/locales/zh.json:492/575-577`）。

### D. 新版现状：grasp 零残留，已随删除轮物理删除

- [ ] `N/tools/` 仅 7 个基础设施文件（`__init__.py`、`executor.py`、`model.py`、`protocol.py`、`registry.py`、`runtime.py`、`skill_api.py`），**无任何技能子包**。
- [ ] `N/specs/implemented/inner/l3-tool-plane.spec.md:27-28` — “当前生产工具集合为空”；`:30` — 现行 `revision` 记录值 `sha256:4f53cda1…`.
- [ ] `N/tests/tool-registry/test_rpc_plane.py:81-85` — 空发现面 revision 与 spec 记录值一致并被测试锚定。
- [ ] `N/iteration/design-dispatcher-unmigrated-chain-removal.md:108` — 已删资源主题 `grasp_result/*`、ROS 反馈 `/agent/grasp_result_image`；`:80` — “生产工具、缺失任务注入入口、场景/抓取/记录状态标识零残留”。
- [ ] 新版 `l3-dispatcher-planner/` 全树与 `specs/` 全树 grep “grasp”（忽略大小写）**0 命中** → 已物理删除、无任何残留。
- [ ] `N/rest/dispatcher-deferred-dependencies.md` — R01–R07 均不含 grasp，「本轮明确删除，不自动恢复的内容」表也未登记 grasp → **本次补登记**。

## 3. 目标与约束

- **目标**：
  1. 回答质疑：给出证据链，结论为 grasp **不是**与 vla/scene_nav 平级的 tool，**从未是**；它只是旧库 engine 持有的 latent 感知子工作流，从不适合作为注册工具放在 `tools/`。
  2. 按 `l3-migration-protocol` §2-⑥（无调用方或调试残留 → 不迁移）裁定 grasp 为**不迁移**。
  3. 在 `rest/` 台账补一条 grasp 条目：旧版链路、已删除面、未来若真有站端消费者时的**接入条件**与**可删除条件**。
- **Non-Goals**：不迁移旧实现；不重建 grasp 技能；不进入公开工具发现面；不改生产代码；不改 `specs/`；不动测试；不引入任务编号。
- **硬边界**：
  - 禁止新设计转接器转接新旧 grasp 接口。
  - 被替代的旧接口保持删除，不得以桩/注释/别名形式恢复。
  - 控制面不携带、不派生任何任务编号或枚举映射（`l3-core-boundary` B8）。
  - 契约先行（G18）：未来若真要技能化 grasp，须先按 `l3-skill-contract.spec.md` 出契约，并**同时**交付技能实现与测试，才能进入发现面。

## 4. 方案决策

- **目标目录树**：无新增目录。`N/tools/` 保持现状（7 个基础设施文件）；文档落在 `doc/l3-dispatcher-planner/` 下既有 `iteration/` 与 `rest/` 两处。
- **命名规范**：方案文档沿用 `design-dispatcher-*.md`；台账条目沿用 R 编号，新增 **R08**（与 R01–R07 的“保留”语义区分，标注为“已删除登记项，不自动恢复”）。
- **接口形态**：无新接口契约。
- **旧接口 → 删除**：已随 `design-dispatcher-unmigrated-chain-removal.md` 删除（`grasp_result/*`、`/agent/grasp_result_image`、grasp 线程、`TASK_ID.GRASP`），本轮不再新增删除动作，只登记留证。

## 5. 迁移映射表

| 旧路径/命名 | 新路径/命名 | 动作 | 备注 |
|-------------|-------------|------|------|
| `O/tools/grasp/workflow.py::GraspWorker` | 无 | delete（已执行） | latent 子工作流；缺 import、方法归属错位，静态不可运行 |
| `O/tools/grasp/__init__.py` | 无 | delete（已执行） | 仅文档字符串，无注册逻辑 |
| `O/engine.py::_grasp_wf` + grasp daemon 线程 | 无 | delete（已执行） | 零生产者，无消费者 |
| `O/engine.py::grasp_result_image_pub`（`/agent/grasp_result_image`） | 无 | delete（已执行） | 站端恒 404，无消费者 |
| `O/zenoh_rpc.py` 的 `grasp_result/*` queryable、结果/图像 latch 与访问器 | 无 | delete（已执行） | 无来源、无消费者 |
| `TASK_ID.GRASP = 11` 及 `_is_aggregated_task_id` 聚合并入 | 无 | delete（已执行） | spec-gated，registry 从未放行 |
| `O/tools/registry.py` 的 14 项 ToolSpec | 无对应 | 无动作 | **从未包含 grasp**，证明其从未进入注册面 |

## 6. 删除清单

| 删除项 | 理由 |
|--------|------|
| `O/tools/grasp/workflow.py`、`O/tools/grasp/__init__.py` | 不可运行、零生产者、无任何技能契约点 |
| engine 的 grasp 工作流实例与 daemon 线程 | latent 残留，调度即 AttributeError |
| `/agent/grasp_result_image` 发布与订阅、`grasp_result/*` queryable 与 latch | 无生产者、无消费读模型 |
| `TASK_ID.GRASP = 11`（含 task-phase 聚合并入） | registry 从未放行（spec-gated），保留将误导发现面 |

## 7. 实施步骤（P0/P1 分期）

### P0 — 文档登记（本方案即交付物，本轮执行）

- 范围：落盘本方案文档；在 `rest/dispatcher-deferred-dependencies.md` 新增 R08 条目并更新头部与「后续关闭条目的记录格式」表；在 `rest/README.md` 同步索引行。
- 行为不变式：不触碰生产代码、`specs/` 与测试；生产发现面保持空集不变；不引入任务编号。
- 验收：方案与台账中所有路径+行号证据可复核；`rest/README.md` 索引与台账一致；数据库/代码零改动。
- 回退：仅撤销本次文档改动，无其他影响。

### P1 — 未来触发式接入（非本轮执行，条件见 R08）

- 范围：仅当出现**真实站端消费者**需求时启动。
- 不变式：先契约后实现（`l3-skill-contract`）；实现与测试同批交付；完成门/裁决/端口按现行契约。
- 验收：新增技能通过 `N/tests/tool-registry/` 与 `N/tests/core-boundary/` 全绿；发现面 revision 随 spec 同步更新。
- 回退：不接受“先搬旧实现、后补契约”的半成品。

## 8. 验收标准

- [ ] 新版 `l3-dispatcher-planner/` 与 `specs/` 全树 grep “grasp”（忽略大小写）保持 **0 命中**。
- [ ] `tests/tool-registry/test_rpc_plane.py` 基线全绿（未改动，作为不动代码的回归锚点）。
- [ ] `rest/dispatcher-deferred-dependencies.md` 含 R08 grasp 条目：旧版链路、已删除面、接入条件、可删除条件齐备。
- [ ] `rest/README.md` 索引与台账同步。
- [ ] 无生产代码、`specs/`、测试文件改动（`git status` 仅显示新增/修改的文档）。

## 9. 风险与对策

| 风险 | 影响 | 对策 |
|------|------|------|
| 未来站端再现 grasp 需求 | 需从零重建 | R08 登记接入条件：先按技能契约出 spec，实现+测试同批交付，再进发现面 |
| 误以为 grasp 曾是被放行的工具 | 决策依据失真 | 证据链明确 registry 14 项从未含 grasp、config 注释“spec-gated未放行” |
| 迁移时顺手恢复旧实现 | 违反 no legacy shim 硬约束 | 硬边界登记 + R08 注明“不自动恢复”，恢复唯一触发条件是真实消费者 |
| grasp 的感知/几何能力被误判为共享能力 | 归属判断错误 | 其感知入口 `_serve_search`（vla 私有）与 `GeometryService`（vla 私有时被跨模块复用）属 §2-③形态，若未来复用须重新设计归属，不原样搬运 |

## 10. 修改点清单汇总

| 文件 | 动作 | 说明 |
|------|------|------|
| `doc/l3-dispatcher-planner/iteration/design-dispatcher-grasp-retirement.md` | 新建 | 本方案（grasp 不迁移、仅登记为删除项） |
| `doc/l3-dispatcher-planner/rest/dispatcher-deferred-dependencies.md` | 修改 | 新增 R08 grasp 条目；更新头部状态说明；追加「后续关闭条目」记录行 |
| `doc/l3-dispatcher-planner/rest/README.md` | 修改 | 索引表新增 grasp → R08 行 |
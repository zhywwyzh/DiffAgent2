# dispatcher task_id 退役与依赖模块迁入方案

> 摘要：本轮做两件事：① 在新仓库（DiffAgent2 新版）`engine.py`（987 行窄 core 版）中退役 task_id 全触点（新版任务解析不再需要 task-id，用户裁决）；② 将旧仓库（DiffAgent2 旧版）dispatcher 包的 `state.py`、`config.py`、`slog.py`、`skill_api.py`、`perception/pointcloud_accumulator.py` 共 5 个模块迁入新仓库，闭合前两轮登记的全部 7 项包内 B 级断裂，使 dispatcher 包达成 import 闭环（仅剩 ROS/三方外部依赖）。engine 手术含一处语义关键点（`_load_next_prompt` 聚合门改单条件）；skill_api 迁入时做 import 区 TYPE_CHECKING 化手术（仅注解用途的两个运行期 import 下沉，同文件既有先例）。

## 0. 元信息

| 项 | 值 |
|----|----|
| 日期 | 2026-09-11 |
| 目标路径 | `l3-dispatcher-planner/ros_packages/dispatcher/dispatcher/`（engine.py 手术 + 5 文件迁入） |
| 状态 | done（2026-09-11 执行并评审放行，验收 V1-V8 全过，见附录） |
| 关联文档 | 姊妹篇：`design-dispatcher-core-inference-migration.md`（首轮迁入，其 §4.3 B 级断裂分级与 §4.6 决策 15 注解惰性化先例为本轮沿用）；`design-dispatcher-engine-narrow-core-trim.md`（二次裁剪，其 §4.3 断裂台账、§4.5 语义声明惯例与附录勘误惯例为本轮沿用）；模板：`doc/l3-dispatcher-planner/iteration/_TEMPLATE.md` |
| 对照基准 | 旧仓库文件仅作迁移源与语义参考；**engine.py 全部行号以新仓库 987 行当前文件为准**，5 个迁入文件行号以旧仓库源文件为准 |
| 源（旧仓库） | `<old-repo-root>/diff-dockers/drone_projects/l3-dispatcher-planner/ros_packages/dispatcher/`（下称 `OLD/`） |
| 目标（新仓库） | `<new-repo-root>/l3-dispatcher-planner/ros_packages/dispatcher/`（下称 `NEW/`） |

## 1. 背景与动机

首轮迁移建立 core+run-inference 基线，二次裁剪把 engine 收敛为 28 def 的窄 core；两轮共登记 7 项包内 B 级断裂（engine 5 + base_policy 2），dispatcher 包在新仓库始终无法 import 闭环。用户本轮给出三项指令：

1. 新版任务解析不再需要 task-id → engine 中 task_id 全触点退役；
2. `dispatcher.state` / `dispatcher.config` / `dispatcher.skill_api` / `dispatcher.slog` 迁入（恰好是 engine 的 5 个 B 级断裂中的 4 个对应模块）；
3. `dispatcher.perception.pointcloud_accumulator` 迁入（base_policy 的断裂之一）。

三项合并的自然结果：**B 级断裂台账清零**（TASK_ID import 随退役摘除、state 断裂同时服务 engine 与 base_policy 两处），dispatcher 包 9 个 py 文件相互闭合，为后续技能/rpc 轮次提供可真实 import 的包底座。

## 2. 现状事实（问题清单）

> engine 行号指向新仓库 987 行当前文件；其余行号指向旧仓库源文件。均逐条复核。

### 2.1 engine.py task_id 全触点（12 处，任务范围 1 的手术对象）

- [x] `NEW/.../engine.py#L26` — `from dispatcher.tools.config import TASK_ID`：B 级断裂之一；引用点 L97/L240/L403/L310-317 全在本清单内，摘除后零残留。
- [x] `NEW/.../engine.py#L93` — `self.prepare_task_ids = []`：与 prepare_content 一一对应的 task_id 队列；下游触点 L239-240/L399-403/L406/L532。
- [x] `NEW/.../engine.py#L97` — `self.current_task_id = TASK_ID.VLA`：读点 L416（loginfo）与 L428（聚合门入参）。
- [x] `NEW/.../engine.py#L239-L240` — sync_task_buffers_from_prepare 内注释 + `prepare_task_ids = [int(TASK_ID.VLA)] * len(...)` 重建。
- [x] `NEW/.../engine.py#L304-L320` — `_is_aggregated_task_id` 整方法（17 行）：task-id 聚合家族判定；**唯一调用点 L428**（全文 grep 复核）。
- [x] `NEW/.../engine.py#L399-L403` — _handle_get_pre_command 内 prepare_task_ids 长度校验 + 恒 VLA 重建块（5 行）。
- [x] `NEW/.../engine.py#L406` — `self.current_task_id = int(self.prepare_task_ids.pop(0))`。
- [x] `NEW/.../engine.py#L416` — `rospy.loginfo(f"Current task: task_id={self.current_task_id}, prompt={...}")`。
- [x] `NEW/.../engine.py#L428` — `if self._is_aggregated_task_id(self.current_task_id) and not self._task_sequence_failed:` ← **语义关键点**，裁决见 §4.1。
- [x] `NEW/.../engine.py#L532` — `_enter_global_stop` 内 `self.prepare_task_ids = []`。
- [x] `NEW/.../engine.py#L837-L838` — DISPATCH 分支注释「task_id 是更上层的任务分发入口。/ 目前只放通 TASK_ID.VLA……」；其后 L839-841 的 P3.8 迁移注记与 task_id 无关（§4.4 裁决 8）。

### 2.2 L428 聚合门恒真性证明（决策点 1 证据）

- `current_task_id` 的全部写点：L97（初值 `TASK_ID.VLA`）、L406（`prepare_task_ids.pop(0)`）；`prepare_task_ids` 的全部写点：L93（空表）、L240 与 L403（恒 `[int(TASK_ID.VLA)] * n` 重建）、L532（清空，其后必经 L240 重建才可 pop）。故 `current_task_id` 在迁入版所有可达状态下恒为 `int(TASK_ID.VLA)`；VLA ∈ `_is_aggregated_task_id` 家族元组（L310）→ **L428 左条件恒 True**，删除断言下该分支裁决与 `if not self._task_sequence_failed:` 逐点等价。
- `_task_sequence_failed` 触点全景（grep 复核）：L117-L120 注释+初始化（False）、L428 唯一读点；**无写点**——其唯一写口 `fail_sequence`（skill_api.py L194 声明的 SkillHost 端口）首轮迁移即未保留，迁入版恒 False。

### 2.3 待迁 5 模块（旧仓库源，任务范围 2/3 对象）

- [x] `OLD/dispatcher/state.py`（45 行）：仅 `from __future__ import annotations`，定义 `COMMAND_TYPE/DISPATCHER_STATE/COMMAND_STATUS/MISSION_TYPE`。消费者：engine L27（3 符号）、base_policy L35（`MISSION_TYPE`）。
- [x] `OLD/dispatcher/config.py`（241 行）：外部依赖 os/deepcopy/typing/rospy/yaml，**零包内依赖**；提供 engine L28-L39 引用的全部 10 符号（`merge_dicts` 为内部实现，engine 不引用但 `load_yaml`/`merge_pointcloud_mode_params` 依赖它）。注意：此为包根 `dispatcher/config.py`，不是 `tools/config.py`（后者本轮不迁，见 §4.4 裁决 7）。
- [x] `OLD/dispatcher/slog.py`（157 行）：外部依赖 json/sys/time/pathlib，零包内依赖；`StructuredLogger` 被 engine L136-L140 实例化。
- [x] `OLD/dispatcher/skill_api.py`（201 行）：L33 `from __future__ import annotations`；**L38-L39 两个运行期 import 为本轮唯一迁移手术点**（§2.4）；其余 `enum/typing` 零包内运行依赖。
- [x] `OLD/dispatcher/perception/pointcloud_accumulator.py`（198 行）：外部依赖 deque/threading/typing/numpy/rospy/sensor_msgs，零包内依赖；被 base_policy L36-L39 import。

### 2.4 skill_api.py 两个运行期 import 的用途核实（决策点 2 证据）

- `RecordingService`（L38 import）：全文唯一使用点 L159 `recording: RecordingService` —— SkillHost Protocol **类体注解**。
- `SkillCommand`（L39 import）：全文使用点 L57/L58（Skill Protocol 的 `on_start`/`plan_tick` 签名）与 L111/L114（SkillBase 同名方法签名），共 4 处，**全部为方法签名注解**。
- L33 `from __future__ import annotations` 生效 → PEP 563 下上述注解（含类体变量注解）一律不求值；两符号迁入 TYPE_CHECKING 块后**运行期零损失**。
- 同文件先例：L41-L42 `if TYPE_CHECKING: from dispatcher.tools.vla.vlm_facade import VlmFacade`，头注 L24-L25 明文「vlm 属性类型注记为 VlmFacade（……TYPE_CHECKING 引用避免契约模块拖入 VLM 重依赖链）」——旧仓库自身已确立该惯例；首轮方案 §4.6 决策 15（engine 侧 ToolCall/SkillCommand import 摘除）为第二轮先例。
- 顺带迁移选项的依赖雪球核实：`recording.py` L13 `from dispatcher.tools.helpers import clean_object_name, pose_to_list, write_json`；`tools/helpers.py` 头部仅 stdlib+numpy（7 个 import，零包内依赖）；`tools/model.py` 零包内依赖。即「顺带迁 recording」最小闭包 = recording + tools/model + tools/helpers 共 3 个范围外文件。

### 2.5 新仓库包内 import 全景（本轮闭合对象）

- [x] `engine.py` L26（tools.config，本轮摘除）、L27（state）、L28-L39（config）、L40（skill_api）、L43（base_policy，已闭合）。
- [x] `base_policy.py` L35（state.MISSION_TYPE）、L36-L39（perception.pointcloud_accumulator）。
- [x] 新仓库目录现状：`dispatcher/dispatcher/{__init__.py, engine.py, perception/{__init__.py, base_policy.py}}`，共 4 个 py 文件。

## 3. 目标与约束

- **目标**：
  1. engine.py 退役 task_id 全部 12 处触点（§2.1），def 28 → 27（删 `_is_aggregated_task_id`），行数 987 → 约 955。
  2. 5 个模块迁入 `NEW/dispatcher/dispatcher/`（含 perception 子目录）：4 个原样字节级一致，skill_api.py 仅 import 区 TYPE_CHECKING 化手术（201 行行数不变，diff 仅 1 个 hunk）。
  3. **B 级断裂台账清零**：dispatcher 包 9 个 py 文件 import 相互闭合，仅剩 ROS/三方外部依赖（rospy/std_msgs/sensor_msgs/numpy/yaml/stdlib）。
- **Non-Goals**：
  - 不迁 `tools/` 任何文件（含 `tools/config.py`——其唯一新仓库消费者 TASK_ID import 本轮摘除；`tools/model.py`、`tools/helpers.py`、`recording.py` 留待 recording/tools 轮次）。
  - 不改 `_load_next_prompt`/`_handle_get_pre_command`/`sync_task_buffers_from_prepare` 的非 task_id 逻辑（含 L405 `prompt = self.pre_prompt.pop(0)` 的既有零引用左值——非触点不越界改写，见 §4.4 裁决 9）。
  - 不触碰 `base_policy.py`、两个既有 `__init__.py`。
  - 不做 FSM 语义重构：L428 改单条件是删除恒真子条件，非行为改写（§4.1 论证）。
  - 不 commit（沿用前两轮惯例，等待用户显式指令）。
- **硬边界**：
  - 禁止转接器：不新增任何桥接新旧接口的层；skill_api 的 TYPE_CHECKING 下沉不桥接任何接口，仅按 PEP 563 语义等价移动注解符号的可见域。
  - 过期必删：task_id 触点全部直接删除，不留注释桩、不注释掉（L837-L838 注释删除同理）。
  - 迁移非重构：文件名、模块路径、符号名一律沿用旧仓库原名。

## 4. 方案决策

### 4.1 决策点 1：L428 聚合门 → 保留 `_task_sequence_failed` 单条件

裁决：L428 改为

```python
            if not self._task_sequence_failed:
```

FSM 行为影响分析（对照二次裁剪 §4.5 语义声明惯例）：

1. **可达状态逐点等价**：迁入版 `current_task_id` 恒为 VLA、聚合判定恒 True（§2.2 证明），删左条件不改变任何可达输入下该分支的裁决——队尽且序列未失败时仍发 `done` 相位（`pop_task_result` + `_publish_task_phase("done", ...)` 原样），失败守卫语义不变。
2. **守卫语义归位**：`_task_sequence_failed` 是「primitive 失败即终止整个 prompt 序列，后续不得再发 done」（canonical §3.3，L117-L119 注释），与 task 家族正交；原双条件中它本就是行为守卫，`_is_aggregated_task_id` 是来源分类。退役 task_id 后分类条件失去存在依据（新版任务解析无 task-id 概念），守卫完整保留。
3. **写口缺位现状与归位路径**：迁入版无 `fail_sequence` 写口、标志恒 False——与旧行为等价（原左条件恒 True + 标志恒 False）。未来技能/接线轮次恢复 `fail_sequence` 端口时写回此标志，L428 守卫即刻生效，零返工（登记 §9 风险 3 与后续轮次待办）。
4. **不采纳的替代项**：整分支删除（done 相位是 `_publish_task_phase`/`pop_task_result`/`_task_phase_progress` 在闭包内的存活根，删除引发连锁语义缩窄，违背「只删 task_id 不改 FSM」边界）；无条件恒发 done（丢失失败守卫，未来 fail_sequence 恢复时需二次手术）。

### 4.2 决策点 2：skill_api 两 import → TYPE_CHECKING 手术（推荐项，已采纳）

裁决：L38-L39 两行从运行期区删除，符号移入既有 `if TYPE_CHECKING:` 块（逐字片段见 §7.2）。三选项论证：

| 选项 | 后果 | 判定 |
|------|------|------|
| a. TYPE_CHECKING 下沉（采纳） | 两符号仅注解用途（§2.4 证据），PEP 563 下零运行时损失；与同文件 VlmFacade 惯例、首轮决策 15 先例一致；迁入版 import 闭环达成 | **采纳**：最小手术面（-2/+2 行）、零新断裂、零行为变化 |
| b. 原样迁入 + 登记 recording/tools.model 为 B 级断裂 | engine L40 `import dispatcher.skill_api` 即触发 `dispatcher.recording` → `dispatcher.tools.helpers` 链式 ImportError，**skill_api 本身不可 import**，B 级断裂不减反增（+2），且未来每一轮「能否 import 冒烟」都被这两行卡死 | 否决：为两个不求值的注解符号引入两个可运行级断裂，代价与收益倒挂 |
| c. 顺带迁 recording.py + tools/model.py | 雪球核实为 3 个范围外文件（§2.4）；model.py 的 `ToolCall.task_id` 字段（L31）与「task_id 退役」方向相冲，本轮迁入反而要立刻面对 schema 改动；为一个注解符号扩迁移范围违背轮次边界（首轮决策 3 同款理由） | 否决：留待 tools/recording 轮次整体裁决 |

非转接器论证：TYPE_CHECKING 块不桥接任何新旧接口——它只是把「模块加载期符号绑定」降级为「类型检查期符号可见」，运行期任何路径都不经过它；这与「禁止设计转接层桥接新旧接口」约束无交集。

### 4.3 决策点 3：关联状态孤儿排查（逐一裁决）

| 属性/符号 | 触点（手术后） | 裁决 | 理由 |
|-----------|----------------|------|------|
| `prepare_task_ids` | L93/L240/L399-403/L406/L532 全删 → 零引用 | **删** | task_id 队列本体 |
| `current_task_id` | L97/L406/L416/L428 全删 → 零引用 | **删** | task_id 当前值本体 |
| `_is_aggregated_task_id` | 方法删除后零调用方 | **删**（def 28→27） | 唯一调用点 L428 已改造 |
| `TASK_ID` import | L97/L240/L310-317 全删 → 零引用 | **摘**（B 级断裂消失） | tools.config 断裂唯一入口 |
| `_task_sequence_failed` | L117-L120 初始化保留、L428 读点保留（单条件） | **保留** | §4.1：任务级失败守卫，语义独立于 task_id；写口由未来 fail_sequence 轮次恢复 |
| `_task_phase_progress` | L218 初始化、L432 读点（done 相位 progress 字段） | **保留** | 有活读点；恒 0 属写点未迁的既有惰性态（与二次裁剪 §9 风险 9 同类登记） |
| `replan_content` | L95 初始化、L414-L415 读写、L416 读、L534 清空 | **保留** | 与 task_id 无关的活跃状态（当前重规划参考命令） |

### 4.4 补充裁决（复核中发现）

| # | 事项 | 裁决 | 理由 |
|---|------|------|------|
| 5 | 断裂台账更新 | 本轮后 B 级清零（§5.2 台账） | 7 项全部闭合（state×2/config/skill_api/slog/pointcloud_accumulator 迁入）或消失（tools.config 随 import 摘除） |
| 6 | sync_task_buffers_from_prepare 自洽性 | 删 L239-L240 后方法自洽 | 校验/重建链整体退役；`valid_entries → prepare_content → content/pre_prompt/prompt_bf` 派生链完整，长度校验的对象（prepare_task_ids）不复存在，校验块随之失去意义，删除即自洽 |
| 7 | `tools/config.py` 不迁 | 不迁 | 唯一新仓库消费者是本轮摘除的 TASK_ID import；无消费者即无迁移理由 |
| 8 | L837-L841 注释块拆分 | 删 L837-L838（task_id 专属描述，名不副实即删）；**保留 L839-L841**（P3.8 迁移注记，描述 `_validate_active_tool` 前身的删除历史，仍然准确） | 注释删除以「是否仍准确」为准，与首轮 P3-1 孤儿注释处置惯例对齐 |
| 9 | L405 `prompt = self.pre_prompt.pop(0)` | 原样保留（含零引用左值） | 左值 `prompt` 零后续引用属既有现象（非本轮引入）；pop 调用语义必需（pre_prompt 队列推进）。改写左值属范围外修饰，违背最小手术 |
| 10 | L416 loginfo 改写 | `rospy.loginfo(f"Current task: prompt={self.replan_content[0]}")` | 仅摘 `task_id=` 片段，保留 prompt 打印 |
| 11 | skill_api TYPE_CHECKING 块内符号排序 | recording → tools.model → tools.vla.vlm_facade | 按模块路径字典序，与既有 vlm_facade 排布一致 |
| 12 | engine 侧 `SkillCommand`/`ToolCall` 签名注解（L442/L464） | 不动 | 首轮决策 15 已摘 import、注解惰性化；本轮无涉 |

### 4.5 语义声明（本轮退役后的窄 core 行为）

1. **任务来源模型**：引擎不再持有「task_id 分类」概念；prepare_content 队列是唯一任务来源（配置面经 sync_task_buffers_from_prepare 装载），队尽 done 聚合上报无条件归属本节点（失败守卫除外）。
2. **done 相位行为不变**：可达状态下与退役前逐点一致（§4.1 论证）；`_task_sequence_failed` 恒 False 期间的对外可观测行为（telemetry/phase 事件）零变化。
3. **skill_api 契约完整性**：TYPE_CHECKING 下沉后，`Skill`/`SkillBase`/`SkillHost` 的注解在静态类型检查器下仍全量可解析；运行期 `SkillVerdict`（engine 实际消费的唯一符号）不受影响。

### 4.6 目标目录树与命名规范

```
ros_packages/dispatcher/dispatcher/
  __init__.py                      # 既有，不动
  engine.py                        # 既有，task_id 退役手术
  state.py                         # 新迁入（copy 原样，45 行）
  config.py                        # 新迁入（copy 原样，241 行）
  slog.py                          # 新迁入（copy 原样，157 行）
  skill_api.py                     # 新迁入（copy + import 区 TYPE_CHECKING 化，201 行）
  perception/
    __init__.py                    # 既有，不动
    base_policy.py                 # 既有，不动（2 个断裂本轮闭合）
    pointcloud_accumulator.py      # 新迁入（copy 原样，198 行）
```

命名规范沿用首轮 §4.2（迁移非重构，文件/类/函数名一律不变；方案文档 `design-dispatcher-*.md` 惯例）。

## 5. 迁移映射表

### 5.1 五文件迁移映射

| 旧路径/命名 | 新路径/命名 | 动作 | 备注 |
|-------------|-------------|------|------|
| `OLD/dispatcher/state.py` | `NEW/dispatcher/state.py` | copy（原样） | 45 行字节级一致；闭合 engine L27 + base_policy L35 |
| `OLD/dispatcher/config.py` | `NEW/dispatcher/config.py` | copy（原样） | 241 行字节级一致；闭合 engine L28-L39（10 符号） |
| `OLD/dispatcher/slog.py` | `NEW/dispatcher/slog.py` | copy（原样） | 157 行字节级一致；闭合 engine L41 |
| `OLD/dispatcher/skill_api.py` | `NEW/dispatcher/skill_api.py` | copy + 手术 | 201 行；唯一手术 = L38-L39 移入 TYPE_CHECKING 块（§7.2 逐字片段）；行数不变；闭合 engine L40 且零新断裂 |
| `OLD/dispatcher/perception/pointcloud_accumulator.py` | `NEW/dispatcher/perception/pointcloud_accumulator.py` | copy（原样） | 198 行字节级一致；闭合 base_policy L36-L39 |

### 5.2 断裂台账（前后对比）

| 包内 import（消费点） | 本轮前 | 本轮后 |
|------------------------|--------|--------|
| engine → `dispatcher.tools.config`（TASK_ID，L26） | B 级断裂 | **消失**（import 随退役摘除） |
| engine → `dispatcher.state`（L27） | B 级断裂 | **闭合**（state.py 迁入） |
| engine → `dispatcher.config`（L28-L39） | B 级断裂 | **闭合**（config.py 迁入） |
| engine → `dispatcher.skill_api`（L40） | B 级断裂 | **闭合**（skill_api.py 迁入 + §4.2 手术） |
| engine → `dispatcher.slog`（L41） | B 级断裂 | **闭合**（slog.py 迁入） |
| base_policy → `dispatcher.state`（L35） | B 级断裂 | **闭合**（同 state.py） |
| base_policy → `dispatcher.perception.pointcloud_accumulator`（L36） | B 级断裂 | **闭合**（pointcloud_accumulator.py 迁入） |
| skill_api → recording / tools.model（源文件 L38-L39） | 运行期依赖（源仓库） | **零新断裂**（TYPE_CHECKING 下沉，登记后续轮次） |

结论：B 级断裂 7 项 → **0 项**；dispatcher 包 import 面仅剩外部依赖（rospy/std_msgs/sensor_msgs/numpy/yaml/stdlib）。

### 5.3 engine.py task_id 手术清单（方法级 + 行级）

| # | 行号（987 行基线） | 方法 | 手术 |
|---|---------------------|------|------|
| S1 | L837-L838 | `_run_inference_loop` | 删 2 行注释（保留 L839-L841，裁决 8） |
| S2 | L532 | `_enter_global_stop` | 删 `self.prepare_task_ids = []` |
| S3 | L428 | `_load_next_prompt` | 改 `if not self._task_sequence_failed:`（§4.1） |
| S4 | L416 | `_handle_get_pre_command` | 改 `rospy.loginfo(f"Current task: prompt={self.replan_content[0]}")` |
| S5 | L406 | `_handle_get_pre_command` | 删 `self.current_task_id = int(self.prepare_task_ids.pop(0))` |
| S6 | L399-L403 | `_handle_get_pre_command` | 删长度校验 + 重建块（5 行整块） |
| S7 | L304-L320（+尾随 1 空行） | `_is_aggregated_task_id` | 删整方法（17+1 行） |
| S8 | L239-L240 | `sync_task_buffers_from_prepare` | 删注释 + 重建行（2 行） |
| S9 | L97 | `__init__` | 删 `self.current_task_id = TASK_ID.VLA` |
| S10 | L93 | `__init__` | 删 `self.prepare_task_ids = []` |
| S11 | L26 | import 区 | 删 `from dispatcher.tools.config import TASK_ID` |

统计：删 32 行、改写 2 行（L416/L428 行数不变）；987 → 约 955 行；def 28 → 27；手术方法 6 个（`__init__`/`sync_task_buffers_from_prepare`/`_handle_get_pre_command`/`_load_next_prompt`/`_enter_global_stop`/`_run_inference_loop`，前五个为删行、`_load_next_prompt` 为条件改写），其余 21 个保留方法零手术。

## 6. 删除清单

| 删除项 | 位置 | 理由 |
|--------|------|------|
| `TASK_ID` import | engine L26 | 用户范围 1；引用点全随触点删除（§4.3） |
| `prepare_task_ids` 属性及全部触点 | engine L93/L239-L240/L399-L403/L406/L532 | task_id 队列本体，退役后零引用 |
| `current_task_id` 属性及全部触点 | engine L97/L406/L416/L428 | task_id 当前值本体，退役后零引用 |
| `_is_aggregated_task_id` 方法 | engine L304-L320 | 唯一调用点 L428 改造；task-id 家族判定随概念退役（§4.1） |
| L239 注释「单一任务来源 = tool registry 的 task_id……」 | engine L239 | 描述被删逻辑，名不副实即删 |
| L837-L838 注释「task_id 是更上层的任务分发入口……」 | engine L837-L838 | 同上（L839-L841 保留，裁决 8） |
| skill_api L38-L39 运行期 import 区两行 | skill_api.py L38-L39 | 移入 TYPE_CHECKING 块（非删除语义，符号仍对类型检查器可见；§4.2） |

## 7. 实施步骤（P0 单期）

> 行为不变式：除 §5.3 表 11 项手术与 §7.2 片段外，engine.py 不新增/改写任何行；5 个迁入文件中 4 个与旧文件字节级一致、skill_api.py 仅 import 区 1 个 hunk。engine 手术按 987 行基线行号**从大到小**执行，每步先 grep 锚点确认再动手；相邻删除区间合并后空行归一（类内成员间恰好 1 空行、模块级定义间 2 空行）。

### P0 — 五文件迁入 + engine/skill_api 手术 + 验收

- 范围：新增 5 文件 + 修改 `NEW/dispatcher/engine.py`；不触碰其他任何文件。
- 回退：engine 术前快照 `cp .../engine.py /tmp/engine.py.taskid-baseline`；5 个新增文件直接删除即回退；engine 回滚 `cp /tmp/engine.py.taskid-baseline .../engine.py`。

**步骤 0：基线快照与断言**

```bash
cd <new-repo-root>
F=l3-dispatcher-planner/ros_packages/dispatcher/dispatcher/engine.py
cp "$F" /tmp/engine.py.taskid-baseline
test "$(grep -c 'def ' "$F")" = "28" || { echo 'BASELINE MISMATCH'; exit 1; }
```

**步骤 1：五文件迁入（cp 命令）**

```bash
OLD=<old-repo-root>/diff-dockers/drone_projects/l3-dispatcher-planner/ros_packages/dispatcher
NEW=<new-repo-root>/l3-dispatcher-planner/ros_packages/dispatcher
cp "$OLD/dispatcher/state.py"        "$NEW/dispatcher/state.py"
cp "$OLD/dispatcher/config.py"       "$NEW/dispatcher/config.py"
cp "$OLD/dispatcher/slog.py"         "$NEW/dispatcher/slog.py"
cp "$OLD/dispatcher/skill_api.py"    "$NEW/dispatcher/skill_api.py"   # 步骤 2 手术底稿
cp "$OLD/dispatcher/perception/pointcloud_accumulator.py" \
   "$NEW/dispatcher/perception/pointcloud_accumulator.py"
```

**步骤 2：skill_api.py import 区手术（唯一手术点）**

手术前（源文件 L33-L42）：

```python
from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING, Any, Protocol

from dispatcher.recording import RecordingService
from dispatcher.tools.model import SkillCommand

if TYPE_CHECKING:
    from dispatcher.tools.vla.vlm_facade import VlmFacade
```

手术后（删除 L38-L39 两行及其后 1 空行，TYPE_CHECKING 块按裁决 11 排序补 2 行）：

```python
from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from dispatcher.recording import RecordingService
    from dispatcher.tools.model import SkillCommand
    from dispatcher.tools.vla.vlm_facade import VlmFacade
```

锚点：删除前 `grep -n 'from dispatcher.recording import RecordingService'` 在该文件唯一命中 L38。

**步骤 3：engine.py 手术（按 §5.3 序号 S1→S11 即降序执行）**

| 序 | 行号 | 锚点（删除/改写前 grep 必须唯一命中） |
|----|------|----------------------------------------|
| S1 | L837-L838 | `task_id 是更上层的任务分发入口` |
| S2 | L532 | `self.prepare_task_ids = \[\]`（注意与 L93 同串，取 `_enter_global_stop` 内上下文；L93 在 S10 处理） |
| S3 | L428 | `_is_aggregated_task_id(self.current_task_id) and not` → 改 `if not self._task_sequence_failed:` |
| S4 | L416 | `Current task: task_id=` → 改 `rospy.loginfo(f"Current task: prompt={self.replan_content[0]}")` |
| S5 | L406 | `self.current_task_id = int(self.prepare_task_ids.pop(0))` |
| S6 | L399-L403 | `prepare_task_ids length mismatch` 起至 `= \[int(TASK_ID.VLA)\] \* len` 止（5 行整块） |
| S7 | L304-L320+尾空行 | `def _is_aggregated_task_id` 起至其 `return False` 止，连同与后续 `@staticmethod` 之间 1 空行 |
| S8 | L239-L240 | `单一任务来源 = tool registry 的 task_id` 起至 `prepare_task_ids = \[int` 行止 |
| S9 | L97 | `self.current_task_id = TASK_ID.VLA` |
| S10 | L93 | `self.prepare_task_ids = \[\]`（`__init__` 内） |
| S11 | L26 | `from dispatcher.tools.config import TASK_ID` |

**步骤 4：验收（§8 全绿才算完成；不 commit）**

## 8. 验收标准

- [x] **V1 语法（9 个 py 全量）**：

```bash
python3 -m py_compile \
  <new-repo-root>/l3-dispatcher-planner/ros_packages/dispatcher/dispatcher/engine.py \
  <new-repo-root>/l3-dispatcher-planner/ros_packages/dispatcher/dispatcher/state.py \
  <new-repo-root>/l3-dispatcher-planner/ros_packages/dispatcher/dispatcher/config.py \
  <new-repo-root>/l3-dispatcher-planner/ros_packages/dispatcher/dispatcher/slog.py \
  <new-repo-root>/l3-dispatcher-planner/ros_packages/dispatcher/dispatcher/skill_api.py \
  <new-repo-root>/l3-dispatcher-planner/ros_packages/dispatcher/dispatcher/perception/pointcloud_accumulator.py \
  <new-repo-root>/l3-dispatcher-planner/ros_packages/dispatcher/dispatcher/perception/base_policy.py \
  <new-repo-root>/l3-dispatcher-planner/ros_packages/dispatcher/dispatcher/__init__.py \
  <new-repo-root>/l3-dispatcher-planner/ros_packages/dispatcher/dispatcher/perception/__init__.py
```

- [x] **V2 原样迁入字节级一致（4 文件；输出为空即通过）**：

```bash
OLD=<old-repo-root>/diff-dockers/drone_projects/l3-dispatcher-planner/ros_packages/dispatcher/dispatcher
NEW=<new-repo-root>/l3-dispatcher-planner/ros_packages/dispatcher/dispatcher
cmp "$OLD/state.py"        "$NEW/state.py"
cmp "$OLD/config.py"       "$NEW/config.py"
cmp "$OLD/slog.py"         "$NEW/slog.py"
cmp "$OLD/perception/pointcloud_accumulator.py" "$NEW/perception/pointcloud_accumulator.py"
```

- [x] **V3 skill_api 手术面核对（diff 仅 import 区 1 个 hunk）**：

```bash
diff -u "$OLD/skill_api.py" "$NEW/skill_api.py"   # 预期唯一 hunk：删运行期两 import、TYPE_CHECKING 块增两行；其余零差异
```

- [x] **V4 engine 负向 grep（本轮无注释白名单；输出为空即通过）**：

```bash
grep -nE '\b(task_id|TASK_ID)\b|prepare_task_ids|current_task_id|_is_aggregated_task_id' \
  <new-repo-root>/l3-dispatcher-planner/ros_packages/dispatcher/dispatcher/engine.py
```

（预期零命中：全部触点含注释已删；`_task_sequence_failed`/`task_generation`/`task_phase` 等不含 `task_id` 子串，不误伤。）

- [x] **V5 方法闭包复核（期望集 = 二次裁剪 22 方法减 `_is_aggregated_task_id`；输出 `UNRESOLVED: []` 与 `CLOSURE-OK`）**：

```bash
python3 - <<'EOF'
import ast
ENG = "<new-repo-root>/l3-dispatcher-planner/ros_packages/dispatcher/dispatcher/engine.py"
BASE = "<new-repo-root>/l3-dispatcher-planner/ros_packages/dispatcher/dispatcher/perception/base_policy.py"
EXPECT = {"run_inference","_run_inference_loop","_recover_inference_after_exception",
"_enter_global_stop","_reset_plan_cycle_if_needed","_validate_active_tool",
"_handle_plan_tool","_action_done","_handle_post_action","_advance_to_next_prompt",
"_load_next_prompt","_handle_get_pre_command","_publish_task_phase",
"publish_command_content","_set_dispatcher_state",
"_set_if_handle_yaw","_bump_task_generation","_telemetry",
"_decision_chain_wait_diag","_fmt_wait_age","pop_task_result"}
def load(path, cls_name):
    tree = ast.parse(open(path, encoding="utf-8").read())
    cls = [n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == cls_name][0]
    methods = {}
    for m in cls.body:
        if isinstance(m, ast.FunctionDef):
            methods[m.name] = {
                a.func.attr for a in ast.walk(m)
                if isinstance(a, ast.Call) and isinstance(a.func, ast.Attribute)
                and isinstance(a.func.value, ast.Name) and a.func.value.id == "self"
            }
    return methods
eng = load(ENG, "DispatcherEngine")
base_m = set(load(BASE, "BasePolicyNode"))
seen, stack = set(), ["run_inference"]
while stack:
    m = stack.pop()
    if m in seen or m not in eng: continue
    seen.add(m); stack.extend(eng[m])
resolved = set(eng) | base_m | {"clear"}
unresolved = {c for cs in eng.values() for c in cs} - resolved
print("UNRESOLVED:", sorted(unresolved))
print("CLOSURE-OK" if seen == EXPECT else f"CLOSURE-MISMATCH: {sorted(seen ^ EXPECT)}")
EOF
```

- [x] **V6 def 计数**：`grep -c 'def ' <engine.py>` == **27**
  （二次裁剪基线 28 − `_is_aggregated_task_id`；含 `PendingAction.clear` 与嵌套 `_state_name`）。

- [x] **V7 属性闭包**（沿二次裁剪 V5 三源脚本原样复跑；输出 `UNRESOLVED: []`。本轮删的 `prepare_task_ids`/`current_task_id` 均为 store 侧属性，loads 随手术同步消失，预期不变）。

- [x] **V8 import 冒烟（可选，按主机环境分级；这是 B 级断裂清零后的首次真实 import 验收）**：

```bash
cd <new-repo-root>/l3-dispatcher-planner/ros_packages/dispatcher
# 分级一（零 ROS 依赖子集，主机必跑）：
PYTHONPATH=. python3 -c "import dispatcher.state, dispatcher.slog, dispatcher.skill_api; print('SMOKE-L1-OK')"
# 分级二（判定条件：python3 -c 'import rospy, yaml, numpy' 退出码为 0 时执行，否则跳过并记录）：
python3 -c "import rospy, yaml, numpy" && \
PYTHONPATH=. python3 -c "import dispatcher.config, dispatcher.perception.pointcloud_accumulator; print('SMOKE-L2-OK')"
# 分级三（判定条件：rospy 环境存在且 sensor_msgs/std_msgs/nav_msgs/visualization_msgs/message_filters 可导入时执行）：
python3 -c "import rospy, sensor_msgs, std_msgs, nav_msgs, visualization_msgs, message_filters, cv_bridge, cv2" && \
PYTHONPATH=. python3 -c "import dispatcher.engine; print('SMOKE-L3-OK')"
```

判定条件说明：分级一覆盖 state/slog/skill_api（手术后零 ROS 依赖），任何主机必须通过；分级二/三依赖主机 ROS1 环境（base_policy 的 nav_msgs 等消息包缺口系首轮 §2 登记的 package.xml 既有缺口，非本轮引入），不可用时**回退静态验收**（V1-V7 全绿即为通过），不得因环境缺失判失败。

## 9. 风险与对策

| 风险 | 影响 | 对策 |
|------|------|------|
| 1. L428 语义变化（聚合门改单条件） | done 相位触发条件改变 | §2.2 恒真性证明：迁入版左条件恒 True，删除后可达状态逐点等价；§4.5 语义声明归档；V5 闭包 + 未来运行时验收兜底。语义变化点仅是「来源分类」概念退役，非行为变化 |
| 2. skill_api 手术理由不足引发质疑（TYPE_CHECKING 下沉是否算改契约） | 评审反复/返工 | §2.4 证据链：两符号仅注解用途 + PEP 563 + 同文件 VlmFacade 先例 + 首轮决策 15 先例；V3 diff 核对手术面仅 1 hunk；非转接器论证见 §4.2 |
| 3. `_task_sequence_failed` 处置（保留无写口属性） | 读者困惑「恒 False 为何保留」 | §4.1/§4.3 登记其守卫语义与写口归位路径（fail_sequence 端口轮次）；与二次裁剪 §9 风险 9 的惰性属性同类处置 |
| 4. 手术行号漂移切错行 | engine 损坏 | §7 降序执行 + 锚点唯一命中断言；V4 负向 grep 零白名单（本轮注释全删，无白名单豁免负担）+ V5/V6/V7 三闸 |
| 5. `tools/config.py` 断裂消失后被误判为「tools.config 已迁」 | 后续轮次误操作 | §4.4 裁决 7 明文登记：不迁、无消费者；tools 树整体留待 tools 轮次 |
| 6. 未来 tools/model.py 迁入轮需要运行期 `SkillCommand`（如 isinstance） | 需改回 import | 届时把 TYPE_CHECKING 行移回运行期区即可（一行改动）；本轮注解惰性化不构成永久锁定；旧仓库 model.py `ToolCall.task_id` 字段（L31）与 task_id 退役方向的冲突登记给 tools 轮次裁决 |
| 7. import 冒烟分级三被 base_policy 消息包缺口卡住（package.xml 既有缺口） | 冒烟误判失败 | §8 V8 判定条件显式分级；环境缺失回退静态验收，缺口归属 package.xml 轮次 |
| 8. config.py 迁入后 `UAV_POLICY_DEFAULTS` 与 engine 属性面的别名（`_min_action_wait`）行为漂移 | 配置注入异常 | config.py 原样迁移零行为变化（首轮 V5 的 CONFIG_KEYS 键集即源自该文件）；V7 复跑确认 |
| 9. 空行归一与手术区间合并产生意外多删 | 保留方法受损 | 沿二次裁剪惯例：归一仅限删除区间边界，方法体逐字节不动；步骤 0 基线快照支持逐行 diff 终检 |

回滚路径：engine 用 `/tmp/engine.py.taskid-baseline` 快照回拷（或已入库时 `git checkout -- <path>`）；5 个新增文件直接删除；工作区不留中间产物（/tmp 快照不入仓库）。

## 10. 修改点清单汇总

| 文件 | 动作 | 说明 |
|------|------|------|
| `l3-dispatcher-planner/ros_packages/dispatcher/dispatcher/engine.py` | 修改（删 32 行 + 改写 2 行） | task_id 全触点退役（§5.3 的 S1-S11）；987 → 约 955 行；def 28 → 27；B 级断裂 −1（tools.config） |
| `l3-dispatcher-planner/ros_packages/dispatcher/dispatcher/state.py` | 新增（copy 原样） | 45 行；闭合 engine + base_policy 两处 state 断裂 |
| `l3-dispatcher-planner/ros_packages/dispatcher/dispatcher/config.py` | 新增（copy 原样） | 241 行；闭合 engine config 断裂（10 符号） |
| `l3-dispatcher-planner/ros_packages/dispatcher/dispatcher/slog.py` | 新增（copy 原样） | 157 行；闭合 engine slog 断裂 |
| `l3-dispatcher-planner/ros_packages/dispatcher/dispatcher/skill_api.py` | 新增（copy + import 手术） | 201 → 200 行（净 −1 行，勘误见附录）；L38-L39 移入 TYPE_CHECKING；闭合 engine skill_api 断裂且零新断裂 |
| `l3-dispatcher-planner/ros_packages/dispatcher/dispatcher/perception/pointcloud_accumulator.py` | 新增（copy 原样） | 198 行；闭合 base_policy pointcloud_accumulator 断裂 |
| `doc/l3-dispatcher-planner/iteration/design-dispatcher-taskid-retirement-deps-migration.md` | 新增 | 本方案 |

不触碰：`base_policy.py`、两个既有 `__init__.py`、旧仓库任何文件、tools/ 树、recording.py；不 commit。

**登记的后续轮次待办**：① `fail_sequence` 端口（`_task_sequence_failed` 唯一写口）恢复时直接生效于 L428 守卫；② tools/model.py 迁入轮若需运行期 `SkillCommand`，将 TYPE_CHECKING 行移回运行期区，并裁决 `ToolCall.task_id` 字段与新任务解析的对齐；③ package.xml 依赖缺口（nav_msgs/visualization_msgs/message_filters）继续归属 package.xml 轮次。

---

## 附录：执行与评审记录（2026-09-11）

**执行**：code-fixer 按本方案 §7 P0 执行完毕。S1-S11 全部锚点术前逐项核对、
零行号偏差（S2/S10 同串按方法上下文区分命中）；engine 987 → 955 行
（删 32 行 + 改写 2 行）、def 28 → 27；5 文件迁入（state 45 / config 241 /
slog 157 / skill_api 200 / pointcloud_accumulator 198）；术前快照
`/tmp/engine.py.taskid-baseline`；py_compile 缓存已清理。

**验收实测**：V1 九文件 py_compile 全过；V2 四文件 cmp 零差异；V3 skill_api
diff 仅 1 个 hunk（`@@ -35,10 +35,9 @@`，与 §7.2 逐字一致）；V4 负向 grep
零命中；V5 `UNRESOLVED: []` + `CLOSURE-OK`（21 方法闭包）；V6 def = 27；
V7 `UNRESOLVED: []`；V8 分级一 `SMOKE-L1-OK`、分级二 `SMOKE-L2-OK`
（PYTHONPATH 修正为前置追加 `.:$PYTHONPATH`，保留 ROS dist-packages）、
分级三按判定条件跳过（主机 ROS noetic 预编译 cv_bridge 与当前 numpy
不兼容，环境问题非代码引入）。

**评审**：deep-oracle 独立复核（L428 恒真性证据链逐环复验、基线全量偏移
链比对、skill_api 运行期零损失验证、9 文件包内 import 静态闭环清单、
孤儿属性大小写不敏感 grep），总裁决「放行」（约 90% 置信度）。

**勘误（已回写正文）**：

1. skill_api.py 实际 200 行（净 −1 行：删 2 import + 1 空行、补 2 行），
   初版 §3/§5.1/§10「201 行行数不变」为笔误——§7.2 片段推演本就是 −1 行；
   代码忠实于 §7.2，无需改动。
2. V8 分级二命令的 `PYTHONPATH=.` 为覆盖语义会剥离既有 ROS 路径，执行时
   修正为 `PYTHONPATH=.:$PYTHONPATH`，判定条件与结果不变。

**待环境补跑**（评审观察项 P2）：任一 ROS1 环境主机补跑
`PYTHONPATH=.:$PYTHONPATH python3 -c "import dispatcher.engine"`（SMOKE-L3），
作为 engine 运行期 import 的直接运行时证据；可与 package.xml 轮次一并处理。

**未执行**：git add/commit/push（等待用户显式指令）。

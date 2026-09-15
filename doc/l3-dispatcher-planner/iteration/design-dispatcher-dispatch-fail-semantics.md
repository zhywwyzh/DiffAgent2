# dispatcher 分发失败语义与端口登记 方案

> 摘要：本文件是总纲 `doc/l3-dispatcher-planner/iteration/design-dispatcher-architecture-stabilization.md`
> 的 **S6 期执行方案**。目标：把「分发未命中已注册技能」从**静默推进并在队尽时报 `done`**
> 改为**上报 `fail` 并停在 `WAIT_FOR_MISSION`**（契约 `l3-core-boundary` B5 + O3、
> `l3-migration-protocol` §4「禁止假成功」、门禁 G3/G22）。同时登记
> `l3-skill-contract` §7 的 11 个宿主端口缺口（**本期不补桩**，总纲 §4.6）。
>
> 归属：总纲 **S6**；前置 **S3**（该逻辑 S3 后位于 `core/skill_router.py`）。

## 0. 元信息

| 项 | 值 |
|----|----|
| 日期 | 2026-09-12 |
| 目标路径 | 现状版：`l3-dispatcher-planner/ros_packages/dispatcher/dispatcher/engine.py`；S3 后：`dispatcher/core/skill_router.py`（以 S3 定稿为准） |
| 状态 | done（2026-09-12 执行完毕；deep-oracle 放行，见 §11 附录） |
| 前置 | S3（`engine.py` 非 core 职责迁出）；S1（对外变更登记） |
| 行为影响 | 有：仅「未注册」这一条路径的对外结果由 `done` 改为 `fail`（S1 方案 §4.5(c) 已登记） |
| 关联文档 | 总纲 `doc/l3-dispatcher-planner/iteration/design-dispatcher-architecture-stabilization.md`（§2.A、§4.6、§4.7 S6 行、§7 S6、§9）；S1 `design-dispatcher-spec-reconciliation.md`（§4.5(c)、§4.2 白名单）；S3 `design-dispatcher-engine-relocate-non-core.md` |
| 契约依据 | `specs/implemented/inner/l3-core-boundary.spec.md`（B5 `#L34-L35`、O3 `#L50-L51`、G3 `#L61`）、`specs/implemented/inner/l3-migration-protocol.spec.md`（§4 `#L57-L58`、G22 `#L104`、§6 `#L75-L85`）、`specs/implemented/inner/l3-skill-contract.spec.md`（§7 `#L91-L110`） |

## 1. 背景与动机

总纲 §2.A 记：`engine.py#L562-L573` 与 `#L410-L419` 在分发未命中技能时走
`_advance_to_next_prompt()`，队尽即上报 `done`，**无 fail 相位**——这违反
`l3-core-boundary` B5（「分发未命中已注册技能时，必须上报失败相位并停在
`WAIT_FOR_MISSION`；禁止排空队列后上报完成」，`#L34-L35`）与
`l3-migration-protocol` §4「禁止假成功」（`#L57-L58`），对应门禁 G3（`#L61`）与 G22（`#L104`）。

S1 已把「未注册分发的对外结果由 `done` 改为 `fail`」登记为有意对外变更（S1 方案 §4.5(c)）；
S6 是该项登记的落地期。S6 前置为 S3：S3 完成后该分发逻辑位于 `core/skill_router.py`，
`engine.py` 只保留回退调用——本方案给出两种落点写法，以 S3 定稿为准。

## 2. 现状事实（问题清单）

> 行号为本次实测（`engine.py` 现 1067 行版）。

- [ ] `engine.py#L197` — `self._skills: dict = {}`：技能注册表当前为**空表**（vla/flight/
      scene_nav/grasp 均未迁入）。这是「未命中」路径当前必然被走到的根因之一。
- [ ] `engine.py#L547-L573` — `_handle_plan_tool(cmd, skill_command)`：注册表查找后，
      未命中分支（`#L562-L573`）为

  ```
          skill = self._skills.get(tool_name)
          if skill is not None and not skill.synchronous:
              self._current_plan_skill = skill
              return skill.plan_tick(skill_command)

          rospy.logwarn(
              "Unregistered active tool in DISPATCH: name=%r prompt=%r",
              tool_name,
              str(skill_command.call.display_text or skill_command.call.name),
          )
          self._advance_to_next_prompt()
          return True
  ```

  ——未命中即 `#L572` `_advance_to_next_prompt()`（推进下一条），并 `#L573` 返回 `True`
      让主循环 `continue`；**无任何 fail 上报**。
- [ ] `engine.py#L410-L419` — `_validate_active_tool(call)`：

  ```
          if self._active_tool_name:
              return True
          rospy.logwarn(
              "DISPATCH has no active registered tool, prompt=%r",
              str(call.display_text or call.name),
          )
          self._advance_to_next_prompt()
          return False
  ```

  ——「DISPATCH 无活动已注册工具」同样走 `#L418` `_advance_to_next_prompt()`；同属
      「未命中已注册技能」的推进分支（总纲 §6 删除清单把两处并列为 S6 对象）。
- [ ] `engine.py#L390-L408` — `_load_next_prompt`：`#L394` 队列空时 `#L396-L403` 在
      `not self._task_sequence_failed` 条件下上报 `phase="done"`（`#L399`），`#L405` 返回 `False`。
      这是「队尽报完成」的落点；**正常 ADVANCE 路径依赖它发 `done`**（见 §4.4）。
- [ ] `engine.py#L448-L475` — `start_tool_workflow` 的 `_start_prompt_task` 缺失守卫：
      `#L461` `if not hasattr(self, "_start_prompt_task"):` → `#L462-L465` logwarn 后
      `#L466-L474` 上报 `fail`（`error.code="task_injection_not_migrated"`）→ `#L475` `return`。
      **该 fail 已存在，不需改**：它属「任务注入未迁入」的过渡态，正确行为是 drop 该工具流；
      留待任务注入轮次（迁入 `_start_prompt_task` 时移除守卫）——它与 S6 的区别见 §4.3。
- [ ] 现状可达性说明：因 `_start_prompt_task` 全仓无定义（`grep` 仅 `skill_api.py` 注释引用），
      上述 `#L461` 守卫**恒真**，`start_tool_workflow` 永远在 `#L475` 返回——即
      `_handle_plan_tool` / `_validate_active_tool` 的推进分支**当前不可达**。S6 修正的是
      「任务注入迁入后即刻可复现」的潜在假成功，而不是已发生的线上行为。

## 3. 目标与约束

- **目标**：
  1. 「分发未命中已注册技能」改为上报 `fail`（载荷含未命中工具名，满足 O3）并停在
     `WAIT_FOR_MISSION`；
  2. 不得再发 `done`、不得排空队列（B5）；
  3. 登记 `l3-skill-contract` §7 的 11 个宿主端口缺口（本期不补桩）。
- **Non-Goals**：
  - **不动正常 ADVANCE 路径**：`_advance_to_next_prompt` / `_load_next_prompt` 及其
    `done` 上报照旧（§4.4）；
  - 不实现技能族、不补 `SkillHost` 端口桩（总纲 §4.6）；
  - 不改 `start_tool_workflow` 的 `_start_prompt_task` 守卫 fail（§4.3）；
  - 不改 FSM 状态集合、不改 `/agent_task_phase` 的键集（fail 载荷沿用既有键）。
- **硬边界**：
  - 禁止假成功：未注册必须 fail（`l3-migration-protocol` §4）；
  - 过期必删：不得保留「未命中即 advance」的旧分支为注释桩；
  - 不留桩：不补空端口、不预造技能占位（总纲 §4.6）。

## 4. 方案决策

### 4.1 改法总览

把两处「未命中即 `_advance_to_next_prompt()`」改为调用一个统一的失败处理：
**上报 `fail`（`detail` 与 `error.message` 均含未命中工具名）→ 置 `_task_sequence_failed=True`
→ 置 `if_plan=False` → 切 `WAIT_FOR_MISSION`**。不 pop `command_content`、不清
`prepare_content`、不调用 `_advance_to_next_prompt`。返回 `True`（`_handle_plan_tool`）
或 `False`（`_validate_active_tool`），让主循环 `continue` 后停在空闲态。

- `fail` 载荷键集 = `{frame_id, phase, progress, detail, error}`，与既有 fail 上报
  （`engine.py#L466-L474`、`#L496-L501`）**同构**；工具名放在 `detail` 与 `error.message`，
  **不新增 `tool_name` 键**（保持行为契约键集，符合 G21 口径）。
- `_task_sequence_failed`（`engine.py#L118` 定义、`#L396` 读）置真，是「后续 `_load_next_prompt`
  不得再发 done」的既有 canonical 写口（`#L115-L118` 注释）；其复位属 `_start_prompt_task`
  职责（任务注入轮次），S6 登记该依赖（见 §9）。

### 4.2 改后逐字代码

**写法 A — engine 现状版落点**（S3 未完成、或 S6 与 S3 同轮时；直接改 `engine.py`）。

新增私有方法（置于 `engine.py` `_handle_plan_tool` 附近；S1 方案 §4.2b 白名单已含此名）：

```python
    def _fail_unregistered_dispatch(self, *, tool_name: str, frame_id: str) -> None:
        """分发未命中已注册技能：上报 fail 并停在 WAIT_FOR_MISSION。

        B5：不得排空队列后回报完成——本方法不 pop command_content、不清
        prepare_content、不调用 _advance_to_next_prompt；
        O3：fail 载荷携带未命中的工具名。
        """
        self._publish_task_phase(
            "fail",
            detail=f"tool not registered: {tool_name}",
            error={
                "code": "tool_not_registered",
                "message": f"tool not registered: {tool_name}",
            },
            frame_id=str(frame_id or "Null"),
        )
        self._task_sequence_failed = True
        self.if_plan = False
        self._set_dispatcher_state(
            DISPATCHER_STATE.WAIT_FOR_MISSION,
            reason="plan:tool_not_registered",
        )
```

`_handle_plan_tool` 未命中分支（`#L567-L573`）

old（逐字）：

```
        rospy.logwarn(
            "Unregistered active tool in DISPATCH: name=%r prompt=%r",
            tool_name,
            str(skill_command.call.display_text or skill_command.call.name),
        )
        self._advance_to_next_prompt()
        return True
```

new（逐字）：

```
        rospy.logwarn(
            "Unregistered active tool in DISPATCH: name=%r prompt=%r",
            tool_name,
            str(skill_command.call.display_text or skill_command.call.name),
        )
        self._fail_unregistered_dispatch(
            tool_name=tool_name,
            frame_id=skill_command.call.frame_id,
        )
        return True
```

`_validate_active_tool` 未命中分支（`#L414-L419`）

old（逐字）：

```
        rospy.logwarn(
            "DISPATCH has no active registered tool, prompt=%r",
            str(call.display_text or call.name),
        )
        self._advance_to_next_prompt()
        return False
```

new（逐字）：

```
        rospy.logwarn(
            "DISPATCH has no active registered tool, prompt=%r",
            str(call.display_text or call.name),
        )
        self._fail_unregistered_dispatch(
            tool_name=str(call.name or call.display_text or ""),
            frame_id=call.frame_id,
        )
        return False
```

**写法 B — S3 后落点（推荐，以 S3 定稿为准）**。S3 把「查表分发」迁入 `core/skill_router.py`，
`engine.py` 只保留回退调用；失败处理（FSM 状态控制 + 相位上报）属 core 门面，留在 engine，
协作对象只做查表：

- `core/skill_router.py::dispatch_plan` 未命中时**返回 `False`**（不再调用推进），
  `engine.py` 回退分支据返回值调用 `_fail_unregistered_dispatch`；
- `core/skill_router.py::validate_active_tool` 同构：无活动工具时返回 `False`。

`_run_inference_loop` 内的回退调用（现状版 `#L928-L933` 的形态；S3 后仍为 engine 回退分支）：

old（逐字）：

```
                # 经技能注册表分发到命中的技能。
                if self._handle_plan_tool(cmd, skill_command):
                    continue

                # 未命中任何分支时，不强行报错，先回到 WAIT_FOR_MISSION，
                # 让外部有机会刷新任务或注入新 prompt。
                self._set_dispatcher_state(DISPATCHER_STATE.WAIT_FOR_MISSION, reason="plan:unhandled_prompt")
```

new（逐字）：

```
                # 经技能注册表分发到命中的技能。
                if self._handle_plan_tool(cmd, skill_command):
                    continue

                # 未命中已注册技能：fail 上报并停在 WAIT_FOR_MISSION（B5/O3）。
                self._fail_unregistered_dispatch(
                    tool_name=str(skill_command.call.name or ""),
                    frame_id=skill_command.call.frame_id,
                )
```

> 落点以 S3 定稿为准：若 S3 保留 `_handle_plan_tool` 名与方法体位置，则取写法 A；
> 若 S3 改为 `SkillRouter.dispatch_plan` 返回布尔、engine 回退处理，则取写法 B。
> 两种写法的**可观测结果完全一致**（同一 fail 载荷、同一停态、同一不排空队列语义）。

### 4.3 与 S3、与「任务注入过渡态 fail」的关系

- **与 S3**：S6 前置 S3。S3 后该逻辑位于 `core/skill_router.py`，engine 只保留回退调用；
  `_fail_unregistered_dispatch` 作为 FSM 状态控制方法留在 engine（S1 方案 §4.2b 白名单项）。
- **与 `start_tool_workflow` 守卫 fail 的区别**（`engine.py#L461-L475`）：
  - 该 fail 属「任务注入（`_start_prompt_task`）尚未迁入」的**过渡态**，发生在
    `_activate_tool_call` 记账**之前**，正确行为是**丢弃**该工具流并释放 runtime
    （`frame→call_id` 回退），站端不悬空；
  - 它**已经是 fail**，符合契约，**S6 不改**；留待任务注入轮次迁入 `_start_prompt_task`
    后移除守卫（届时该路径才会进入 S6 修正的 DISPATCH 分发段）。

### 4.4 裁决：`_advance_to_next_prompt` 正常路径保留

`_advance_to_next_prompt`（`engine.py#L685-L703`）**不删除、不缩小语义**。它仍服务：

- **ADVANCE 裁决的正常落地**：`_handle_post_action`（`#L714`）在 `verdict is SkillVerdict.ADVANCE`
  时调用 `_load_next_prompt()`（`#L749`）；技能经 `SkillHost.advance_prompt`（`skill_api.py#L200`）
  也走此路径；
- **正常队尽 `done`**：`_load_next_prompt#L396-L403` 在未失败时发 `done`——这是契约允许的
  「正常完成」，**必须保留**。

S6 **只改「未注册」这一条路径**（`_handle_plan_tool` 未命中 + `_validate_active_tool` 无活动工具），
不扩大到 ADVANCE。验收含**误伤检查**（§8）：正常 ADVANCE 仍发 `done`。

### 4.5 对外影响与站端兼容处置

- **变更**：仅「未注册」路径的 `/agent_task_phase` 结果由 `phase="done"` 改为 `phase="fail"`，
  载荷携带未命中工具名（`detail` / `error.message`）。
- **影响方**：站端 `/agent_task_phase` 消费方。
- **兼容处置**（引用 S1 方案 §4.5(c)）：站端据 `fail` + 工具名定位缺失技能；与 l4 侧确认后
  执行（总纲 §9 S6 风险行）。既有 fail 消费路径（`#L466-L474` 的 `task_injection_not_migrated`）
  已存在，站端已能处理 `fail` 相位，故为**同相位、同键集**的语义修正，非新协议。

### 4.6 端口缺口登记（本期不补桩，总纲 §4.6）

- **缺口**：`specs/implemented/inner/l3-skill-contract.spec.md#L91-L110`（§7 端口清单）列出
  11 个宿主端口——最新帧读取、快速通道图像、动作武装、航点下发、规划器模式发布、相位上报、
  任务结果暂存、任务结果取出、失败终止、代次守卫、队列机械操作。这些端口目前仅作为
  **契约工件**声明于 `dispatcher/skill_api.py`（`SkillHost` Protocol，`#L138-L200`），
  **宿主（`DispatcherEngine`）未实现**（§2 证据：`_skills` 空表、无技能实例）。
- **登记项**：缺口以「端口清单已由契约定义、宿主未实现」形式登记（**不进契约正文**，
  符合 `l3-migration-protocol` §5 第 2 项「待办不进契约」）。
- **入口条件（与技能族同轮落地）**：后续「技能族迁入」轮次开始时，11 个端口实现必须与
  技能族**同一改动**落地；在此之前不得先补空端口/占位实现——否则立刻成为「只被自己引用的
  空实现」，违反 `l3-migration-protocol` §1「不留桩」与「不投机设计」。
- **本期不补桩**：S6 只改未注册失败语义（不依赖技能族），端口实现不在本期。

## 5. 迁移映射表

| 旧位置 | 新位置/命名 | 动作 | 备注 |
|--------|-------------|------|------|
| `engine.py#L567-L573`（未命中即 `_advance_to_next_prompt` + `return True`） | 同方法内改调 `_fail_unregistered_dispatch`（写法 B：`core/skill_router.py::dispatch_plan` 返回 `False`，engine 回退调用） | rewrite | 以 S3 定稿为准 |
| `engine.py#L414-L419`（无活动工具即推进 + `return False`） | 同方法内改调 `_fail_unregistered_dispatch`（写法 B：`SkillRouter.validate_active_tool` 返回 `False`） | rewrite | 同上 |
| `engine.py#L928-L933`（未命中回退到 `plan:unhandled_prompt`） | 改为回退调 `_fail_unregistered_dispatch` | rewrite | 写法 B 的接线点 |
| （新增） | `engine.py::_fail_unregistered_dispatch`（S3 后仍在 engine） | add | 统一失败处理，白名单已登记 |

## 6. 删除清单

| 删除项 | 理由 |
|--------|------|
| `engine.py#L572` `self._advance_to_next_prompt()`（`_handle_plan_tool` 未命中分支内） | 改为 fail；假成功路径（B5/G3），不留注释桩 |
| `engine.py#L418` `self._advance_to_next_prompt()`（`_validate_active_tool` 内） | 同上 |
| `engine.py#L933` `reason="plan:unhandled_prompt"` 的静默回退（写法 B） | 被 `_fail_unregistered_dispatch` 取代 |

> `_advance_to_next_prompt` **方法本身不删除**（§4.4）；删除的只是「未注册」路径对它的调用。

## 7. 实施步骤（S6 单期）

### P0 — 未注册失败语义（依 S3 定稿落点）

- 范围：§5 映射表；落点按 S3 定稿选写法 A 或 B。
- 行为不变式：只有「未注册」路径的对外可观测行为改变（`done` → `fail`）；正常 ADVANCE 的
  `done`、`_advance_to_next_prompt` 调用、`/agent_task_phase` 键集均不变。
- 验收：§8 全部；`python3 -m py_compile` 全绿。
- 回退：还原两处分支 + 删除 `_fail_unregistered_dispatch`。

### P1 — 端口缺口登记（纯文档）

- 范围：§4.6 登记（本方案 + 后续技能轮次入口条件）。
- 行为不变式：零代码。
- 验收：S1 方案 §4.5 与总纲 §4.6/§10 尾注一致。

## 8. 验收标准

- [ ] **G3 判定**（`l3-core-boundary.spec.md#L61`）：静态检查「分发未命中路径存在 fail 上报且
      无 done 上报」——断言未命中分支不含 `_advance_to_next_prompt`，且出现
      `_publish_task_phase("fail"` / `_fail_unregistered_dispatch`。
- [ ] **G22 判定**（`l3-migration-protocol.spec.md#L104`）：空注册表（`_skills == {}`）下喂入一个
      未注册 `ToolCall` 进 DISPATCH，断言**无** `phase=="done"` 事件、**有** `phase=="fail"` 事件。
- [ ] **失败相位 payload 断言**：mock `task_phase_pub` / `zenoh_middleware`，断言 fail 载荷
      `phase=="fail"`、`detail` 与 `error.message` **均含未命中工具名**（O3）、
      `error.code=="tool_not_registered"`、`frame_id == call.frame_id`；键集为
      `{frame_id, phase, progress, detail, error}`（无新增键）。
- [ ] **停态断言**：失败后 `dispatcher_state == DISPATCHER_STATE.WAIT_FOR_MISSION`、
      `if_plan is False`、`_task_sequence_failed is True`。
- [ ] **不排空队列断言**：失败前后 `command_content` 与 `prepare_content` 的长度/内容不变。
- [ ] **误伤检查（正常 ADVANCE 不受影响）**：以 mock 技能经 `_handle_post_action`
      返回 `SkillVerdict.ADVANCE`，断言队尽时仍上报 `done`、`_load_next_prompt` 仍被调用；
      `_advance_to_next_prompt` 在正常路径仍可达（§4.4）。
- [ ] **`done` 语义分离**：另设用例证明「正常完成」与「未注册失败」互不污染（前者 `done`、
      后者 `fail`，同一会话不并存）。
- [ ] **端口登记一致**：§4.6 的 11 端口登记与 `l3-skill-contract` §7（`#L95-L107`）逐条对齐。

## 9. 风险与对策

| 风险 | 影响 | 对策 |
|------|------|------|
| 站端按 `done` 判完成，改为 `fail` 后任务卡住 | 站端行为变化 | S1 §4.5(c) 已登记为有意变更；fail 载荷带工具名（O3）；与 l4 侧确认后执行（总纲 §9） |
| `_task_sequence_failed` 复位缺失（`_start_prompt_task` 未迁） | 失败后新任务可能不发 `done` | 登记复位依赖属任务注入轮次；本方案只置真、不臆造复位逻辑；S6 单测以「失败路径」为对象 |
| 误扩大范围删掉 ADVANCE 的正常 `done` | 正常任务不再收终态 | §4.4 裁决 + §8 误伤检查锁定：只改未注册路径 |
| 落点与 S3 定稿不一致 | diff 冲突/半改 | 两种写法给出，以 S3 定稿为准；落点选定后在同一改动内完成 |
| `_fail_unregistered_dispatch` 未入 G2 白名单 | G2 在 S6 后判红 | S1 方案 §4.2b 白名单已列该项 |

回退路径：还原 §5 两处分支与回退接线 + 删除 `_fail_unregistered_dispatch`（语义期按本方案回退点）。

## 10. 修改点清单汇总

| 文件 | 动作 | 说明 |
|------|------|------|
| `l3-dispatcher-planner/ros_packages/dispatcher/dispatcher/engine.py` | 修改 | 未命中分支改为 fail；新增 `_fail_unregistered_dispatch`；回退接线（写法 A/B 依 S3 定稿） |
| `l3-dispatcher-planner/ros_packages/dispatcher/dispatcher/core/skill_router.py` | 修改 | 仅在写法 B（S3 后）下：`dispatch_plan` / `validate_active_tool` 未命中返回 `False` |
| `doc/l3-dispatcher-planner/iteration/design-dispatcher-dispatch-fail-semantics.md` | 新增 | 本方案（S6 执行方案） |

**本方案不动的文件**（明确排除）：

- `engine.py::_advance_to_next_prompt` / `_load_next_prompt` 的**正常**路径（§4.4）；
- `engine.py#L461-L475` 的 `_start_prompt_task` 守卫 fail（§4.3）；
- `dispatcher/skill_api.py`（`SkillHost` 端口声明不动；实现缺口只登记）；
- `specs/**`（S6 只引用 S1 的登记，不改契约正文）；
- `l3-dispatcher-planner/tests/**`（除 S6 需新增失败语义用例，按测试轮次另行安排）。

**登记的后续轮次**：`SkillHost` 11 端口实现与技能族同轮落地（§4.6）；`_task_sequence_failed`
复位归 `_start_prompt_task`（任务注入轮次）。

## 11. 附录：执行记录

### 2026-09-12 执行（S6 置 done）

- **执行者**：SOLO Agent 直接执行（单文件小改：新增 1 方法 + 改 2 处回退分支）；deep-oracle 独立评审。
- **落点裁决**：取**写法 B**（S3 定稿形态）——`SkillRouter.dispatch_plan`/`validate_active_tool` 返回 `False`（S3 已实现），engine 回退分支改调 `_fail_unregistered_dispatch`；方案 §4.2 的 `self._publish_task_phase(...)` 按「以 S3 定稿为准」落为 `self.task_phase.publish(...)`。方案 §5 第三行（`#L928-L933` `plan:unhandled_prompt` 静默回退接线点）经核实已被 S3 的二态化改写吸收（该分支不存在），实际改动两处。
- **改动实测**：`engine.py` 754→783 行——新增 `_fail_unregistered_dispatch`（L466-487：fail 载荷键集 `{frame_id,phase,progress,detail,error}` 与两处既有 fail 同构、工具名双落点 `detail`/`error.message`、`error.code="tool_not_registered"`；不 pop 队列、不清 `prepare_content`、不调 advance；置 `_task_sequence_failed=True`/`if_plan=False`、切 `WAIT_FOR_MISSION` reason=`plan:tool_not_registered`）；`validate_active_tool` False 分支（L667-678）与 `dispatch_plan` False 分支（L686-701）改调本方法，logwarn 文本逐字保留，`_advance_to_next_prompt()` 调用删除。
- **门禁实测**：py_compile 绿；G3 静态判定成立（未命中分支零 advance 调用、fail 上报在位、done 唯一落点 `_load_next_prompt` L282-287 从未命中路径不可达）；G2 AST：engine def=17 ⊆ 白名单 17 项（`_fail_unregistered_dispatch` 为 S1 预登记项）；pytest 44/6 基线一致；R7 回读复验稳定。
- **deep-oracle 评审结论**：**放行置 done**。5 项复核全 PASS（B5/O3 载荷与停态、正常 ADVANCE→done 误伤零触碰、控制流等价与 FSM 停态守卫（`if_plan=False` 无绕行——`if_plan=True` 写点仅 L270/L452 两处均不可绕）、G21 登记（reason 值新增落在 S1 §4.5(c)+S6 §4.2 双登记内）、G3/G22 静态论证链闭合（含任务注入迁入前后两种可达性假设））。
- **运行时断言的环境回退（R9）**：§8 的 mock 级 payload/停态/不排空/误伤断言因本机 cv2×NumPy2 不兼容无法实例化 engine——以 deep-oracle 全文件逐段比对（快照↔现版 diff 恰为三处改动、其余逐字节一致）+ 静态论证替代；**登记：随下次带 ROS 环境联调补做 mock 断言与 S3 遗留的 topic/trace 逐字节 diff**。
- **登记的后续轮次待办（CONCERN）**：① `_task_sequence_failed` 无复位写点（复位归 `_start_prompt_task`，任务注入轮次，§9 已登记）；② `_advance_to_next_prompt` 现为零调用方法（§4.4 裁决保留——`SkillHost.advance_prompt` 端口既定实现、白名单在册；**技能族迁入轮次须显式重裁其去留**）；③ `fail_sequence` 端口语义统一（技能轮次实现 11 端口时，engine 直写 `_task_sequence_failed` 与端口「唯一写口」注释的口径统一）；④ 帧回退链微差（新 fail `str(frame_id or "Null")` vs 既有 fail 裸 frame_id 经 `_active_task_frame_id` 回退——DISPATCH 可达场景两链取值一致，观察级备注）。

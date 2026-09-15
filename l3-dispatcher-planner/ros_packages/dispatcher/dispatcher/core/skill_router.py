"""技能注册表与分发（S3 方案 §2.6/§5/§4.10）：策略分发的查表职责。

自 engine.py 迁出。§4.10 冻结接口：dispatch_plan / validate_active_tool
只做查表判定并返回 bool——False=未命中，不自行推进、不发任何相位；
未命中的回退动作（logwarn + _advance_to_next_prompt）留在 engine 侧保持
现状行为，S6 起改走 _fail_unregistered_dispatch（不在本轮实现）。
当前注册表恒空（技能族未随 S3 迁移），全部走未命中回退路径，与迁移前
行为等价；后续轮次技能迁入时经 register 恢复注册。
"""

from __future__ import annotations

from typing import Callable

from dispatcher.tools.model import SkillCommand, ToolCall


class SkillRouter:
    """技能注册表：注册/查表/分发/归属快照/结果暂存。"""

    def __init__(self, active_tool_name: Callable[[], str]) -> None:
        # 当前激活工具名取值缝（_active_tool_name 字段的读取回调；router
        # 不回引 engine/workflow 对象本身——S3 §9「经注入回调工作」）
        self.active_tool_name = active_tool_name
        self._task_result_stash = None  # 技能暂存的任务级结果（stash/pop_task_result 端口背后字段）
        # P3.4 动作归属绑定（patch 20/21 note b 修复）：完成门/verdict 挂到
        # 「发布该动作的技能实例」上，而非 _active_tool_name 字符串解析
        self._current_plan_skill = None  # 本轮 DISPATCH 分发命中的技能
        self._action_owner_skill = None  # 进入 WAIT_ACTION_FINISH 时的技能快照
        # P3 技能注册表（本轮迁入为空表：vla/flight/scene_nav/grasp 技能族
        # 未随本轮迁移，dispatch_plan/owner_skill 的注册表查找按原 None
        # 守卫走通用回退路径；后续轮次技能迁入时经 register 恢复注册）。
        self._skills: dict = {}

    def register(self, name: str, skill) -> None:
        """注册技能实例（技能族迁入轮次的注册入口，S3 起登记、暂无调用方）。"""
        self._skills[name] = skill

    def get(self, name: str):
        """按工具名查注册表。"""
        return self._skills.get(name)

    def dispatch_plan(self, cmd, skill_command: SkillCommand) -> bool:
        """Continue the active registered tool through its workflow adapter.

        §4.10 冻结接口：True=已处理（engine continue）；False=未命中，
        不自行推进、不发任何相位（回退由 engine 侧执行）。
        """
        # P3.8：技能解析键直接取随 prompt 穿越队列的原生 ToolCall.name
        # （normalize_call 保证恒非空；原 SkillCommand.tool_name 字段已删除，
        # or 链仅为形式保留——_active_tool_name 兜底永不可达）
        tool_name = str(skill_command.call.name or self.active_tool_name() or "")
        # P3.4：本轮 DISPATCH 分发命中技能复位；命中注册表技能时记录实例，供
        # arm_action 快照为 _action_owner_skill（完成门/verdict 归属）
        self._current_plan_skill = None

        # P3 技能注册表分发：异步技能（flight.* → FlightSkill，P3.2；
        # scene.* → SceneNavSkill，P3.3；navigation.vla_reach → VlaSkill，
        # P3.4）经 plan_tick 推进；同步技能（graph.*）不入队，永不走到
        # 这里（synchronous 守卫）
        skill = self._skills.get(tool_name)
        if skill is not None and not skill.synchronous:
            self._current_plan_skill = skill
            return skill.plan_tick(skill_command)

        return False

    def validate_active_tool(self, call: ToolCall) -> bool:
        """Reject DISPATCH work that did not originate from the registered runtime.

        §4.10 冻结接口：True=通过；False=未命中（不推进，回退由 engine 执行）。
        """
        if self.active_tool_name():
            return True
        return False

    def owner_skill(self):
        """动作归属技能：_action_owner_skill 快照优先，注册表名解析回退。"""
        owner = self._action_owner_skill
        if owner is None:
            owner = self._skills.get(str(self.active_tool_name() or ""))
        return owner

    def snapshot_owner(self) -> None:
        """arm_action 轮次的归属快照口（S3 登记接口，暂无调用方）。"""
        self._action_owner_skill = self._current_plan_skill

    def stash_task_result(self, result: dict) -> None:
        """技能暂存任务级结果（SkillHost stash 端口，技能轮次接入）。"""
        self._task_result_stash = result

    def pop_task_result(self):
        """SkillHost 任务结果口：取走并清空暂存的任务级结果。"""
        result = self._task_result_stash
        self._task_result_stash = None
        return result

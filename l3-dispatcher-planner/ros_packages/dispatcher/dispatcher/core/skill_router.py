"""按调用名注册与分发，动作归属保持发布时的技能实例快照。"""

from __future__ import annotations

from typing import Callable

from dispatcher.tool_plane.model import SkillCommand, ToolCall


class SkillRouter:
    """技能注册表：注册/查表/分发/归属快照/结果暂存。"""

    def __init__(self, active_tool_name: Callable[[], str]) -> None:
        self.active_tool_name = active_tool_name
        self._task_result_stash = None  # 技能暂存的任务级结果（stash/pop_task_result 端口背后字段）
        self._current_plan_skill = None  # 本轮 DISPATCH 分发命中的技能
        self._action_owner_skill = None  # 进入 WAIT_ACTION_FINISH 时的技能快照
        self._skills: dict = {}

    def register(self, name: str, skill):
        """返回只撤销本次注册的幂等逆操作，不影响后注册实例。"""
        self._skills[name] = skill
        disposed = False

        def dispose():
            nonlocal disposed
            if disposed:
                return
            skill.on_cancel()
            if self._skills.get(name) is skill:
                self._skills.pop(name, None)
            disposed = True

        return dispose

    def get(self, name: str):
        """按工具名查注册表。"""
        return self._skills.get(name)

    def dispatch_plan(self, skill_command: SkillCommand) -> bool:
        """按原始调用名查表，False 由核心统一上报失败。"""
        tool_name = skill_command.call.name
        self._current_plan_skill = None

        skill = self._skills.get(tool_name)
        if skill is not None and not skill.synchronous:
            self._current_plan_skill = skill
            return skill.plan_tick(skill_command)

        return False

    def validate_active_tool(self, call: ToolCall) -> bool:
        """检查队首调用确实属于当前激活的已注册技能。"""
        return call.name == self.active_tool_name() and self.get(call.name) is not None

    def owner_skill(self):
        """动作归属只读取发布时的实例快照。"""
        return self._action_owner_skill

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

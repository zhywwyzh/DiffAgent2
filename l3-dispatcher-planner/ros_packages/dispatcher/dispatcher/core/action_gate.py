"""动作完成门与四裁决；动作代次和待发布上下文归本对象所有。"""

import time
from dataclasses import dataclass
from typing import Any

from dispatcher.tools.skill_api import SkillVerdict
from dispatcher.utils.state import DISPATCHER_STATE


@dataclass
class PendingAction:
    """待发布动作上下文。"""

    waypoint: Any = None  # 待发布航点（xyz 或 xyzrpy）
    look_forward: bool = True  # 发布动作时是否朝向前进方向
    replan_cmd: Any = None  # 执行完成后用于重规划的命令
    replan_reason: Any = None  # 执行完成后用于重规划的原因
    action_name: str = ""  # 发布动作日志名称
    prompt_raw: str = ""  # 原始 prompt
    instruction_type: Any = None  # 动作发布类型，默认走 TURN_GOAL
    nav_yaw: Any = None  # 到达 waypoint 后执行的 terminal yaw
    yaw_source: str = "unspecified"  # 最终下发 yaw 的来源
    is_far_push: bool = False  # 是否为远/稀疏目标的推进动作（触发 reacquire 重搜）

    def clear(self) -> None:
        """重置待发布动作上下文。"""
        self.waypoint = None
        self.look_forward = True
        self.replan_cmd = None
        self.replan_reason = None
        self.action_name = ""
        self.prompt_raw = ""
        self.instruction_type = None
        self.nav_yaw = None
        self.yaw_source = "unspecified"
        self.is_far_push = False


class ActionGate:
    def __init__(self, *, runlog, skills, ledger, queue,
                 if_plan_set,
                 action_progress_get, action_progress_set,
                 action_finish_get, action_finish_set, action_start_time_get,
                 min_action_wait_get):
        self.runlog = runlog
        self.skills = skills
        self.ledger = ledger
        self.queue = queue
        self.if_plan_set = if_plan_set
        self.action_progress_get = action_progress_get
        self.action_progress_set = action_progress_set
        self.action_finish_get = action_finish_get
        self.action_finish_set = action_finish_set
        self.action_start_time_get = action_start_time_get
        self.min_action_wait_get = min_action_wait_get
        self._action_generation = 0
        self._action_finish_generation = -1
        self._last_action_result = None
        self.pending_action = PendingAction()

    def action_done(self) -> bool:
        """基于动作所属技能的完成门、结果代次和最小等待时间判定完成。"""
        if self.action_progress_get():
            gate_skill = self.skills.owner_skill()
            if gate_skill is not None:
                gate_verdict = gate_skill.action_done_gate()
                if gate_verdict is not None:
                    return gate_verdict

        if not self.action_finish_get():
            return False
        # 拒绝旧代次的 action result（任务切换/新动作发布会增代）
        if self._action_finish_generation != self._action_generation:
            self.runlog.info(
                "[ActionDone] reject stale action result (gen=%d != current=%d)",
                self._action_finish_generation,
                self._action_generation,
            )
            self.runlog.emit(
                "info",
                "task_action_result_ignored",
                reason="stale_generation",
                result_generation=self._action_finish_generation,
                action_generation=self._action_generation,
            )
            self.action_finish_set(False)
            return False
        if time.time() - float(self.action_start_time_get()) < float(self.min_action_wait_get()):
            return False
        return True


    def handle_post_action(self) -> None:
        """机械执行所属技能的四裁决；缺少归属或非法裁决交由核心失败自愈。"""
        owner = self.skills.owner_skill()
        if owner is None:
            raise RuntimeError(f"action owner missing: {self.skills.active_tool_name()}")
        verdict = owner.on_action_result(self._last_action_result)
        if verdict not in tuple(SkillVerdict):
            raise ValueError(f"invalid skill verdict: {verdict!r}")

        if verdict is SkillVerdict.REPLAN:
            self.pending_action.replan_cmd = None
            self.pending_action.replan_reason = None
            self.ledger.set_state(DISPATCHER_STATE.DISPATCH, reason="post_action:replan")
            self.if_plan_set(True)
            return

        if verdict is SkillVerdict.NEW_ACTION:
            return

        if verdict is SkillVerdict.ADVANCE:
            if self.queue.load_next_prompt():
                self.ledger.set_state(DISPATCHER_STATE.DISPATCH, reason="post_action:advance")
            else:
                self.ledger.set_state(DISPATCHER_STATE.WAIT_FOR_MISSION, reason="post_action:queue_finished")
            return

        if not self.ledger.failed:
            pending = self.skills.pop_task_result()
            self.queue.task_phase.publish(
                "done", detail="skill finished",
                result=dict(pending) if isinstance(pending, dict) else None,
            )
        self.if_plan_set(False)
        self.ledger.set_state(DISPATCHER_STATE.WAIT_FOR_MISSION, reason="post_action:no_advance_ready")


    def clear_action_state(self) -> None:
        self.pending_action.clear()
        self.action_progress_set(False)
        self.action_finish_set(False)
        self._action_generation += 1
        self._action_finish_generation = -1
        self._last_action_result = None

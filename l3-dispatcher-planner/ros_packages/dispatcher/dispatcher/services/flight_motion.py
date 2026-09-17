"""飞行动作共用生命周期，具体技能只负责目标生成。"""
from dispatcher.tools.skill_api import SkillBase, SkillVerdict


class FlightMotion(SkillBase):
    def __init__(self, host):
        super().__init__(host)
        self._goals = iter(())
        self._result = None

    def begin(self, goals):
        self._goals = iter(goals)
        self._result = None
        self._host.start_goal(self, next(self._goals))

    def wait_action_tick(self):
        try:
            self._result = self._host.poll_result()
        except Exception as exc:
            self._host.fail_sequence(str(exc))

    def action_done_gate(self):
        return self._result is not None

    def on_action_result(self, result):
        if result is None or not result.success:
            self._host.fail_sequence(result.reason if result else 'missing_result')
            return SkillVerdict.IDLE
        goal = next(self._goals, None)
        if goal is not None:
            self._result = None
            self._host.start_goal(self, goal)
            return SkillVerdict.NEW_ACTION
        self._host.stash_task_result({'completion': 'action_result'})
        return SkillVerdict.IDLE

    def on_cancel(self):
        self._host.cancel_execution(self)
        self._goals = iter(())
        self._result = None

    def on_global_stop(self):
        self.on_cancel()

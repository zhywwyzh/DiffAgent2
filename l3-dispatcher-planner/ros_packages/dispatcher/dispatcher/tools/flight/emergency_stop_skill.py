"""emergency_stop 命令的同步转交；不宣称下游物理动作完成。"""
from dispatcher.tools.skill_api import SkillBase


class EmergencyStopSkill(SkillBase):
    name = 'basic_flight.emergency_stop'
    requires_perception = False
    synchronous = True

    def on_start(self, command):
        try:
            self._host.request_safety_stop()
            self._host.publish_phase('done', result={'completion': 'forwarded'})
        except Exception as exc:
            self._host.fail_sequence(str(exc))

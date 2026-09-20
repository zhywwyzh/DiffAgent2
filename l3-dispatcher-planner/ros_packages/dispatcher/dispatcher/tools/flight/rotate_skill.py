"""有符号偏航分段执行，跨圈不取模丢失动作。"""
import math
from dispatcher.tools.flight.motion import FlightMotion
from dispatcher.execution.ports import Goal


class RotateSkill(FlightMotion):
    name = 'basic_flight.rotate'
    requires_perception = False
    synchronous = False

    def plan_tick(self, command):
        try:
            state = self._host.state()
            degrees = command.call.arguments['yaw_delta_deg']
            if abs(degrees) > self._host.config.max_rotation_deg:
                raise ValueError('rotation_budget_exceeded')
            segments = max(1, math.ceil(abs(degrees) / 90))
            delta = math.radians(degrees) / segments
            self.begin(Goal(state.position, state.yaw + delta * index)
                       for index in range(1, segments + 1))
        except Exception as exc:
            self._host.fail_sequence(str(exc))
        return True

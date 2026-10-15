"""按调用时机体水平朝向构造平移目标。"""
import math
from dispatcher.tools.flight.motion import FlightMotion
from dispatcher.execution.ports import Goal


class TranslateSkill(FlightMotion):
    name = 'basic_flight.translate'
    requires_perception = False
    synchronous = False

    def plan_tick(self, command):
        try:
            state = self._host.state()
            forward, left = {'forward': (1, 0), 'backward': (-1, 0),
                             'left': (0, 1), 'right': (0, -1)}[command.call.arguments['direction']]
            distance = command.call.arguments['distance_m']
            x, y, z = state.position
            cosine, sine = math.cos(state.yaw), math.sin(state.yaw)
            self.begin([Goal((x + distance * (forward*cosine - left*sine),
                              y + distance * (forward*sine + left*cosine), z), state.yaw)])
        except Exception as exc:
            self._host.fail_sequence(str(exc))
        return True

"""空参返回本飞行会话起飞点的水平位置，不自动降落。"""
from dispatcher.services.flight_motion import FlightMotion
from dispatcher.tools.flight.ports import Goal


class ReturnSkill(FlightMotion):
    name = 'basic_flight.return'
    requires_perception = False
    synchronous = False

    def plan_tick(self, command):
        try:
            state = self._host.state()
            x, y, _ = self._host.origin()
            self.begin([Goal((x, y, state.position[2]), state.yaw)])
        except Exception as exc:
            self._host.fail_sequence(str(exc))
        return True

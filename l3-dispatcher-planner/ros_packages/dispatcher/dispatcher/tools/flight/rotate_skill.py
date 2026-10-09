"""分段旋转并用连续解缠的实际偏航核对有符号累计角。"""
import math
from dispatcher.tools.flight.motion import FlightMotion
from dispatcher.tools.skill_api import SkillVerdict
from dispatcher.execution.ports import Goal


class RotateSkill(FlightMotion):
    name = 'basic_flight.rotate'
    requires_perception = False
    synchronous = False

    def __init__(self, host):
        super().__init__(host)
        self._previous_state = None
        self._rotation_rad = 0.0
        self._segment_delta = 0.0
        self._completed_segments = 0

    def plan_tick(self, command):
        try:
            state = self._host.state()
            degrees = command.call.arguments['yaw_delta_deg']
            if abs(degrees) > self._host.config.max_rotation_deg:
                raise ValueError('rotation_budget_exceeded')
            segments = max(1, math.ceil(abs(degrees) / 90))
            self._segment_delta = math.radians(degrees) / segments
            self._previous_state = state
            self._rotation_rad = 0.0
            self._completed_segments = 0
            self.begin(Goal(state.position, state.yaw + self._segment_delta * index,
                            yaw_low_speed=True)
                       for index in range(1, segments + 1))
        except Exception as exc:
            self._host.fail_sequence(str(exc))
        return True

    def _observe_rotation(self):
        state = self._host.state()
        previous = self._previous_state
        if previous is None:
            raise RuntimeError('rotation_observation_missing')
        dt = state.source_stamp - previous.source_stamp
        if dt < 0 or dt > self._host.config.state_timeout:
            raise RuntimeError('rotation_observation_gap')
        if dt == 0:
            return
        # 低速分段要求观测能够区分相邻采样间的旋转方向。
        if state.yaw_rate_rad_s is None or previous.yaw_rate_rad_s is None:
            raise RuntimeError('rotation_observation_missing')
        if max(abs(state.yaw_rate_rad_s), abs(previous.yaw_rate_rad_s)) * dt >= math.pi:
            raise RuntimeError('rotation_observation_ambiguous')
        delta = state.yaw - previous.yaw
        self._rotation_rad += math.atan2(math.sin(delta), math.cos(delta))
        self._previous_state = state

    def wait_action_tick(self):
        try:
            self._observe_rotation()
            self._result = self._host.poll_result()
        except Exception as exc:
            self._host.fail_sequence(str(exc))

    def on_action_result(self, result):
        if result is None or not result.success:
            return super().on_action_result(result)
        try:
            self._observe_rotation()
            self._completed_segments += 1
            expected = self._segment_delta * self._completed_segments
            if abs(self._rotation_rad - expected) > math.radians(self._host.config.settle_yaw_deg):
                raise RuntimeError('rotation_angle_not_reached')
            return super().on_action_result(result)
        except Exception as exc:
            self._host.fail_sequence(str(exc))
            return SkillVerdict.IDLE

    def on_cancel(self):
        try:
            super().on_cancel()
        finally:
            self._previous_state = None
            self._rotation_rad = 0.0
            self._completed_segments = 0

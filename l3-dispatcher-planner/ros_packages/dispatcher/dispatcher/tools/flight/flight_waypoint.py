"""共享单目标执行：批次只关联动作反馈，不识别工具名字。"""
import math
import secrets
import threading
import time
from dispatcher.execution.ports import ActionResult, FlightConfig, FlightPorts, Goal


class FlightWaypointExecution:
    def __init__(self, ports: FlightPorts, config: FlightConfig, *, clock=time.monotonic, first_batch=None):
        self.ports = ports
        self.config = config
        self.clock = clock
        self._batch = first_batch if first_batch is not None else secrets.randbelow(2**31) + 1
        self._active = None
        self._hold_pending = False
        self._started = 0.0
        self._goal = None
        self._planner_done = False
        self._previous_state = None
        self._settle_since = None
        self._lock = threading.RLock()

    def state(self):
        state = self.ports.snapshot()
        if state is None:
            raise RuntimeError('odometry_unavailable')
        age = self.clock() - state.received
        if not 0 <= age <= self.config.state_timeout or not 0 <= state.source_age + age <= self.config.state_timeout or state.source_age < 0:
            raise RuntimeError('odometry_stale')
        if state.frame != self.config.world_frame:
            raise RuntimeError('odometry_frame_mismatch')
        if not all(math.isfinite(v) for v in (*state.position, state.yaw, state.speed)):
            raise RuntimeError('odometry_invalid')
        if not all(math.isfinite(v) for v in (state.source_stamp, state.received, state.source_age)):
            raise RuntimeError('odometry_invalid')
        if state.velocity is not None and (
            len(state.velocity) != 3 or not all(math.isfinite(v) for v in state.velocity)
        ):
            raise RuntimeError('odometry_invalid')
        if state.yaw_rate_rad_s is not None and not math.isfinite(state.yaw_rate_rad_s):
            raise RuntimeError('odometry_invalid')
        return state

    def start(self, goal: Goal):
        with self._lock:
            if self._active is not None or self._hold_pending:
                raise RuntimeError('execution_not_cancelled')
            state = self.state()
            if not all(math.isfinite(v) for v in (*goal.position, goal.yaw)):
                raise ValueError('non_finite_goal')
            lower = self.config.min_height
            if goal.ground_approach:
                if self.config.ground_z is None:
                    raise ValueError('ground_height_unconfigured')
                lower = self.config.ground_z
            if not lower <= goal.position[2] <= self.config.max_height:
                raise ValueError('goal_height_out_of_range')
            self._active = self._next_batch()
            self._started = self.clock()
            self._goal = goal
            self._planner_done = False
            self._previous_state = state
            self._settle_since = None
            try:
                self.ports.send_goal(self._batch, goal)
            except Exception:
                # A failed publish may have reached a peer: retain until cancellation succeeds.
                self.cancel()
                raise
            return self._batch

    def poll(self):
        with self._lock:
            if self._hold_pending:
                raise RuntimeError("execution_cancel_pending")
            if self._active is None:
                return None
            try:
                state = self.state()
            except RuntimeError as exc:
                self.cancel()
                return ActionResult(False, str(exc))
            for progress in self.ports.progress():
                if progress.batch != self._active:
                    continue
                if progress.skipped_mask:
                    self.cancel()
                    return ActionResult(False, 'waypoint_skipped')
                if progress.all_consumed:
                    self._planner_done = True
            if self.clock() - self._started >= self.config.action_timeout:
                reason = 'goal_settle_timeout' if self._planner_done else 'planner_timeout'
                self.cancel()
                return ActionResult(False, reason)
            previous = self._previous_state
            dt = state.source_stamp - previous.source_stamp
            if dt < 0 or dt > self.config.state_timeout:
                self.cancel()
                return ActionResult(False, 'odometry_discontinuous')
            if dt == 0:
                return None
            self._previous_state = state
            if not self._planner_done or not self._is_settled(state, previous, dt):
                self._settle_since = None
                return None
            if self._settle_since is None:
                self._settle_since = state.source_stamp
            if state.source_stamp - self._settle_since >= self.config.settle_hold_s:
                self._active = None
                return ActionResult(True)
            return None

    def _is_settled(self, state, previous, dt):
        # 缺少动态观测不能填零冒充停稳。
        if state.velocity is None or previous.velocity is None or state.yaw_rate_rad_s is None:
            return False
        acceleration = math.dist(state.velocity, previous.velocity) / dt
        yaw_error = math.atan2(math.sin(self._goal.yaw - state.yaw),
                               math.cos(self._goal.yaw - state.yaw))
        return (
            math.dist(state.position, self._goal.position) <= self.config.settle_position_m
            and state.speed <= self.config.settle_speed_m_s
            and acceleration <= self.config.settle_acceleration_m_s2
            and abs(state.yaw_rate_rad_s) <= self.config.settle_yaw_rate_rad_s
            and (self._goal.look_forward or abs(yaw_error) <= math.radians(self.config.settle_yaw_deg))
        )

    def _next_batch(self):
        if self._batch >= 2**32 - 1:
            raise RuntimeError('action_generation_exhausted')
        self._batch += 1
        return self._batch

    def _publish_hold(self):
        # Retire the old result before publishing. Failed replacement blocks new work.
        self._hold_pending = True
        state = self.state()
        batch = self._next_batch()
        self.ports.send_goal(batch, Goal(tuple(state.position), state.yaw, look_forward=False))
        self._active = None
        self._hold_pending = False

    def cancel(self):
        """取消：同一目标口发布新批次保持意图。"""
        with self._lock:
            if self._active is not None or self._hold_pending:
                self._publish_hold()

    def stop(self):
        """显式急停保留原全局信号，保持目标由 dispatcher 自己构造。"""
        with self._lock:
            self._hold_pending = True
            self.ports.stop()
            self._publish_hold()

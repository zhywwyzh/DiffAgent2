"""共享单目标执行：批次只关联动作反馈，不识别工具名字。"""
import math
import secrets
import threading
import time
from dispatcher.execution.ports import ActionResult, FlightConfig, FlightPorts, Goal


class WaypointExecution:
    def __init__(self, ports: FlightPorts, config: FlightConfig, *, clock=time.monotonic, first_batch=None):
        self.ports = ports
        self.config = config
        self.clock = clock
        self._batch = first_batch if first_batch is not None else secrets.randbelow(2**31) + 1
        self._active = None
        self._hold_pending = False
        self._started = 0.0
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
        return state

    def start(self, goal: Goal):
        with self._lock:
            if self._active is not None or self._hold_pending:
                raise RuntimeError('execution_not_cancelled')
            self.state()
            if not all(math.isfinite(v) for v in (*goal.position, goal.yaw)):
                raise ValueError('non_finite_goal')
            if not self.config.min_height <= goal.position[2] <= self.config.max_height:
                raise ValueError('goal_height_out_of_range')
            self._active = self._next_batch()
            self._started = self.clock()
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
                self.state()
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
                    self._active = None
                    return ActionResult(True)
            if self.clock() - self._started >= self.config.action_timeout:
                self.cancel()
                return ActionResult(False, 'planner_timeout')
            return None

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

"""当前任务立即释放；设备停止确认独立跟踪，不持有技能引用。"""
import math
import threading
import time
import uuid
from dataclasses import replace
from dispatcher.execution.ports import ActionKey, ActionResult, StopRecord, TrackingGoal


class ActionSession:
    def __init__(self, actions, states, commands, config, *, clock=time.monotonic, emit=None, can_send=None):
        self.actions, self.states, self.commands = actions, states, commands
        self.config, self.clock = config, clock
        self._emit = emit if emit is not None else (lambda *args, **kwargs: None)
        self._can_send = can_send if can_send is not None else (lambda: True)
        self._last_wait_log = 0.0
        self._lock = threading.RLock()
        self._blocked = threading.Event()
        self._active = None
        self._pending = None
        self._results = {}
        self._stop = None
        self._fault = None
        self._released_at = 0.0
        self._closed = False

    def state(self):
        state = self.states.snapshot()
        if state is None:
            raise RuntimeError('odometry_unavailable')
        age = self.clock() - state.received
        if not 0 <= age <= self.config.state_timeout_s or not 0 <= state.source_age + age <= self.config.state_timeout_s or state.source_age < 0:
            raise RuntimeError('odometry_stale')
        if state.source_stamp <= 0:
            raise RuntimeError('odometry_invalid')
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

    def start(self, goal, *, generation, owner):
        with self._lock:
            if self._closed:
                raise RuntimeError('execution_closed')
            if not self._can_send():
                raise RuntimeError('task_cancelled')
            if self._fault:
                raise RuntimeError(self._fault)
            if self._pending is not None or self._active is not None:
                raise RuntimeError('execution_busy')
            self.state()
            if isinstance(goal, TrackingGoal):
                if (not goal.session_id or not goal.execution_id or
                        not all(math.isfinite(v) and v > 0 for v in (goal.follow_distance_m,
                            goal.distance_tolerance_m, goal.observation_timeout_s, goal.duration_s)) or
                        not self.config.min_height <= goal.target_height_m <= self.config.max_height):
                    raise ValueError('invalid_tracking_goal')
            else:
                if not all(math.isfinite(v) for v in (*goal.position, goal.yaw)):
                    raise ValueError('non_finite_goal')
                lower = self.config.ground_z if goal.ground_approach else self.config.min_height
                if lower is None:
                    raise ValueError('ground_height_unconfigured')
                if not lower <= goal.position[2] <= self.config.max_height:
                    raise ValueError('goal_height_out_of_range')
            key = ActionKey(generation, owner)
            self._pending = (key, goal, self.clock())
            return key

    def finish(self, key):
        """内部收尾保留当前 owner，供技能汇合业务完成与停止结果。"""
        with self._lock:
            if self._active is None or self._active['key'] != key:
                raise RuntimeError('tracking_not_active')
            if 'finishing_since' not in self._active:
                self._active['finishing_since'] = self.clock()
            self.actions.cancel(self._active['handle'])

    def feedback(self, key):
        with self._lock:
            if self._active is None or self._active['key'] != key:
                return None
            return self.actions.feedback(self._active['token'])

    def request_stop(self, reason='task_cancelled', *, retry=False):
        # 可在 engine 生命周期锁被占用时设置；发送提交点再次检查。
        self._blocked.set()
        with self._lock:
            active = None
            if not retry:
                self._pending = None
                self._results.clear()
                active, self._active = self._active, None
            if self._stop is not None and self._stop.request_sent and not retry:
                return True
            if self._stop is None:
                ready = self.actions.readiness()
                self._stop = StopRecord(
                    self.clock(), ready.boot_id if ready else None,
                    ready.recovery_generation if ready else 0,
                    active['token'] if active else None,
                    active['handle'] if active else None,
                )
                self._fault = None
            record = self._stop
            sent = record.request_sent
            sends = [('emergency_stop', self.commands.stop)]
            if record.handle is not None:
                sends.append(('action_cancel', lambda: self.actions.cancel(record.handle)))
            # 两个出口分别尝试；失败后有限重试，不重置设备停止期限。
            for channel, send in sends:
                try:
                    send()
                    sent = True
                except Exception as exc:
                    self._emit('warning', 'execution_stop_send_failed', channel=channel, reason=str(exc))
            self._stop = replace(record, request_sent=sent, last_attempt=self.clock())
            return sent

    def cancel(self, owner=None):
        with self._lock:
            keys = [self._active['key']] if self._active else []
            if self._pending:
                keys.append(self._pending[0])
            if owner is not None and not any(key.owner is owner for key in keys):
                return
            if not keys and self._stop is None:
                self._results.clear()
                return
        self.request_stop()

    def stop(self):
        if not self.request_stop('safety_stop'):
            raise RuntimeError('execution_stop_endpoint_unavailable')

    def _pump(self):
        now = self.clock()
        ready = self.actions.readiness()
        fresh = ready is not None and 0 <= now - ready.received <= self.config.state_timeout_s
        stop = self._stop
        if stop is not None:
            if stop.boot_id is None and fresh:
                # 首次收到状态仅建立基线；再次请求停止后才接受确认。
                stop = replace(stop, boot_id=ready.boot_id, recovery_generation=ready.recovery_generation, request_sent=False)
                self._stop = stop
            acknowledged = stop.request_sent and fresh and ready.received > stop.started and ready.ready and ready.stop_confirmed and (
                ready.boot_id != stop.boot_id or ready.recovery_generation > stop.recovery_generation)
            if acknowledged:
                self._stop = None
                self._fault = None
                self._released_at = now
                self._blocked.clear()
            elif now - stop.started >= self.config.stop_timeout_s + self.config.state_timeout_s:
                self._stop = None  # 丢弃传输句柄；闭锁属于设备，不保留旧任务。
                self._fault = 'execution_stop_timeout'
            elif now-stop.last_attempt >= 0.25:
                self.request_stop('stop_retry', retry=True)
        for event in self.actions.events():
            active = self._active
            if active is None or event.token != active['token']:
                continue
            if event.status == 'active':
                active['admitted'] = True
                continue
            if event.result is None:
                continue
            result = event.result
            if not fresh or ready.boot_id != active['boot_id']:
                result = ActionResult(False, 'planner_disconnected')
            key = active['key']
            if result.stop_confirmed:
                self._active = None
                self._released_at = now
            else:
                self.request_stop(result.reason or 'execution_stop_unconfirmed')
            self._results[key] = result
        active = self._active
        if active is not None:
            limit = (active['duration_s'] + self.config.stop_timeout_s + self.config.state_timeout_s
                     if active['admitted'] else self.config.admission_timeout_s)
            since = active.get('finishing_since', active['sent_at'])
            if 'finishing_since' in active:
                limit = self.config.stop_timeout_s + self.config.state_timeout_s
            if not fresh or ready.boot_id != active['boot_id'] or now-since >= limit:
                key = active['key']
                reason = 'planner_disconnected' if not fresh else ('planner_restarted' if ready.boot_id != active['boot_id'] else 'action_result_timeout')
                self.request_stop(reason)
                self._results[key] = ActionResult(False, reason)
        if self._pending is not None:
            key, goal, since = self._pending
            if not self._can_send():
                self._pending = None
            elif self._fault:
                self._results[key] = ActionResult(False, self._fault)
                self._pending = None
            elif (not self._blocked.is_set() and self._stop is None and self._active is None and fresh
                  and ready.ready and ready.stop_confirmed and ready.received > self._released_at and self.actions.connected(goal)):
                self._pending = None
                token = uuid.uuid4().hex
                self._active = dict(key=key, token=token, handle=None, sent_at=now, admitted=False, boot_id=ready.boot_id, duration_s=goal.duration_s if isinstance(goal, TrackingGoal) else self.config.action_timeout_s)
                try:
                    # 此锁串行化发送与停止；回调只携带 token，绝不捕获 owner。
                    if self._blocked.is_set() or not self._can_send():
                        self._active = None
                        return
                    self._active['handle'] = self.actions.send(token, goal)
                except Exception:
                    self.request_stop('goal_send_unconfirmed')
                    self._results[key] = ActionResult(False, 'goal_send_unconfirmed')
            elif now-since >= self.config.connect_timeout_s + self.config.stop_timeout_s:
                self._results[key] = ActionResult(False, 'execution_not_ready')
                self._pending = None

    def tick(self):
        with self._lock:
            self._pump()
            now = self.clock()
            if now-self._last_wait_log >= 2.0 and (self._active or self._pending or self._stop or self._fault):
                self._last_wait_log = now
                ready = self.actions.readiness()
                age = None if ready is None else now-ready.received
                self._emit('info', 'execution_wait', reason=self._fault or ('device_stopping' if self._stop else 'action_result'),
                           input_state='never' if ready is None else ('stale' if age > self.config.state_timeout_s else 'received'),
                           input_age_s=age, phase=None if ready is None else ready.phase)

    def require_idle(self):
        with self._lock:
            self._pump()
            ready = self.actions.readiness()
            if (self._blocked.is_set() or self._fault or self._active is not None or self._pending is not None
                    or ready is None or not ready.ready or not ready.stop_confirmed
                    or not 0 <= self.clock()-ready.received <= self.config.state_timeout_s):
                raise RuntimeError('execution_not_ready')

    def poll(self, *, generation, owner):
        with self._lock:
            self._pump()
            return self._results.pop(ActionKey(generation, owner), None)

    def close(self):
        with self._lock:
            self._closed = True
            self.cancel()
        deadline = self.clock()+self.config.stop_timeout_s+self.config.state_timeout_s
        while self.clock() < deadline:
            with self._lock:
                self._pump()
                if self._active is None and self._stop is None and not self._blocked.is_set():
                    return
            time.sleep(0.05)
        raise RuntimeError('execution_close_stop_unconfirmed')

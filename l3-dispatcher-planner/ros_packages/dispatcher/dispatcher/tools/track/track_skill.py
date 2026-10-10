"""连续跟踪流程；视觉和运动生命周期经宿主端口隔离。"""
import math
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dispatcher.tools.skill_api import SkillBase, SkillVerdict
from dispatcher.tools.track.client import UETrackClient
from dispatcher.tools.track.producer import TrackingProducer
from dispatcher.execution.ports import TrackingGoal


class TrackSkill(SkillBase):
    name = 'navigation.track'
    requires_perception = False
    synchronous = False

    def __init__(self, host):
        super().__init__(host)
        self.host = host
        self.worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix='tracking')
        self.lock = threading.Lock()
        self.future = self.producer = None
        self.latest = None
        self.active = False
        self.phase = 'STARTING'
        self.key = None
        self.finished = False
        self.generation = 0
        self.closed = False

    def plan_tick(self, command):
        c = self.host.config
        try:
            if self.closed or (self.future is not None and not self.future.done()):
                raise RuntimeError('tracker_busy')
            a = command.call.arguments
            frame = self.host.frames.seed(float(a['image_stamp']))
            if frame is None or not 0 <= self.host.frames.now() - frame.stamp <= c.seed_max_age_s:
                raise ValueError('track_seed_expired')
            box = a['bbox']
            if (len(box) != 4 or not all(type(v) in (int, float) and math.isfinite(v) for v in box)
                    or not 0 <= box[0] < box[2] <= frame.rgb.shape[1]
                    or not 0 <= box[1] < box[3] <= frame.rgb.shape[0]):
                raise ValueError('invalid_track_seed')
            self.host.state()
            self.host.arm(self)
            self.started = time.monotonic()
            self.lost_since = None
            self.candidate = None
            self.last_sequence = self.last_stamp = self.last_state_stamp = 0
            self.last_report = 0
            self.args = dict(a)
            self.phase, self.active, self.finished = 'STARTING', True, False
            self.execution_id = ''
            self.generation += 1
            generation = self.generation
            self.key = None
            self.latest = None
            client = UETrackClient(c.api_url, a['session_id'], c.request_timeout_s, c.init_timeout_s)
            def observe(state, output, current_frame):
                with self.lock:
                    if self.active and self.generation == generation:
                        self.latest = state, output, current_frame
            self.producer = TrackingProducer(client, self.host.frames, frame, box, observe,
                                              self.host.frames.now, c.observation_timeout_s)
            self.future = self.worker.submit(self.producer.run)
        except Exception as exc:
            self._fail(str(exc))
        return True

    def wait_action_tick(self):
        if not self.active:
            return
        c = self.host.config
        now = time.monotonic()
        try:
            if now - self.started >= c.session_timeout_s:
                raise RuntimeError('track_session_timeout')
            if now-self.last_report >= 2.0:
                self.last_report = now
                self.host.report(self.phase, now-self.started)
            if self.future.done():
                raise RuntimeError(self.future.result() or 'track_execution_failed')
            with self.lock:
                latest = self.latest
            good = False
            if latest is not None:
                state, output, frame = latest
                good = (output.ok and 0 <= now-frame.received <= c.observation_timeout_s
                        and 0 <= self.host.frames.now()-frame.stamp <= c.observation_timeout_s)
                if output.submit_seq != self.last_sequence:
                    self.host.publish_telemetry(state, output, frame, self.args['session_id'], self.execution_id)
                    self.last_sequence = output.submit_seq
            if self.key is None and good and self.phase in ('STARTING', 'HOLD'):
                self.host.require_idle()
                self.execution_id = uuid.uuid4().hex
                goal = TrackingGoal(self.args['session_id'], self.execution_id, c.follow_distance_m,
                    c.distance_tolerance_m, c.target_height_m, c.observation_timeout_s,
                    max(0.01, c.session_timeout_s-(now-self.started)))
                self.key = self.host.start_tracking(self, goal)
                self.leg_started = now
                self.last_stamp = self.last_state_stamp = 0
                self.candidate = None
                self.phase = 'ACTIVE'
            if self.key is not None:
                if good and self.phase == 'ACTIVE':
                    self.host.publish_observation(output, frame, self.args['session_id'], self.execution_id)
                result = self.host.poll_tracking(self.key)
                if result is not None:
                    self.key = None
                    if not result.stop_confirmed:
                        raise RuntimeError('track_stop_unconfirmed')
                    if result.reason == 'track_observation_lost':
                        self.finished = False
                        self.phase = 'HOLD'
                        self.lost_since = self.lost_since or now
                    elif self.phase != 'STOPPING' or result.reason != 'cancelled':
                        raise RuntimeError(result.reason or 'track_execution_failed')
                    if self.finished:
                        self._stop_producer()
                        self.host.complete(self, {'completion': 'workflow_result', 'reason': 'track_reached'})
                        return
                    self.phase = 'HOLD'
                feedback = self.host.tracking_feedback(self.key) if self.key else None
                fresh = (good and feedback is not None and feedback.valid and
                         0 <= now-feedback.received <= c.observation_timeout_s and
                         0 <= self.host.frames.now()-feedback.stamp <= c.observation_timeout_s)
                if self.phase == 'ACTIVE':
                    if fresh:
                        self.lost_since = None
                        self._check_finish(feedback)
                    else:
                        self.candidate = None
                    if not fresh and ((feedback is not None and now-self.leg_started > c.observation_timeout_s)
                          or now-self.leg_started > c.init_timeout_s):
                        self._begin_stop(False)
                        self.lost_since = self.lost_since or now
            if not good and self.key is None and self.phase != 'STARTING':
                self.lost_since = self.lost_since or now
            if self.phase == 'STARTING' and now-self.started >= c.init_timeout_s:
                raise RuntimeError('track_init_timeout')
            if self.lost_since is not None and now-self.lost_since >= c.loss_timeout_s:
                raise RuntimeError('track_lost')
        except RuntimeError as exc:
            # 旧运动停止期间暂时不可准入，保持等待但不重置预算。
            if str(exc) == 'execution_not_ready' and self.phase == 'HOLD':
                if self.lost_since is not None and now-self.lost_since >= c.loss_timeout_s:
                    self._fail('track_lost')
                return
            self._fail(str(exc))
        except Exception as exc:
            self._fail(str(exc) or 'track_execution_failed')

    def _check_finish(self, feedback):
        c = self.host.config
        if feedback.stamp <= self.last_stamp:
            return
        state = self.host.state()
        if state.source_stamp <= self.last_state_stamp:
            self.candidate = None
            return
        if ((self.last_stamp and feedback.stamp-self.last_stamp > c.observation_timeout_s)
                or (self.last_state_stamp and state.source_stamp-self.last_state_stamp > c.observation_timeout_s)):
            self.candidate = None
        self.last_stamp = feedback.stamp
        self.last_state_stamp = state.source_stamp
        delta = tuple(x-y for x,y in zip(feedback.position, state.position))
        yaw = math.atan2(delta[1], delta[0])-state.yaw
        stable = (abs(math.sqrt(sum(x*x for x in delta))-c.follow_distance_m) <= c.distance_tolerance_m
                  and abs(math.atan2(math.sin(yaw), math.cos(yaw))) <= c.yaw_tolerance_rad
                  and state.speed <= c.aircraft_speed_m_s
                  and math.sqrt(sum(v*v for v in feedback.velocity)) <= c.target_speed_m_s)
        self.candidate = (self.candidate if self.candidate is not None else feedback.stamp) if stable else None
        if self.candidate is not None and feedback.stamp-self.candidate >= c.finish_hold_s:
            self._begin_stop(True)

    def _begin_stop(self, finished):
        self.finished = finished
        self.candidate = None
        self.phase = 'STOPPING'
        self.host.finish_tracking(self.key)

    def _stop_producer(self):
        with self.lock:
            self.active = False
            self.generation += 1
            self.latest = None
        if self.producer is not None:
            self.producer.cancel()
            self.producer = None

    def _fail(self, reason):
        self._stop_producer()
        self.key = None
        self.host.fail_sequence(reason)

    def on_cancel(self):
        self._stop_producer()
        self.key = None
        self.finished = False
        self.host.cancel_execution(self)

    on_global_stop = on_cancel
    on_new_prompt_task = on_cancel
    on_plan_cycle_reset = on_cancel

    def on_action_result(self, result):
        return SkillVerdict.IDLE

    def close(self):
        self.closed = True
        self.on_cancel()
        self.worker.shutdown(wait=True, cancel_futures=True)

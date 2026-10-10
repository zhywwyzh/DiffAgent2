"""原生 action 收发；回调仅投递绑定发送代次的不可变事件。"""
import queue
from contextlib import ExitStack
import threading
import time
import actionlib
import rospy
from actionlib_msgs.msg import GoalStatus
from geometry_msgs.msg import Point
from quadrotor_msgs.msg import ExecuteWaypointsAction, ExecuteWaypointsGoal, ExecutionState as RosExecutionState, YawPolicy
from quadrotor_msgs.msg import TrackTargetAction, TrackTargetGoal
from dispatcher.tools.track.ports import TrackingFeedback
from dispatcher.execution.ports import ActionEvent, ActionResult, ExecutionState, TrackingGoal


class RosPlannerActionClient:
    def __init__(self, world_frame):
        self._frame = world_frame
        self._events = queue.SimpleQueue()
        self._lock = threading.Lock()
        self._ready = None
        self._feedback = {}
        self._feedback_token = None
        with ExitStack() as resources:
            self._tracking = actionlib.ActionClient('/planner/track_target', TrackTargetAction)
            resources.callback(self._tracking.stop)
            self._client = actionlib.ActionClient('/planner/execute_waypoints', ExecuteWaypointsAction)
            resources.callback(self._client.stop)
            self._subscriber = rospy.Subscriber('/planner/execution_state', RosExecutionState,
                                                 self._on_readiness, queue_size=1)
            resources.callback(self._subscriber.unregister)
            self._resources = resources.pop_all()

    def _on_readiness(self, msg):
        value = ExecutionState(msg.boot_id, msg.recovery_generation, msg.ready, msg.stop_confirmed, msg.phase, time.monotonic())
        with self._lock:
            self._ready = value

    def readiness(self):
        with self._lock:
            return self._ready

    def connected(self, goal=None):
        client = self._tracking if isinstance(goal, TrackingGoal) else self._client
        return all(endpoint.get_num_connections() > 0 for endpoint in (
            client.pub_goal, client.pub_cancel, client.status_sub,
            client.result_sub, client.feedback_sub))

    def send(self, token, goal):
        with self._lock:
            self._feedback_token = token
            self._feedback.clear()
        client = self._tracking if isinstance(goal, TrackingGoal) else self._client
        if isinstance(goal, TrackingGoal):
            msg = TrackTargetGoal()
            for name in ('session_id', 'execution_id', 'follow_distance_m', 'distance_tolerance_m',
                         'target_height_m', 'observation_timeout_s', 'duration_s'):
                setattr(msg, name, getattr(goal, name))
        else:
            msg = ExecuteWaypointsGoal()
            msg.header.frame_id = self._frame
            msg.header.stamp = rospy.Time.now()
            msg.target.waypoints = [Point(*goal.position)]
            msg.target.yaw = goal.yaw
            msg.target.look_forward = goal.look_forward
            msg.target.ground_approach = goal.ground_approach
            msg.target.yaw_policy.mode = YawPolicy.LOW_SPEED if goal.yaw_low_speed else YawPolicy.NORMAL
            msg.target.yaw_policy.path = YawPolicy.SHORTEST

        def transition(handle):
            state = handle.get_comm_state()
            if state == actionlib.CommState.ACTIVE:
                self._events.put(ActionEvent(token, 'active'))
            elif state == actionlib.CommState.DONE:
                status, result = handle.get_goal_status(), handle.get_result()
                with self._lock:
                    self._feedback.pop(token, None)
                reason = result.reason if result is not None else 'missing_action_result'
                self._events.put(ActionEvent(token, 'terminal', ActionResult(
                    status == GoalStatus.SUCCEEDED and result is not None and result.state_valid and result.stop_confirmed, reason,
                    result.stop_confirmed if result is not None else False)))
        def feedback(handle, value):
            if isinstance(goal, TrackingGoal):
                item = TrackingFeedback(time.monotonic(), value.observation_stamp.to_sec(), value.sequence,
                    value.valid, (value.position.x, value.position.y, value.position.z),
                    (value.velocity.x, value.velocity.y, value.velocity.z), value.phase)
                with self._lock:
                    if token == self._feedback_token:
                        self._feedback[token] = item
        return client.send_goal(msg, transition_cb=transition, feedback_cb=feedback)

    def feedback(self, token):
        with self._lock:
            return self._feedback.get(token)

    def cancel(self, handle):
        if handle is None:
            raise RuntimeError('goal_handle_unavailable')
        handle.cancel()

    def events(self):
        result = []
        while True:
            try:
                result.append(self._events.get_nowait())
            except queue.Empty:
                return tuple(result)

    def close(self):
        self._resources.close()

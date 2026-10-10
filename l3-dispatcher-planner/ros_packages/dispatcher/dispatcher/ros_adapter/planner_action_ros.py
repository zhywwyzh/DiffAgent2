"""原生 action 收发；回调仅投递绑定发送代次的不可变事件。"""
import queue
import threading
import time
import actionlib
import rospy
from actionlib_msgs.msg import GoalStatus
from geometry_msgs.msg import Point
from quadrotor_msgs.msg import ExecuteWaypointsAction, ExecuteWaypointsGoal, ExecutionState as RosExecutionState, YawPolicy
from dispatcher.execution.ports import ActionEvent, ActionResult, ExecutionState


class RosPlannerActionClient:
    def __init__(self, world_frame):
        self._frame = world_frame
        self._events = queue.SimpleQueue()
        self._lock = threading.Lock()
        self._ready = None
        self._client = actionlib.ActionClient('/planner/execute_waypoints', ExecuteWaypointsAction)
        try:
            self._subscriber = rospy.Subscriber('/planner/execution_state', RosExecutionState,
                                                 self._on_readiness, queue_size=1)
        except Exception:
            self._client.stop()
            raise

    def _on_readiness(self, msg):
        value = ExecutionState(msg.boot_id, msg.recovery_generation, msg.ready, msg.stop_confirmed, msg.phase, time.monotonic())
        with self._lock:
            self._ready = value

    def readiness(self):
        with self._lock:
            return self._ready

    def connected(self):
        return all(endpoint.get_num_connections() > 0 for endpoint in (
            self._client.pub_goal, self._client.pub_cancel, self._client.status_sub,
            self._client.result_sub, self._client.feedback_sub))

    def send(self, token, goal):
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
                reason = result.reason if result is not None else 'missing_action_result'
                self._events.put(ActionEvent(token, 'terminal', ActionResult(
                    status == GoalStatus.SUCCEEDED and result is not None and result.state_valid and result.stop_confirmed, reason,
                    result.stop_confirmed if result is not None else False)))
        return self._client.send_goal(msg, transition_cb=transition)

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
        self._subscriber.unregister()
        self._client.stop()

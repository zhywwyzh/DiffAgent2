"""EGO 直连端口：只转换消息并保存完整快照，不推进任务 FSM。"""
from collections import deque
import math
import threading
import time

import rospy
from nav_msgs.msg import Odometry
from std_msgs.msg import Empty
from quadrotor_msgs.msg import LocalGoalSet, WaypointProgress, TakeoffLand

from dispatcher.tools.flight.ports import FlightState, Progress


class RosFlightPorts:
    def __init__(self, *, drone_id=0, odometry_topic='/ekf_quat/ekf_odom',
                 goal_topic='/planner/local_goal', progress_topic='/planner/waypoint_progress',
                 stop_topic='/command/emergency_stop',
                 takeoff_land_topic='/px4ctrl/takeoff_land'):
        self.drone_id = drone_id
        self._state = None
        self._progress = deque(maxlen=256)
        self._lock = threading.RLock()
        self._handles = []
        try:
            self._goal = self._publisher(goal_topic, LocalGoalSet)
            self._stop = self._publisher(stop_topic, Empty)
            self._flight = self._publisher(takeoff_land_topic, TakeoffLand)
            self._handles.append(rospy.Subscriber(odometry_topic, Odometry, self._on_state, queue_size=1))
            self._handles.append(rospy.Subscriber(progress_topic, WaypointProgress, self._on_progress, queue_size=32))
        except Exception:
            self.close()
            raise

    def _publisher(self, topic, kind):
        publisher = rospy.Publisher(topic, kind, queue_size=10)
        self._handles.append(publisher)
        return publisher

    def _on_state(self, message):
        position = message.pose.pose.position
        q = message.pose.pose.orientation
        velocity = message.twist.twist.linear
        norm = math.sqrt(q.x*q.x + q.y*q.y + q.z*q.z + q.w*q.w)
        yaw = float('nan') if not norm else math.atan2(
            2*(q.w*q.z + q.x*q.y)/norm**2, 1 - 2*(q.y*q.y + q.z*q.z)/norm**2)
        stamp = message.header.stamp.to_sec()
        state = FlightState((position.x, position.y, position.z), yaw,
                            math.sqrt(velocity.x**2 + velocity.y**2 + velocity.z**2),
                            time.monotonic(), stamp, message.header.frame_id,
                            rospy.Time.now().to_sec() - stamp)
        with self._lock:
            self._state = state

    def _on_progress(self, message):
        with self._lock:
            self._progress.append(Progress(message.batch_id, message.all_consumed, message.skipped_mask))

    def snapshot(self):
        with self._lock:
            return self._state

    def progress(self):
        with self._lock:
            return tuple(self._progress)

    @staticmethod
    def _send(publisher, message):
        if publisher.get_num_connections() == 0:
            raise RuntimeError('execution_endpoint_unavailable')
        publisher.publish(message)

    def send_goal(self, batch, goal):
        message = LocalGoalSet()
        message.drone_id = self.drone_id
        message.batch_id = batch
        message.waypoints = list(goal.position)
        message.yaw = goal.yaw
        message.look_forward = goal.look_forward
        message.yaw_mode = LocalGoalSet.YAW_MODE_NORMAL
        message.yaw_path_mode = LocalGoalSet.YAW_PATH_SHORTEST
        self._send(self._goal, message)

    def takeoff(self):
        self._send(self._flight, TakeoffLand(takeoff_land_cmd=TakeoffLand.TAKEOFF))

    def land(self):
        self._send(self._flight, TakeoffLand(takeoff_land_cmd=TakeoffLand.LAND))

    def stop(self):
        # Global notification has the same semantics as CoreChannels; the domain
        # requires a connected goal consumer for the subsequent hold replacement.
        self._stop.publish(Empty())

    def close(self):
        errors = []
        for handle in reversed(self._handles):
            try:
                handle.unregister()
            except Exception as exc:
                errors.append(exc)
        self._handles.clear()
        if errors:
            raise RuntimeError("flight_port_cleanup_failed") from errors[0]

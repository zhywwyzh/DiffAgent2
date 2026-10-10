"""里程计完整快照的唯一写入方。"""
import math
import threading
import time
import rospy
from nav_msgs.msg import Odometry
from dispatcher.execution.ports import FlightState


class RosFlightState:
    def __init__(self, topic):
        self._state = None
        self._lock = threading.Lock()
        self._subscriber = rospy.Subscriber(topic, Odometry, self._receive, queue_size=1)

    def _receive(self, message):
        p, q = message.pose.pose.position, message.pose.pose.orientation
        v = message.twist.twist.linear
        n = q.x*q.x + q.y*q.y + q.z*q.z + q.w*q.w
        yaw = math.atan2(2*(q.w*q.z+q.x*q.y)/n, 1-2*(q.y*q.y+q.z*q.z)/n) if n else float('nan')
        state = FlightState((p.x,p.y,p.z), yaw, math.sqrt(v.x*v.x+v.y*v.y+v.z*v.z),
                            time.monotonic(), message.header.stamp.to_sec(), message.header.frame_id,
                            rospy.Time.now().to_sec()-message.header.stamp.to_sec(),
                            (v.x,v.y,v.z), message.twist.twist.angular.z)
        with self._lock:
            self._state = state

    def snapshot(self):
        with self._lock:
            return self._state

    def close(self):
        self._subscriber.unregister()

"""同步起降转交与独立全局急停的 ROS 出口。"""
import rospy
from std_msgs.msg import Empty
from quadrotor_msgs.msg import TakeoffLand


class RosFlightCommands:
    def __init__(self):
        self._flight = rospy.Publisher('/px4ctrl/takeoff_land', TakeoffLand, queue_size=10)
        try:
            self._stop = rospy.Publisher('/command/emergency_stop', Empty, queue_size=10)
        except Exception:
            self._flight.unregister()
            raise

    def takeoff(self):
        self._send(TakeoffLand.TAKEOFF)

    def land(self):
        self._send(TakeoffLand.LAND)

    def _send(self, command):
        if not self._flight.get_num_connections():
            raise RuntimeError('execution_endpoint_unavailable')
        self._flight.publish(TakeoffLand(takeoff_land_cmd=command))

    def stop(self):
        if not self._stop.get_num_connections():
            raise RuntimeError('execution_stop_endpoint_unavailable')
        self._stop.publish(Empty())

    def close(self):
        self._stop.unregister()
        self._flight.unregister()
